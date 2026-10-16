"""Public ReachCat Firebase reads with an explicit campaign-field allowlist."""
import json
import math
import re
import time

import requests
from cli_tools_shared.exceptions import ClientError

BASE_URL = 'https://reachcat-api-default-rtdb.europe-west1.firebasedatabase.app'
PAGE_SIZE = 100
PUBLIC_FIELDS = frozenset({
    'id', 'shortId', 'name', 'description', 'captionDetail', 'status', 'networks', 'category',
    'cpm', 'cpmLinkCapMax', 'cpmTotalCapMax', 'cpmUserCapMax', 'minViewsForPayout',
    'amountCredited', 'amountConsumed', 'amountRemaining', 'flatFeeBonus', 'shadowBan',
})
PUBLIC_SETTINGS = frozenset({
    'requirements', 'link', 'linkMaterials', 'type', 'start', 'created', 'networkMinFollowers',
    'hasAllowedCountries', 'allowedCountries', 'hasAllowedLanguages', 'allowedLanguages',
    'hasAllowedUsers', 'maxLinksPerUser', 'cpm', 'cpmLinkCapMax', 'cpmTotalCapMax',
    'cpmUserCapMax', 'flatFeeBonus', 'requiresClientApproval', 'isFarmReserved', 'isVip',
})


def public_campaign(value: dict) -> dict:
    """Preserve native public field names; exclude management/payment/user records."""
    if not isinstance(value, dict) or not isinstance(value.get('id'), str):
        raise ClientError('ReachCat campaign schema changed')
    row = {key: item for key, item in value.items() if key in PUBLIC_FIELDS}
    if 'settings' in value:
        settings = value['settings']
        if not isinstance(settings, dict):
            raise ClientError('ReachCat campaign settings schema changed')
        row['settings'] = {key: item for key, item in settings.items() if key in PUBLIC_SETTINGS}
    return row


class ReachCatClient:
    def __init__(self, session=None, max_retries: int = 2, base_delay: float = 1, max_delay: float = 10):
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def close(self):
        self.session.close()

    def _read(self, path: str, params=None):
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                response = self.session.get(BASE_URL + path, params=params, timeout=30)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == self.max_retries:
                    raise ClientError('ReachCat public read unavailable') from None
            else:
                if response.status_code not in {429, 500, 502, 503, 504}:
                    break
                if attempt == self.max_retries:
                    raise ClientError(f'ReachCat public read failed (HTTP {response.status_code})')
            delay = min(self.max_delay, self.base_delay * 2 ** attempt)
            if response is not None and response.headers.get('Retry-After'):
                try:
                    seconds = float(response.headers['Retry-After'])
                except ValueError:
                    raise ClientError('ReachCat Retry-After is not a supported seconds value') from None
                if not math.isfinite(seconds) or not 0 <= seconds <= self.max_delay:
                    raise ClientError('ReachCat Retry-After exceeds retry bound')
                delay = max(delay, seconds)
            time.sleep(delay)
        if response is None or not response.ok:
            raise ClientError('ReachCat public read failed')
        try:
            return response.json()
        except ValueError:
            raise ClientError('ReachCat returned invalid JSON') from None

    def campaigns(self, limit: int = 100, status: str = 'ACTIVE', platform: str | None = None) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ClientError('limit must be between 1 and 1000')
        rows, cursor = [], None
        for _ in range(100):
            params = {'orderBy': json.dumps('$key'), 'limitToFirst': PAGE_SIZE + (1 if cursor else 0)}
            if cursor is not None:
                params['startAt'] = json.dumps(cursor)
            value = self._read('/static/campaigns.json', params)
            if value is None:
                return rows
            if not isinstance(value, dict):
                raise ClientError('ReachCat campaign collection schema changed')
            keys = sorted(value)
            next_keys = [key for key in keys if cursor is None or key > cursor]
            if keys and not next_keys:
                if len(keys) == 1 and keys[0] == cursor:
                    return rows
                raise ClientError('ReachCat pagination did not advance')
            for key in next_keys:
                raw = value[key]
                if not isinstance(raw, dict):
                    raise ClientError('ReachCat campaign record schema changed')
                if status and raw.get('status') != status:
                    continue
                if platform and (raw.get('networks') or {}).get(platform) is not True:
                    continue
                row = public_campaign(raw)
                if row['id'] != key:
                    raise ClientError('ReachCat campaign identity mismatch')
                rows.append(row)
                if len(rows) >= limit:
                    return rows
            if len(keys) < params['limitToFirst']:
                return rows
            cursor = next_keys[-1]
        raise ClientError('ReachCat campaign scan exceeded pagination bound')

    def campaign(self, campaign_id: str) -> dict:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', campaign_id):
            raise ClientError('Invalid ReachCat campaign ID')
        value = self._read('/static/campaigns/' + campaign_id + '.json')
        if value is None:
            raise ClientError('ReachCat campaign not found')
        row = public_campaign(value)
        if row['id'] != campaign_id:
            raise ClientError('ReachCat campaign identity mismatch')
        return row
