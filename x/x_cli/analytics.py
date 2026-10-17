"""Validated, lossless analytics requests for X API v2 and Ads API v12."""
import gzip
import json
import re
from datetime import datetime
from urllib.parse import quote, urlsplit

import requests

from .client import ClientError, XClient

METRIC_GROUPS = ("public_metrics", "non_public_metrics", "organic_metrics", "promoted_metrics")
POST_ANALYTICS_FIELDS = "app_install_attempts,app_opens,bookmarks,detail_expands,email_tweet,engagements,follows,hashtag_clicks,id,impressions,likes,media_views,permalink_clicks,quote_tweets,replies,retweets,shares,timestamp,timestamped_metrics,unfollows,unlikes,url_clicks,user_profile_clicks"
MEDIA_ANALYTICS_FIELDS = "cta_url_clicks,cta_watch_clicks,media_key,play_from_tap,playback25,playback50,playback75,playback_complete,playback_start,timestamp,timestamped_metrics,video_views,watch_time_ms"
USAGE_FIELDS = "cap_reset_day,daily_client_app_usage,daily_project_usage,project_cap,project_id,project_usage"
ADS_ENTITIES = ("ACCOUNT", "CAMPAIGN", "FUNDING_INSTRUMENT", "LINE_ITEM", "PROMOTED_ACCOUNT", "PROMOTED_TWEET")
ADS_ACTIVE_ENTITIES = ADS_ENTITIES[1:]
ADS_PLACEMENTS = ("ALL_ON_TWITTER", "SPOTLIGHT", "TREND")
ADS_METRICS = ("BILLING", "ENGAGEMENT", "LIFE_TIME_VALUE_MOBILE_CONVERSION", "MOBILE_CONVERSION", "VIDEO", "WEB_CONVERSION")
ADS_SEGMENTS = ("AGE", "GENDER", "METROS", "REGIONS", "PLATFORMS", "CONVERSION_TAGS")


def choice(value, allowed, label):
    if value not in allowed:
        raise ClientError(f"{label} must be one of: {', '.join(allowed)}")
    return value


def csv_values(value, label, maximum=None, allowed=None, pattern=None):
    values = [part.strip() for part in value.split(",")]
    if not all(values) or len(values) != len(set(values)):
        raise ClientError(f"{label} must contain nonempty, unique comma-separated values")
    if maximum and len(values) > maximum:
        raise ClientError(f"{label} accepts at most {maximum} values")
    for item in values:
        if allowed:
            choice(item, allowed, label)
        if pattern and not re.fullmatch(pattern, item):
            raise ClientError(f"Invalid {label}: {item}")
    return ",".join(values)


def time_range(start, end, max_days=None, whole_hours=False):
    parsed = []
    for label, value in (("start_time", start), ("end_time", end)):
        if value is None:
            parsed.append(None)
            continue
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ClientError(f"{label} must be an ISO 8601 timestamp with timezone") from exc
        if stamp.tzinfo is None:
            raise ClientError(f"{label} must include a timezone")
        if whole_hours and (stamp.minute or stamp.second or stamp.microsecond):
            raise ClientError(f"{label} must be expressed in whole hours")
        parsed.append(stamp)
    if all(parsed):
        seconds = (parsed[1] - parsed[0]).total_seconds()
        if seconds <= 0:
            raise ClientError("end_time must be later than start_time")
        if max_days and seconds > max_days * 86400:
            raise ClientError(f"Time range must not exceed {max_days} days")
    return {key: value for key, value in (("start_time", start), ("end_time", end)) if value is not None}


def identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ClientError("ID must contain only letters, numbers, underscores or hyphens")
    return quote(value, safe="")


class AnalyticsClient(XClient):
    """Return complete API reports, including includes, pagination and partial errors."""

    def metric_params(self, metrics, media=False):
        groups = csv_values(metrics, "metrics", allowed=METRIC_GROUPS)
        if self.auth_mode == "bearer" and groups != "public_metrics":
            raise ClientError("Private, organic and promoted metrics require OAuth 1.0a user credentials")
        if media:
            return {"media.fields": f"media_key,type,duration_ms,{groups}"}
        return {
            "post.fields": f"created_at,attachments,{groups}",
            "expansions": "attachments.media_keys,author_id",
            "media.fields": f"media_key,type,duration_ms,{groups}",
            "user.fields": "public_metrics",
        }

    def posts(self, ids, metrics="public_metrics"):
        params = self.metric_params(metrics)
        params["ids"] = csv_values(ids, "ids", 100, pattern=r"[0-9]{1,19}")
        return self._make_request("GET", "/2/tweets", params=params)

    def media(self, keys, metrics="public_metrics"):
        params = self.metric_params(metrics, media=True)
        params["media_keys"] = csv_values(keys, "media_keys", 100, pattern=r"[0-9]+_[0-9]+")
        return self._make_request("GET", "/2/media", params=params)

    def user(self, user_id=None, username=None):
        if user_id and username:
            raise ClientError("Choose either user ID or username, not both")
        endpoint = f"/2/users/{identifier(user_id)}" if user_id else (
            f"/2/users/by/username/{identifier(username.removeprefix('@'))}" if username else "/2/users/me"
        )
        if endpoint.endswith("/me") and self.auth_mode == "bearer":
            raise ClientError("Current user lookup requires OAuth1; supply --user-id or --username for bearer auth")
        return self._make_request("GET", endpoint, params={"user.fields": "created_at,public_metrics,verified_followers_count,subscriber_count"})

    def timeline(self, user_id, metrics, limit, start, end, token, exclude):
        if not 5 <= limit <= 100:
            raise ClientError("limit must be between 5 and 100 (one API page)")
        if not user_id:
            report = self.user()
            if report.get("errors") or not report.get("data", {}).get("id"):
                raise ClientError(f"Cannot resolve current user: {json.dumps(report)}")
            user_id = report["data"]["id"]
        params = {**self.metric_params(metrics), **time_range(start, end), "max_results": limit}
        if token:
            params["pagination_token"] = token
        if exclude:
            params["exclude"] = csv_values(exclude, "exclude", allowed=("replies", "retweets"))
        return self._make_request("GET", f"/2/users/{identifier(user_id)}/tweets", params=params)

    def series(self, kind, ids, start, end, granularity, fields):
        if self.auth_mode != "oauth1":
            raise ClientError("Post/media analytics require user authentication, not app-only bearer tokens")
        is_media = kind == "media"
        params = time_range(start, end)
        params["granularity"] = choice(granularity, ("hourly", "daily", "total") if is_media else ("hourly", "daily", "weekly", "total"), "granularity")
        params["media_keys" if is_media else "ids"] = csv_values(ids, "media_keys" if is_media else "ids", 100, pattern=r"[0-9]+_[0-9]+" if is_media else r"[0-9]{1,19}")
        supported = MEDIA_ANALYTICS_FIELDS if is_media else POST_ANALYTICS_FIELDS
        params["media_analytics.fields" if is_media else "analytics.fields"] = csv_values(fields or supported, "fields", allowed=supported.split(","))
        return self._make_request("GET", f"/2/{'media' if is_media else 'tweets'}/analytics", params=params)

    def counts(self, query, archive, start, end, granularity, token, since_id=None, until_id=None):
        if self.auth_mode != "bearer":
            raise ClientError("Post counts require app bearer authentication")
        if not query.strip() or len(query) > 4096:
            raise ClientError("query must contain 1-4096 characters")
        params = {"query": query, "granularity": choice(granularity, ("minute", "hour", "day"), "granularity"), **time_range(start, end)}
        if token:
            params["next_token"] = token
        for name, value in (("since_id", since_id), ("until_id", until_id)):
            if value:
                params[name] = csv_values(value, name, 1, pattern=r"[0-9]{1,19}")
        return self._make_request("GET", f"/2/tweets/counts/{'all' if archive else 'recent'}", params=params)

    def usage(self, days=7, credits=False):
        if self.auth_mode != "bearer":
            raise ClientError("API usage requires app bearer authentication")
        if not 1 <= days <= 90:
            raise ClientError("days must be between 1 and 90")
        return self._make_request("GET", "/2/usage/credits" if credits else "/2/usage/tweets", params=None if credits else {"days": days, "usage.fields": USAGE_FIELDS})

    def ads_accounts(self, limit=200, cursor=None, query=None, account_ids=None, with_deleted=False):
        if not 1 <= limit <= 1000:
            raise ClientError("limit must be between 1 and 1000")
        params = {"count": limit, "with_deleted": str(with_deleted).lower()}
        if cursor:
            params["cursor"] = cursor
        if query:
            params["q"] = query
        if account_ids:
            params["account_ids"] = csv_values(account_ids, "account_ids", pattern=r"[A-Za-z0-9]+")
        return self._make_request("GET", "/12/accounts", params=params, ads=True)

    def ads_report(self, account, entity, ids, start, end, granularity, metrics, placement, asynchronous=False, segmentation=None, country=None):
        if segmentation and not asynchronous:
            raise ClientError("Segmentation requires an asynchronous Ads report")
        params = time_range(start, end, max_days=(45 if segmentation else 90) if asynchronous else 7, whole_hours=True)
        params.update(entity=choice(entity, ADS_ENTITIES, "entity"), entity_ids=csv_values(ids, "entity_ids", 20, pattern=r"[A-Za-z0-9]+"), granularity=choice(granularity, ("HOUR", "DAY", "TOTAL"), "granularity"), metric_groups=csv_values(metrics, "metric_groups", allowed=ADS_METRICS), placement=choice(placement, ADS_PLACEMENTS, "placement"))
        groups = params["metric_groups"].split(",")
        if "MOBILE_CONVERSION" in groups and len(groups) > 1:
            raise ClientError("MOBILE_CONVERSION must be requested separately")
        if segmentation:
            params["segmentation_type"] = choice(segmentation, ADS_SEGMENTS, "segmentation")
            if segmentation in ("METROS", "REGIONS") and not country:
                raise ClientError("METROS/REGIONS segmentation requires --country targeting ID")
            if segmentation == "CONVERSION_TAGS" and groups != ["WEB_CONVERSION"]:
                raise ClientError("CONVERSION_TAGS requires only WEB_CONVERSION metrics")
        if country:
            params["country"] = country
        endpoint = f"/12/stats/{'jobs/' if asynchronous else ''}accounts/{identifier(account)}"
        return self._make_request("POST" if asynchronous else "GET", endpoint, params=params, ads=True, retry=not asynchronous)

    def ads_jobs(self, account, ids):
        return self._make_request("GET", f"/12/stats/jobs/accounts/{identifier(account)}", params={"job_ids": csv_values(ids, "job_ids", 200, pattern=r"[0-9]+")}, ads=True)

    def ads_active(self, account, entity, start, end, campaigns=None, funding=None, line_items=None):
        params = {"entity": choice(entity, ADS_ACTIVE_ENTITIES, "entity"), **time_range(start, end, max_days=90, whole_hours=True)}
        scopes = [("campaign_ids", campaigns), ("funding_instrument_ids", funding), ("line_item_ids", line_items)]
        if sum(bool(value) for _, value in scopes) > 1:
            raise ClientError("Choose one entity scope: campaigns, funding instruments or line items")
        for key, value in scopes:
            if value:
                params[key] = csv_values(value, key, 200, pattern=r"[A-Za-z0-9]+")
        return self._make_request("GET", f"/12/stats/accounts/{identifier(account)}/active_entities", params=params, ads=True)

    def ads_reach(self, account, ids, start, end, funding=False):
        resource = "funding_instruments" if funding else "campaigns"
        params = time_range(start, end, whole_hours=True)
        params["funding_instrument_ids" if funding else "campaign_ids"] = csv_values(ids, "entity_ids", 20, pattern=r"[A-Za-z0-9]+")
        return self._make_request("GET", f"/12/stats/accounts/{identifier(account)}/reach/{resource}", params=params, ads=True)

    def ads_download(self, account, job_id):
        report = self.ads_jobs(account, job_id)
        if report.get("errors"):
            raise ClientError(f"Ads job lookup failed: {json.dumps(report['errors'])}")
        jobs = report.get("data", [])
        job = next((row for row in jobs if str(row.get("id_str", row.get("id"))) == job_id), None)
        if not job or job.get("status") != "SUCCESS":
            raise ClientError(f"Ads report is not ready: {job.get('status') if job else 'job not found'}")
        url = job.get("url", "")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise ClientError("Ads report returned an unsupported download URL") from exc
        if parsed.scheme != "https" or parsed.hostname != "ton.twimg.com" or port not in (None, 443) or parsed.username or parsed.password or not parsed.path.startswith("/advertiser-api-async-analytics/"):
            raise ClientError("Ads report returned an unsupported download URL")
        # Separate unauthenticated session: never send OAuth, bearer tokens or netrc credentials to CDN.
        with requests.Session() as session:
            session.trust_env = False
            try:
                response = session.get(url, timeout=60, allow_redirects=False)
                if response.status_code != 200:
                    raise ClientError(f"Ads report download failed ({response.status_code})")
                payload = response.content
                if payload.startswith(b"\x1f\x8b"):
                    payload = gzip.decompress(payload)
                return json.loads(payload)
            except (requests.RequestException, ValueError, OSError, EOFError) as exc:
                raise ClientError(f"Ads report download failed: {type(exc).__name__}") from exc
