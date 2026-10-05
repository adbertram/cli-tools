"""Real catalog evidence fences the exact native public-action callback."""
from copy import deepcopy

import pytest

from test_catalog_runtime import prepared
from tiktok_clipping_cli.engine import decoded_job
from tiktok_clipping_cli.safety import SafetyError,canonical,digest
from tiktok_clipping_cli.studio_adapter import StudioPublicActionGuard,publication_request_id,studio_reservation_identity


def callback_fixture(prepared,clock):
    engine=prepared.engine;config=engine.config
    job_id=engine.ingest(prepared.record())['job_id']
    proposal={'start_seconds':0,'end_seconds':11,'caption':'TEST source-bound caption','style':'plain'}
    asset=engine.adapter.render(engine.get(job_id),proposal)
    key=digest({'account_id':config['account']['account_id'],'asset_digest':asset['sha256']})
    with engine.transaction() as db:
        db.execute("UPDATE jobs SET status='running',stage='publish',proposal=?,proposal_digest=?,asset=?,lease_token='TEST original lease',lease_until=? WHERE id=?",
            (canonical(proposal),digest(proposal),canonical(asset),clock()+120,job_id))
        db.execute("INSERT INTO publications VALUES(?,?,?,?,?,'uploading',NULL,1)",(key,job_id,config['account']['account_id'],asset['sha256'],key))
        job=decoded_job(engine._job(db,job_id))
    policy={'caption':proposal['caption'],'music_rights_confirmed':True}
    actor={'account_id':config['account']['account_id'],'username':'ata_clipper','profile':'clipper'}
    binding={'request_id':publication_request_id(key),'asset_sha256':asset['sha256'],'policy_digest':digest(policy),'actor':actor,'draft_id':'TEST owned draft','project_id':'0'}
    with engine.transaction() as db:db.execute('UPDATE publications SET data=? WHERE job_id=?',(canonical(studio_reservation_identity(binding)),job_id))
    pending={**binding,'draft':{'creation_id':'TEST owned draft','video_id':'TEST exact media'},'state':'dispatch_pending','public_action_dispatched':False,
        'policy':policy,'binding':digest({'asset_sha256':asset['sha256'],'policy':policy})}
    return StudioPublicActionGuard(config,job,asset,key,policy,deepcopy(pending),lambda _:deepcopy(pending),clock=clock),binding,job


def test_real_dynamic_admission_bounds_original_dispatch_deadline(prepared,clock):
    guard,binding,job=callback_fixture(prepared,clock)
    original=prepared.engine._resolve_job_source(job['input'])
    assert guard.config['sources']==[]  # No global configured-source append.
    assert guard(binding)=={'dispatch_deadline':clock()+60}
    assert original['valid_until']==clock()+60<job['lease_until']


@pytest.mark.parametrize('change',['revoked_compiler','changed_version','stale_dependencies','expired_admission','changed_provider','changed_window'])
def test_real_changed_catalog_evidence_never_dispatches(prepared,clock,monkeypatch,change):
    guard,binding,job=callback_fixture(prepared,clock)
    if change=='revoked_compiler':
        from tiktok_clipping_cli import source_catalog
        monkeypatch.delitem(source_catalog.COMPILERS,'supplied-av-episode-commission-v1')
    elif change in {'changed_version','stale_dependencies','changed_provider'}:
        with prepared.catalog._db() as db:
            if change=='changed_version':db.execute("UPDATE catalog_sources SET current_version=?",('f'*64,))
            elif change=='stale_dependencies':db.execute('UPDATE catalog_work SET due=?',(clock(),))
            else:db.execute("UPDATE catalog_settings SET value=? WHERE key='binding'",(canonical({'whop_account_id':'TEST changed provider'}),))
    elif change=='expired_admission':clock.now+=61
    else:
        # Even a consistently hashed DB input cannot alter the admitted window.
        modified={**job['input'],'transcript':'TEST changed window words'}
        with prepared.engine.transaction() as db:db.execute('UPDATE jobs SET input=?,input_digest=? WHERE id=?',(canonical(modified),digest(modified),job['id']))
        guard.job={**job,'input':modified,'input_digest':digest(modified)}
    sends=[]
    with pytest.raises(SafetyError):
        guard(binding);sends.append('Post')
    assert sends==[]
    with prepared.engine.transaction() as db:assert db.execute('SELECT state FROM publications WHERE job_id=?',(job['id'],)).fetchone()[0]=='uploading'


def test_fresh_catalog_refresh_never_renews_original_operating_deadline(prepared,clock):
    guard,binding,job=callback_fixture(prepared,clock)
    clock.now+=54
    with prepared.catalog._db() as db:db.execute('UPDATE catalog_work SET due=?',(clock()+10000,))
    assert guard(binding)=={'dispatch_deadline':clock()+6}


def test_catalog_with_five_seconds_remaining_refuses_before_reservation(prepared,clock):
    guard,binding,job=callback_fixture(prepared,clock)
    clock.now+=55
    with pytest.raises(SafetyError,match='dispatch_headroom_exhausted'):guard(binding)
    with prepared.engine.transaction() as db:assert db.execute('SELECT state FROM publications WHERE job_id=?',(job['id'],)).fetchone()[0]=='uploading'
