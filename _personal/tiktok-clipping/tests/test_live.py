"""Live adapter boundaries; all media/auth consumers remain test doubles."""
import json
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

from tiktok_clipping_cli.engine import AdapterFailure
from tiktok_clipping_cli.live import CAMPAIGN_BASE, LiveAdapter
from tiktok_clipping_cli.media import MediaRenderer
from tiktok_clipping_cli.safety import SafetyError


CAMPAIGN_ID = "188c3e39-7850-4896-94df-e7a5be0cfec3"
DOCUMENT_ID = "1QwGNf5KW_ACPqlkLpVvraUXlM8-lJz170yz2YOuR-SE"
DOCUMENT_URL = "https://docs.google.com/document/d/" + DOCUMENT_ID + "/edit?usp=sharing"
VIDEO_URL = "https://youtu.be/8JMrfSFQdpo?si=source"


class Media:
    _source = MediaRenderer._source

    def __init__(self, config):
        self.config = config
        self.commands = []
        self.prepared = []

    def _run(self, command, deadline):
        self.commands.append(command)
        return json.dumps({"documentId": DOCUMENT_ID, "content": "Approved video: " + VIDEO_URL}).encode()

    def prepare(self, record):
        self.prepared.append(record)
        return {"duration_seconds": 60, "transcript": "Measured speech.",
            "transcript_segments": [{"start_seconds": 0, "end_seconds": 60, "text": "Measured speech."}],
            "provenance": "TEST timed media receipt"}

    def render(self, job, proposal):
        return {"test_render": job}

    def quality(self, job, proposal, asset):
        return {"test_quality": asset}


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def geturl(self):
        return CAMPAIGN_BASE + CAMPAIGN_ID

    def read(self, maximum):
        return self.payload[:maximum]


@pytest.fixture
def live(config):
    source = config["sources"][0]
    source.update(feed=VIDEO_URL, allowed_hosts=["youtu.be", "www.youtube.com"], reuse_evidence=DOCUMENT_URL)
    source["campaign"].update(id=CAMPAIGN_ID, expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    source['publication_policy']={'schema_version':1,'campaign_id':CAMPAIGN_ID,'brief_url':DOCUMENT_URL,'brief_content_sha256':hashlib.sha256(('Approved video: '+VIDEO_URL).encode()).hexdigest(),'source_url':VIDEO_URL,'source_sha256':'a'*64,'source_bytes':100,'video_reuse_allowed':True,'original_audio_reuse_allowed':True,'external_audio_allowed':False,'full_source_repost_allowed':False,'minimum_clip_seconds':7,'required_caption_tokens':['@test','#ad'],'required_on_screen_text':['Ad'],'clip_rules':[]}
    campaign = {"id": CAMPAIGN_ID, "status": "active", "platforms": ["tiktok"],
        "referenceMaterials": [{"url": DOCUMENT_URL}], "budgetCents": 8500000,
        "metrics": {"budgetSpentCents": 1960300}}
    media = Media(config)
    adapter = LiveAdapter(config, media=media, opener=lambda request, timeout: Response({"success": True, "data": campaign}))
    return adapter, source, campaign, media


def test_observed_campaign_sources_require_measured_transcript(live):
    adapter, source, _, media = live
    records = adapter.discover(source)
    assert records[0]["media_id"] == "8JMrfSFQdpo"
    assert records[0]["transcript"] == "Measured speech."
    assert records[0]["transcript_segments"] == [{"start_seconds": 0, "end_seconds": 60, "text": "Measured speech."}]
    assert media.prepared == [{"source_id": source["id"], "media_url": VIDEO_URL}]
    assert media.commands == [["google", "docs", "read", DOCUMENT_ID]]


def test_unlisted_video_is_rejected_before_media_download(live):
    adapter, source, _, media = live
    source["feed"] = "https://www.youtube.com/watch?v=TqAgejIX7uU"
    with pytest.raises(SafetyError, match="rights_policy_source_campaign_brief_mismatch"):
        adapter.discover(source)
    assert media.prepared == []


def test_unrelated_reuse_document_cannot_authorize_source(live):
    adapter, source, campaign, media = live
    campaign["referenceMaterials"] = []
    with pytest.raises(SafetyError, match="source_evidence_not_in_campaign"):
        adapter.discover(source)
    assert media.commands == []


@pytest.mark.parametrize("field,value", [("status", "paused"), ("platforms", ["youtube"])])
def test_inactive_or_unsupported_campaign_never_downloads(live, field, value):
    adapter, source, campaign, media = live
    campaign[field] = value
    with pytest.raises(SafetyError, match="campaign_not_active_funded_for_tiktok"):
        adapter.discover(source)
    assert media.prepared == []


def test_exhausted_campaign_does_not_download(live):
    adapter, source, campaign, media = live
    campaign["metrics"]["budgetSpentCents"] = campaign["budgetCents"]
    with pytest.raises(SafetyError, match="campaign_not_active_funded_for_tiktok"):
        adapter.discover(source)
    assert media.prepared == []


def test_wrong_campaign_response_fails_explicitly(live):
    adapter, _, campaign, _ = live
    campaign["id"] = "ecbd7fec-6f39-4081-aa18-1756f0ae73e9"
    with pytest.raises(SafetyError, match="campaign_response_contract_mismatch"):
        adapter.campaign(CAMPAIGN_ID)


def test_missing_budget_is_not_zero_default(live):
    adapter, _, campaign, _ = live
    del campaign["metrics"]["budgetSpentCents"]
    with pytest.raises(SafetyError):
        adapter.campaign(CAMPAIGN_ID)


def test_rate_limit_retains_category_without_invented_cooldown(live):
    adapter, _, _, _ = live
    def reject(request, timeout):
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)
    adapter.opener = reject
    with pytest.raises(AdapterFailure) as captured:
        adapter.campaign(CAMPAIGN_ID)
    assert captured.value.category == "rate_limit"
    assert captured.value.retry_after is None


@pytest.mark.parametrize("method,args", [
    ("verify_ready", ({},)), ("publish", ({}, {}, "key")),
    ("submit_rewards", ({}, {})), ("reward_status", ({}, {})), ("metrics", ({},)),
])
def test_missing_participant_capabilities_never_return_fabricated_receipts(live, method, args):
    adapter, _, _, media = live
    with pytest.raises(AdapterFailure, match="capability_missing:") as captured:
        getattr(adapter, method)(*args)
    assert captured.value.category == "permanent"
    assert media.prepared == []


def test_unverified_reconciliation_never_claims_absence(live):
    adapter, _, _, _ = live
    result = adapter.reconcile({}, "key")
    assert result["state"] == "unknown"
    assert "authoritative" not in result


def test_media_delegation_preserves_receipts(live):
    adapter, _, _, _ = live
    assert adapter.render({"id": "job"}, {}) == {"test_render": {"id": "job"}}
    assert adapter.quality({}, {}, {"path": "asset"}) == {"test_quality": {"path": "asset"}}


def test_doc_url_alone_cannot_authorize_download(live):
    adapter,source,_,media=live
    del source['publication_policy']
    with pytest.raises(SafetyError,match='explicit_scoped_publication_policy_required'):adapter.discover(source)
    assert media.prepared==[] and media.commands==[]


def test_fresh_changed_brief_cannot_reuse_saved_approval(live):
    adapter,source,_,media=live
    source['publication_policy']['brief_content_sha256']='f'*64
    with pytest.raises(SafetyError,match='source_brief_content_changed'):adapter.discover(source)
    assert media.prepared==[]


class ParticipantSDK:
    """No provider mutation: callable capability checks and read-only doubles."""
    def __init__(self, ready):
        self.ready = ready
        self.calls = []
        self.failure = None
        self.close_failure = False

    def submission_readiness(self, campaign, **binding):
        self.calls.append((campaign, binding))
        if self.failure:
            raise self.failure
        return self.ready

    def create_submission(self, *_args, **_kwargs):
        raise AssertionError('No submission is authorized by these tests')

    reconcile_submission = create_submission
    submission_revenue = create_submission

    def close(self):
        self.calls.append('close')
        if self.close_failure:
            raise TimeoutError('TEST cleanup')


@pytest.fixture
def participant(live):
    from tiktok_clipping_cli.engine import Engine
    from tiktok_clipping_cli.live import now_iso
    from tiktok_clipping_cli.safety import canonical
    import time
    adapter, source, campaign, media = live
    config = adapter.config
    source['publication_policy'] = {**source['publication_policy'], 'schema_version': 2,
        'required_on_screen_text': ['TEST attribution']}
    config['rewards_account'] = {'account_id': 'user_fixture', 'username': 'fixture',
        'profile': 'rewards', 'verified_at': now_iso(), 'provenance': 'TEST owning account'}
    engine = Engine(config, adapter=adapter, clock=time.time)
    engine.control('running')
    media.render_receipt = lambda *args: {'TEST': 'exact render checked'}
    ready = {'ready': True, 'actor': {key: config['rewards_account'][key] for key in ('account_id', 'username', 'profile')},
        'linked_account': {'account_id': config['account']['account_id'], 'username': 'ata_clipper', 'id': 'linked-fixture'},
        'campaign_id': CAMPAIGN_ID, 'requirements_digest': 'c' * 64, 'requirements': {'brief': 'TEST requirements'},
        'funding_remaining_cents': 10000, 'intake': {'TEST': True}, 'action': {'name': 'TEST', 'reference': 'TEST'}, 'observed_at': now_iso()}
    sdk = ParticipantSDK(ready)
    adapter.whop_factory = lambda: sdk
    job = {'id': 'fixture', 'input': {'source_id': source['id'], 'media_url': VIDEO_URL},
        'proposal': {'start_seconds': 10, 'end_seconds': 30, 'caption': '@test #ad', 'style': 'plain'}}
    return adapter, source, campaign, sdk, job, engine


def test_readiness_retains_full_campaign_brief_requirements_and_exact_policy(participant):
    from tiktok_clipping_cli.safety import strict_json, digest
    adapter, source, campaign, sdk, job, _ = participant
    ready = adapter.verify_ready(job)
    evidence = strict_json(ready['provenance'], adapter.config['limits']['max_payload_bytes'])
    assert evidence['source_evidence']['campaign'] == campaign
    assert evidence['source_evidence']['campaign_digest'] == digest(campaign)
    assert evidence['source_evidence']['brief']['content'] == 'Approved video: ' + VIDEO_URL
    assert evidence['source_evidence']['publication_policy'] == source['publication_policy']
    assert evidence['readiness']['requirements'] == sdk.ready['requirements']
    assert sdk.calls[-1] == 'close'


def test_historical_ad_asset_cannot_enter_fresh_public_readiness(participant):
    adapter, source, _, sdk, job, _ = participant
    source['publication_policy'] = {**source['publication_policy'], 'schema_version': 1,
        'required_on_screen_text': ['Ad', 'TEST attribution']}
    with pytest.raises(SafetyError, match='current_no_ad_render_policy_required'):
        adapter.verify_ready(job)
    assert sdk.calls == []


def test_missing_submission_method_blocks_readiness_before_public_prepare(participant):
    adapter, _, _, sdk, job, _ = participant
    sdk.create_submission = None
    with pytest.raises(AdapterFailure, match='whop_participant_submission_sdk'):
        adapter.verify_ready(job)
    assert sdk.calls == ['close']


@pytest.mark.parametrize('change', ['actor', 'linked', 'digest', 'funding', 'stale'])
def test_bad_fresh_participant_binding_cannot_pass(participant, change):
    adapter, _, _, sdk, job, _ = participant
    if change == 'actor': sdk.ready['actor']['account_id'] = 'foreign'
    elif change == 'linked': sdk.ready['linked_account']['account_id'] = 'foreign'
    elif change == 'digest': sdk.ready['requirements_digest'] = 'invalid'
    elif change == 'funding': sdk.ready['funding_remaining_cents'] = 0
    else: sdk.ready['observed_at'] = '2020-01-01T00:00:00+00:00'
    with pytest.raises(SafetyError): adapter.verify_ready(job)
    assert sdk.calls[-1] == 'close'


def test_read_failure_retains_long_provider_delay_even_when_cleanup_fails(participant):
    adapter, source, _, sdk, _, _ = participant
    class TypedError(Exception):
        category, code, status, retry_after_seconds = 'rate_limit', 'read_throttled', 429, 172800.25
    sdk.failure = TypedError('secret upstream message must not be copied')
    sdk.close_failure = True
    with pytest.raises(AdapterFailure) as caught: adapter._whop_ready(source)
    failure = caught.value
    assert (failure.category, failure.provider, failure.code, failure.status, failure.retry_after) == ('rate_limit', 'whop', 'read_throttled', 429, 172800.25)
    assert failure.cleanup_issue == 'whop_close_failed'
    assert 'secret' not in str(failure) and 'cleanup: whop_close_failed' in str(failure)


def test_live_readiness_obeys_persisted_provider_cooldown_before_sdk(participant):
    import time
    adapter, source, _, sdk, _, engine = participant
    with engine.transaction() as db:
        db.execute("INSERT INTO circuits VALUES('provider:whop',1,?)", (time.time() + 172800,))
    with pytest.raises(AdapterFailure, match='circuit_open: provider:whop'): adapter._whop_ready(source)
    assert sdk.calls == []


def test_post_boundary_refreshes_evidence_and_changed_brief_never_posts(participant):
    from tiktok_clipping_cli.safety import canonical, strict_json
    from tiktok_clipping_cli.engine import decoded_job
    import time
    adapter, source, campaign, sdk, _, engine = participant
    record = {'source_id': source['id'], 'media_id': 'fixture', 'media_url': VIDEO_URL,
        'duration_seconds': 60, 'transcript': 'TEST measured speech',
        'transcript_segments': [{'start_seconds': 0, 'end_seconds': 60, 'text': 'TEST measured speech'}],
        'observed_at': datetime.now(timezone.utc).isoformat(), 'provenance': 'TEST', 'categories': source['campaign']['categories']}
    engine.ingest(record)
    envelope = engine.prepare('clip')
    proposal = {'start_seconds': 10, 'end_seconds': 30, 'caption': '@test #ad', 'style': envelope['input']['assigned_style']}
    engine.apply({key: envelope[key] for key in ('job_id', 'lease_token', 'input_digest', 'policy_digest')} | {'proposal': proposal}, execute=False)
    with engine.transaction() as db:
        db.execute("UPDATE jobs SET status='running',stage='publish',lease_until=? WHERE id=?", (time.time() + 120, envelope['job_id']))
        job = decoded_job(engine._job(db, envelope['job_id']))
    job['readiness'] = adapter.verify_ready(job)
    with engine.transaction() as db: db.execute('UPDATE jobs SET readiness=? WHERE id=?', (canonical(job['readiness']), job['id']))
    class Bridge:
        def __init__(self): self.posts = 0
        def publish(self, job, asset, key, policy, *, pre_public_check):
            pre_public_check({'TEST': 'owning SDK binding'})
            self.posts += 1
            return {'TEST': 'public action double'}
    bridge = Bridge()
    adapter.studio_factory = lambda: bridge
    campaign['metrics']['budgetSpentCents'] += 1
    adapter.publish(job, {}, 'fixture-key')
    current = engine.get(job['id'])['readiness']
    snapshot = strict_json(current['provenance'], adapter.config['limits']['max_payload_bytes'])
    assert snapshot['before_public_action']['source_evidence']['campaign']['metrics'] == campaign['metrics']
    assert len([call for call in sdk.calls if call != 'close']) == 2
    assert bridge.posts == 1
    original_run = adapter.media._run
    adapter.media._run = lambda *_args: json.dumps({'documentId': DOCUMENT_ID, 'content': 'Changed current brief'}).encode()
    with pytest.raises(SafetyError, match='source_brief_content_changed'):
        adapter.publish(job, {}, 'fixture-key')
    assert bridge.posts == 1
    adapter.media._run = original_run
    with engine.transaction() as db: db.execute("UPDATE jobs SET lease_token='reclaimed' WHERE id=?", (job['id'],))
    with pytest.raises(SafetyError, match='readiness_worker_lease_changed'):
        adapter.publish(job, {}, 'fixture-key')
    assert bridge.posts == 1
    source['publication_policy']['brief_content_sha256'] = 'f' * 64
    with pytest.raises(SafetyError, match='persisted_publication_readiness_policy_changed'):
        adapter.publish(job, {}, 'fixture-key')
    assert bridge.posts == 1


def test_documented_transport_zero_preserves_transient_provider_category(participant):
    adapter, source, _, sdk, _, _ = participant
    class TransportError(Exception):
        category, code, status, retry_after_seconds = 'transient', 'upstream_read_failed_transport_TimeoutError', 0, 300
    sdk.failure = TransportError('TEST untrusted provider message')
    with pytest.raises(AdapterFailure) as caught: adapter._whop_ready(source)
    assert (caught.value.category, caught.value.provider, caught.value.status, caught.value.retry_after) == ('transient', 'whop', None, 300)
    assert sdk.calls[-1] == 'close'
