import hashlib
import json
from pathlib import Path

import pytest

from conftest import iso
from tiktok_clipping_cli.native_runtime import settle_native
from tiktok_clipping_cli.safety import canonical


def timing_files(engine,clock,kind='clip',elapsed=2.4):
    envelope={'job_id':'a'*32,'attempt_id':'b'*32,'nonce':'TEST nonce','native_execution':{'execution_id':'123','workflow_id':'TEST workflow'}}
    with engine.transaction() as db:
        reservation=engine._reserve_model_attempt(db,envelope['attempt_id'],kind,120)
    root=Path(engine.config['workspace'])/('visual' if kind=='visual' else 'model')/envelope['job_id']/envelope['attempt_id'];root.mkdir(parents=True)
    marker={'schema_version':1,**{k:envelope[k]for k in ('job_id','attempt_id','nonce')},'pid':123,'start_identity':'TEST observed identity'}
    receipt={'envelope':envelope,'outcome':'failed','usage_observed':False}
    raw=(json.dumps(receipt)+'\n').encode()
    proof={'schema_version':1,'envelope':envelope,'process':{k:marker[k]for k in ('pid','start_identity')},'started_at':iso(clock()),'completed_at':iso(clock()+elapsed),'elapsed_seconds':elapsed,'monotonic_started_ms':1000,'monotonic_completed_ms':1000+elapsed*1000,'receipt_sha256':hashlib.sha256(raw).hexdigest(),'provenance':'native_process_monotonic'}
    (root/'process-start.json').write_text(canonical(marker));(root/('native-receipt.json' if kind=='visual' else 'result.json')).write_bytes(raw);(root/'runtime.json').write_text(canonical(proof))
    clock.now+=elapsed
    return envelope,reservation,receipt,proof,root


@pytest.mark.parametrize('kind',['clip','learn','visual'])
def test_exact_native_timing_settles_once_and_retains_bound_proof(engine,clock,kind):
    envelope,reservation,receipt,proof,root=timing_files(engine,clock,kind)
    clock.now+=86400
    with engine.transaction() as db:
        engine._budget(db,'runtime_seconds',10)
        assert settle_native(engine,db,envelope,kind,reservation['reservation_id'],receipt)
        row=db.execute('SELECT * FROM runtime_reservations').fetchone()
        assert row['settled_seconds']==3 and json.loads(row['native_proof'])==proof
        assert row['native_proof_digest']==hashlib.sha256((root/'runtime.json').read_bytes()).hexdigest()
        assert not settle_native(engine,db,envelope,kind,reservation['reservation_id'],receipt)
        budgets={r['day']:r['runtime_seconds']for r in db.execute('SELECT * FROM budgets')}
        assert budgets[reservation['day']]==3 and budgets[engine._day()]==10


@pytest.mark.parametrize('change',['execution','nonce','process','manifest','receipt','negative','overrun','future','monotonic','missing','partial'])
def test_unproven_native_timing_holds_ceiling_without_erasing_terminal_receipt(engine,clock,change):
    envelope,reservation,receipt,proof,root=timing_files(engine,clock)
    if change=='execution':proof['envelope']['native_execution']['execution_id']='456';envelope={**envelope,'native_execution':{'execution_id':'123','workflow_id':'TEST workflow'}}
    elif change=='nonce':proof['envelope']['nonce']='changed';envelope={**envelope,'nonce':'TEST nonce'}
    elif change=='process':proof['process']['start_identity']='changed'
    elif change=='manifest':proof['envelope']['manifest_sha256']='f'*64
    elif change=='receipt':proof['receipt_sha256']='f'*64
    elif change=='negative':proof['elapsed_seconds']=-1
    elif change=='overrun':proof['elapsed_seconds']=121
    elif change=='future':proof['completed_at']=iso(clock()+100)
    elif change=='monotonic':proof['monotonic_completed_ms']+=10
    if change=='missing':(root/'runtime.json').unlink()
    elif change=='partial':(root/'runtime.json').write_text('{')
    else:(root/'runtime.json').write_text(canonical(proof))
    with engine.transaction() as db:
        assert not settle_native(engine,db,envelope,'clip',reservation['reservation_id'],receipt)
        assert db.execute('SELECT runtime_seconds FROM budgets').fetchone()[0]==120
        assert db.execute('SELECT settled_seconds FROM runtime_reservations').fetchone()[0] is None
        assert (root/'result.json').is_file()


def test_empty_interrupted_timing_temp_is_exact_owned_retention_sink(engine,clock):
    from tiktok_clipping_cli.text_attempts import TextAttempts
    from tiktok_clipping_cli.visual import VisualArtifacts
    envelope,_,_,_,root=timing_files(engine,clock)
    (root/'.runtime.pending.json').write_bytes(b'')
    records=TextAttempts(engine).inventory(root)
    assert next(r for r in records if r['path']=='.runtime.pending.json')['bytes']==0
    engine.config['visual']={'frame_count':1}
    visual_root=Path(engine.config['workspace'])/'visual'/envelope['job_id']/envelope['attempt_id'];visual_root.mkdir(parents=True)
    (visual_root/'.runtime.pending.json').write_bytes(b'')
    artifacts=VisualArtifacts(engine.config)
    inventory=artifacts.inventory(envelope)
    assert inventory[0]['bytes']==0
    assert artifacts.prune(envelope,inventory)==0
    assert not visual_root.exists()
