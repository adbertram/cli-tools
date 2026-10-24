"""Read analytics without discarding API metrics, includes or partial errors."""
import json
from typing import Annotated, Optional

import typer
from cli_tools_shared.output import command, print_error, print_json, print_table

from ..analytics import (AnalyticsClient, METRIC_GROUPS, ADS_ENTITIES, ADS_ACTIVE_ENTITIES, ADS_METRICS, ADS_PLACEMENTS, ADS_SEGMENTS)
from ..config import API_AUTH_TYPE, get_config

app = typer.Typer(help="Post, media, audience, API usage and Ads reports. JSON preserves API envelopes and pagination tokens.", no_args_is_help=True)
Profile = Annotated[Optional[str], typer.Option("--profile", help="Saved X auth profile")]
Table = Annotated[bool, typer.Option("--table", "-t", help="Display report fields as a table")]
Metrics = Annotated[str, typer.Option("--metrics", help="Comma-separated " + ",".join(METRIC_GROUPS))]
Start = Annotated[str, typer.Option("--start-time", help="Inclusive ISO 8601 timestamp with timezone")]
End = Annotated[str, typer.Option("--end-time", help="Exclusive ISO 8601 timestamp with timezone")]
OptionalStart = Annotated[Optional[str], typer.Option("--start-time", help="Inclusive ISO 8601 timestamp with timezone")]
OptionalEnd = Annotated[Optional[str], typer.Option("--end-time", help="Exclusive ISO 8601 timestamp with timezone")]
Auth = Annotated[str, typer.Option("--auth-mode", help="oauth1 (user) or bearer (app-only; public metrics only)")]
Granularity = Annotated[str, typer.Option("--granularity", help="Aggregation interval; see command help")]
Fields = Annotated[Optional[str], typer.Option("--fields", help="Comma-separated API analytics fields; default requests all supported fields")]
Entity = Annotated[str, typer.Option("--entity", help=",".join(ADS_ENTITIES))]
AdsMetrics = Annotated[str, typer.Option("--metric-groups", help=",".join(ADS_METRICS))]
Placement = Annotated[str, typer.Option("--placement", help=",".join(ADS_PLACEMENTS))]


def client(profile, auth_mode="oauth1"):
    return AnalyticsClient(config=get_config(profile=profile, profile_auth_type=API_AUTH_TYPE), auth_mode=auth_mode)


def emit(report, table):
    if table:
        rows = [{"field": key, "value": json.dumps(value, ensure_ascii=False)} for key, value in report.items()]
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(report)
    if report.get("errors"):
        print_error("X returned partial or failed analytics. Full data and errors are preserved in output.")
        raise typer.Exit(1)


@app.command()
@command
def posts(ids: Annotated[str, typer.Argument(help="Comma-separated post IDs (1-100)")], metrics: Metrics = "public_metrics", auth_mode: Auth = "oauth1", profile: Profile = None, table: Table = False):
    """Read post metrics plus attached media and author metrics. Private metrics: owned posts within 30 days."""
    emit(client(profile, auth_mode).posts(ids, metrics), table)


@app.command()
@command
def media(media_keys: Annotated[str, typer.Argument(help="Comma-separated media keys (1-100)")], metrics: Metrics = "public_metrics", auth_mode: Auth = "oauth1", profile: Profile = None, table: Table = False):
    """Read media metric groups by key, preserving video view and playback fields."""
    emit(client(profile, auth_mode).media(media_keys, metrics), table)


@app.command()
@command
def user(user_id: Annotated[Optional[str], typer.Option("--user-id", help="User ID; omit both selectors for current user")] = None, username: Annotated[Optional[str], typer.Option("--username", help="X username")] = None, auth_mode: Auth = "oauth1", profile: Profile = None, table: Table = False):
    """Read follower, following, post, list and other returned public user metrics."""
    emit(client(profile, auth_mode).user(user_id, username), table)


@app.command()
@command
def timeline(user_id: Annotated[Optional[str], typer.Option("--user-id", help="User ID; default is authenticated user")] = None, metrics: Metrics = "public_metrics", limit: Annotated[int, typer.Option("--limit", "-l", min=5, max=100, help="Posts per API page")] = 100, start_time: OptionalStart = None, end_time: OptionalEnd = None, pagination_token: Annotated[Optional[str], typer.Option("--pagination-token", help="meta.next_token from previous report")] = None, exclude: Annotated[Optional[str], typer.Option("--exclude", help="replies,retweets or both")] = None, auth_mode: Auth = "oauth1", profile: Profile = None, table: Table = False):
    """Read one page of timeline metrics. Continue with meta.next_token; no hidden extra requests."""
    emit(client(profile, auth_mode).timeline(user_id, metrics, limit, start_time, end_time, pagination_token, exclude), table)


@app.command("post-series")
@command
def post_series(ids: Annotated[str, typer.Argument(help="Comma-separated post IDs (1-100)")], start_time: Start, end_time: End, granularity: Granularity = "total", fields: Fields = None, profile: Profile = None, table: Table = False):
    """Read Enterprise post analytics: hourly/daily/weekly/total. Requires user auth and endpoint access."""
    emit(client(profile).series("posts", ids, start_time, end_time, granularity, fields), table)


@app.command("media-series")
@command
def media_series(media_keys: Annotated[str, typer.Argument(help="Comma-separated media keys (1-100)")], start_time: Start, end_time: End, granularity: Granularity = "daily", fields: Fields = None, profile: Profile = None, table: Table = False):
    """Read Enterprise video analytics: hourly/daily/total, watch time, playback and CTA clicks."""
    emit(client(profile).series("media", media_keys, start_time, end_time, granularity, fields), table)


@app.command()
@command
def counts(query: Annotated[str, typer.Argument(help="X search query")], archive: Annotated[bool, typer.Option("--archive", help="Use full archive instead of recent seven days; requires endpoint access")] = False, start_time: OptionalStart = None, end_time: OptionalEnd = None, granularity: Granularity = "hour", next_token: Annotated[Optional[str], typer.Option("--next-token", help="meta.next_token from previous report")] = None, since_id: Annotated[Optional[str], typer.Option("--since-id")] = None, until_id: Annotated[Optional[str], typer.Option("--until-id")] = None, profile: Profile = None, table: Table = False):
    """Count matching posts per minute/hour/day. App bearer token required; returns one page."""
    emit(client(profile, "bearer").counts(query, archive, start_time, end_time, granularity, next_token, since_id, until_id), table)


@app.command()
@command
def usage(days: Annotated[int, typer.Option("--days", min=1, max=90, help="Usage history days")] = 7, profile: Profile = None, table: Table = False):
    """Read app/project post consumption and daily usage with app bearer token."""
    emit(client(profile, "bearer").usage(days), table)


@app.command()
@command
def credits(profile: Profile = None, table: Table = False):
    """Read API credit usage with app bearer token. Does not buy credits."""
    emit(client(profile, "bearer").usage(credits=True), table)


@app.command("ads-stats")
@command
def ads_stats(account_id: Annotated[str, typer.Argument(help="Ads account ID")], entity_ids: Annotated[str, typer.Argument(help="Comma-separated entity IDs (1-20)")], entity: Entity, start_time: Start, end_time: End, granularity: Granularity = "TOTAL", metric_groups: AdsMetrics = "ENGAGEMENT", placement: Placement = "ALL_ON_TWITTER", profile: Profile = None, table: Table = False):
    """Read synchronous Ads performance, up to seven days. DAY boundaries must be account-local midnight."""
    emit(client(profile).ads_report(account_id, entity, entity_ids, start_time, end_time, granularity, metric_groups, placement), table)


@app.command("ads-job-create")
@command
def ads_job_create(account_id: Annotated[str, typer.Argument(help="Ads account ID")], entity_ids: Annotated[str, typer.Argument(help="Comma-separated entity IDs (1-20)")], entity: Entity, start_time: Start, end_time: End, granularity: Granularity = "TOTAL", metric_groups: AdsMetrics = "ENGAGEMENT", placement: Placement = "ALL_ON_TWITTER", segmentation: Annotated[Optional[str], typer.Option("--segmentation", help=",".join(ADS_SEGMENTS))] = None, country: Annotated[Optional[str], typer.Option("--country", help="Ads country targeting ID for geographic segmentation")] = None, profile: Profile = None, table: Table = False):
    """Create analytics report job (no ad purchase). Maximum 90 days, or 45 segmented. Check via ads-jobs."""
    emit(client(profile).ads_report(account_id, entity, entity_ids, start_time, end_time, granularity, metric_groups, placement, asynchronous=True, segmentation=segmentation, country=country), table)


@app.command("ads-jobs")
@command
def ads_jobs(account_id: Annotated[str, typer.Argument(help="Ads account ID")], job_ids: Annotated[str, typer.Argument(help="Comma-separated report job IDs (1-200)")], profile: Profile = None, table: Table = False):
    """Check analytics report jobs; SUCCESS contains download URL and expiration."""
    emit(client(profile).ads_jobs(account_id, job_ids), table)


@app.command("ads-download")
@command
def ads_download(account_id: Annotated[str, typer.Argument(help="Ads account ID")], job_id: Annotated[str, typer.Argument(help="Completed report job ID")], profile: Profile = None, table: Table = False):
    """Check job, download completed gzip report securely, emit decompressed JSON."""
    emit(client(profile).ads_download(account_id, job_id), table)


@app.command("ads-active")
@command
def ads_active(account_id: Annotated[str, typer.Argument(help="Ads account ID")], entity: Annotated[str, typer.Option("--entity", help=",".join(ADS_ACTIVE_ENTITIES))], start_time: Start, end_time: End, campaign_ids: Annotated[Optional[str], typer.Option("--campaign-ids")] = None, funding_instrument_ids: Annotated[Optional[str], typer.Option("--funding-instrument-ids")] = None, line_item_ids: Annotated[Optional[str], typer.Option("--line-item-ids")] = None, profile: Profile = None, table: Table = False):
    """Find entities with changed metrics (up to 90 days) and reporting windows for each placement."""
    emit(client(profile).ads_active(account_id, entity, start_time, end_time, campaign_ids, funding_instrument_ids, line_item_ids), table)


@app.command("ads-reach")
@command
def ads_reach(account_id: Annotated[str, typer.Argument(help="Ads account ID")], entity_ids: Annotated[str, typer.Argument(help="Comma-separated campaign or funding instrument IDs (1-20)")], start_time: Start, end_time: End, funding_instruments: Annotated[bool, typer.Option("--funding-instruments", help="Query funding instruments instead of campaigns")] = False, profile: Profile = None, table: Table = False):
    """Read unique audience reach and average frequency for campaigns or funding instruments."""
    emit(client(profile).ads_reach(account_id, entity_ids, start_time, end_time, funding_instruments), table)


@app.command("ads-accounts")
@command
def ads_accounts(limit: Annotated[int, typer.Option("--limit", "-l", min=1, max=1000, help="Accounts per page")] = 200, cursor: Annotated[Optional[str], typer.Option("--cursor", help="next_cursor from previous report")] = None, query: Annotated[Optional[str], typer.Option("--query", help="Case-insensitive account name prefix")] = None, account_ids: Annotated[Optional[str], typer.Option("--account-ids", help="Comma-separated account IDs")] = None, with_deleted: Annotated[bool, typer.Option("--with-deleted", help="Include deleted accounts")] = False, profile: Profile = None, table: Table = False):
    """Discover accessible Ads account IDs and timezones; one page with next_cursor."""
    emit(client(profile).ads_accounts(limit, cursor, query, account_ids, with_deleted), table)


# Both OAuth1 keys and X_BEARER_TOKEN belong to X's existing custom API profile.
# The registry resolves the custom profile. AnalyticsClient then validates the
# exact fields for the selected mode; app bearer reads never require OAuth1 keys.
COMMAND_CREDENTIALS = {
    (info.name or info.callback.__name__.replace("_", "-")): [API_AUTH_TYPE]
    for info in app.registered_commands
}
