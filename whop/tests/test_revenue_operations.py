import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from cli_tools_shared.exceptions import ClientError
from whop_cli.client import WhopClient,WhopError
from whop_cli import submission_operations as op,revenue_operations as rev

REQUEST='9b3f4dc5-1072-4d2a-9738-3a1a6a275dce'
ACTOR='user_TEST';CAMPAIGN='campaign_TEST';SUBMISSION='submission_TEST';POST='1234567890123456789'

@pytest.fixture
def client(tmp_path):
    c=WhopClient(SimpleNamespace(get_browser=lambda:Mock(),get_profile_data_dir=lambda:tmp_path,get_active_profile_name=lambda:'rewards'))
    c._location=Mock(return_value=('https://example.apps.whop.com','/c/exp_TEST'))
    c.account=Mock(return_value={'id':ACTOR,'username':'me','profile':'rewards'})
    c.linked_accounts=Mock(return_value=[{'userId':'creator_TEST'}])
    c._rest=Mock(return_value={'success':True,'data':[],'pagination':{'nextCursor':None}})
    c._action=Mock(return_value={'success':True,'data':[{'id':SUBMISSION,'campaignId':CAMPAIGN,'status':'approved','approvedAt':'2026-10-01T00:00:00Z','socialMediaPost':{'platform':'tiktok','postId':POST}}],'nextCursor':None})
    bound={'account_id':ACTOR,'profile':'rewards','experience':'https://example.apps.whop.com/c/exp_TEST','campaign_id':CAMPAIGN,'publication':{'publication_id':POST}}
    row={'version':1,'request_id':REQUEST,'binding':bound,'state':'created_unverified','public_action_dispatched':True,'submission_id':SUBMISSION}
    with op.journal_lock(c.config) as db: op.save(db,row)
    return c

def payout(id='payout_TEST',**kwargs):
    return {'id':id,'submissionId':SUBMISSION,'campaignId':CAMPAIGN,'status':'completed','netAmount':'90','amount':'100','creatorFeeAmount':'10','currency':'USD',**kwargs}

def reply(rows,cursor=None): return {'success':True,'data':rows,'pagination':{'nextCursor':cursor}}
def get(c): return c.submission_revenue(SUBMISSION,CAMPAIGN)

def test_empty_complete_is_unknown_not_zero(client):
    result=get(client)
    assert result['readback_fresh'] is True
    assert result['status']=='approved'
    assert result['pending_cents'] is None and result['received_cents'] is None and result['total_earned_cents'] is None
    assert result['currency'] is None and result['earning_window_started_at'] is None and result['exposure_seconds'] is None
    assert 'no_individual_allocations_observed' in result['unknown_reasons']
    client._rest.assert_called_once_with('/api/submission/payouts',{'userIds':'creator_TEST','limit':100})

def test_actual_fields_separate_net_gross_fees_and_pending(client):
    client._rest.return_value=reply([payout(),payout('payout_PENDING',status='pending',netAmount=None,amount='80',accruedNetAmount='70',accruedAmount='75'),payout('payout_REVERSED',status='reversed',netAmount='120',reversedAt='2026-10-03T00:00:00Z',reversedReason='actual reversal')])
    result=get(client)
    assert result['pending_cents']=='70' and result['received_cents']=='90' and result['total_earned_cents']=='160'
    assert result['currency']=='USD' and result['amounts_verified'] is True
    assert result['allocations'][0]['amount']=='100' and result['allocations'][0]['creatorFeeAmount']=='10'
    assert result['allocations'][2]['reversedAt'] is not None
    assert result['provenance']['moderation_readback_fresh'] is True

@pytest.mark.parametrize('changed,reason',[({'currency':None},'currency_unknown'),({'netAmount':None},'completed_net_amount_unknown'),({'status':'suspended'},'payout_status_unverified'),({'submissionMigratedCompletedAmount':'5'},'migrated_allocation_unverified'),({'status':'pending','unmetSettleGate':'not_approved'},'pending_settlement_gate'),({'status':'pending','frozenSince':'2026-01-01'},'pending_settlement_gate')])
def test_unknown_money_never_ui_default(client,changed,reason):
    client._rest.return_value=reply([payout(**changed)])
    result=get(client)
    assert result['total_earned_cents'] is None and reason in result['unknown_reasons']

@pytest.mark.parametrize('field,value',[('netAmount',True),('amount',1.1),('netAmount','1e3'),('currency','usd'),('currency','invented'),('id',None),('submissionId','bad/id')])
def test_malformed_allocation_fails_without_promotion(client,field,value):
    client._rest.return_value=reply([payout(**{field:value})])
    with pytest.raises(WhopError):get(client)
    with op.journal_lock(client.config) as db:
        assert db.execute('SELECT count(*) FROM payout_current').fetchone()[0]==0

def test_mixed_currency_not_aggregated(client):
    client._rest.return_value=reply([payout(),payout('second',currency='EUR')])
    result=get(client)
    assert result['currency'] is None and result['total_earned_cents'] is None

def test_foreign_campaign_or_submission_never_allocated(client):
    client._rest.return_value=reply([payout(campaignId='other_campaign'),payout('other_payout',submissionId='other_submission')])
    assert get(client)['allocation_count']==0

def test_disappearance_is_unknown_not_inferred_reversal(client):
    client._rest.return_value=reply([payout()]);assert get(client)['received_cents']=='90'
    client._rest.return_value=reply([]);result=get(client)
    assert result['received_cents'] is None
    assert result['disappeared_allocations'][0]['id']=='payout_TEST'
    assert 'allocation_disappeared_not_reversed' in result['unknown_reasons']
    client._rest.return_value=reply([payout(status='reversed',reversedAt='2026-10-04')]);result=get(client)
    assert result['disappeared_allocations']==[] and result['received_cents']=='0'
    assert result['allocations'][0]['status']=='reversed'

def test_same_allocation_cannot_change_binding(client):
    client._rest.return_value=reply([payout()]);get(client)
    client._rest.return_value=reply([payout(campaignId='other_campaign')])
    with pytest.raises(WhopError,match='binding_changed'):get(client)

def test_over_1000_shared_pages_resume_and_promote(client):
    def fetch(path,args):
        assert path=='/api/submission/payouts'
        index=int(args.get('cursor','0'))
        return reply([payout('payout_'+str(index*100+i)) for i in range(100)],str(index+1) if index<12 else None)
    client._rest.side_effect=fetch
    first=get(client)
    assert not first['sync']['complete'] and first['total_earned_cents'] is None
    assert client._rest.call_count==11
    # Restarted client uses the same provider-wide pass, not a per-post scan.
    other=WhopClient(client.config);other.__dict__.update(client.__dict__)
    result=get(other)
    assert result['sync']['complete'] and result['allocation_count']==1300 and result['received_cents']=='117000'
    assert len(result['allocations'])==50 and result['allocations_truncated'] is True
    assert client._rest.call_count==14
    assert result['sync']['snapshot_kind']=='paginated_observation_interval'
    assert result['allocation_observation_started_at']<=result['allocation_observation_ended_at']

def test_incomplete_generation_does_not_mix_into_old_totals(client):
    client._rest.return_value=reply([payout()]);get(client)
    client._rest.side_effect=lambda path,args:reply([payout('new_'+args.get('cursor','0'),netAmount='500')],str(int(args.get('cursor','0'))+1))
    result=get(client)
    assert result['received_cents'] is None and 'new_data_pending' in result['unknown_reasons']
    with op.journal_lock(client.config) as db:
        assert db.execute('SELECT count(*) FROM payout_current').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM payout_pending').fetchone()[0]==11

@pytest.mark.parametrize('failure',[WhopError('limited',category='rate_limit',status=429,retry_after_seconds=172800),WhopError('transient',category='transient',status=503,retry_after_seconds=100)])
def test_typed_nonhead_failure_preserves_cursor_and_provider_cooldown(client,failure,monkeypatch):
    clock=[1000.0];monkeypatch.setattr(rev.time,'time',lambda:clock[0])
    client._rest.side_effect=[reply([payout()], 'next'),failure]
    result=get(client)
    assert not result['sync']['complete'] and result['sync']['failure']['retry_after_seconds']==failure.retry_after_seconds
    client.account.reset_mock();client._rest.reset_mock()
    with pytest.raises(WhopError,match='cooldown'):get(client)
    client.account.assert_not_called();client._rest.assert_not_called()
    clock[0]+=failure.retry_after_seconds+1
    client._rest.side_effect=[reply([payout()], 'next'),reply([payout('next_payout')])]
    result=get(client)
    assert result['sync']['complete'] and result['allocation_count']==2
    assert client._rest.call_args_list[-1].args[1]['cursor']=='next'

def test_interrupted_read_retry_does_not_poison_cursor(client):
    client._rest.side_effect=[reply([payout()], 'next'),KeyboardInterrupt()]
    with pytest.raises(KeyboardInterrupt):get(client)
    client._rest.side_effect=[reply([payout()], 'next'),reply([payout('second')])]
    assert get(client)['sync']['complete']

def test_cycle_requires_explicit_safe_restart(client):
    client._rest.side_effect=lambda path,args:reply([payout()], 'repeat')
    with pytest.raises(WhopError,match='cycle'):get(client)
    client._rest.side_effect=None;client._rest.return_value=reply([payout()])
    assert client.sync_submission_revenue(restart_pass=True)['complete']

@pytest.mark.parametrize('submission,campaign',[(SUBMISSION,'other'),('unknown',CAMPAIGN)])
def test_only_owned_exact_submission(client,submission,campaign):
    with pytest.raises(WhopError,match='owned_submission'):client.submission_revenue(submission,campaign)
    client._rest.assert_not_called()

def test_wrong_actor_stops_before_payouts(client):
    client.account.return_value['id']='user_OTHER'
    with pytest.raises(WhopError,match='actor_changed'):get(client)
    client._rest.assert_not_called()

def test_historical_submission_proof_retained_but_money_not_fresh(client):
    client._rest.return_value=reply([payout()]);get(client)
    client._action.return_value={'data':[],'nextCursor':None,'success':True}
    result=get(client)
    assert result['status'] is None and result['readback_fresh'] is False and result['received_cents'] is None
    with op.journal_lock(client.config) as db:
        historical=op.load(db,REQUEST)
        assert historical['state']=='submitted_verified' and historical['submission']['status']=='approved'

@pytest.mark.parametrize('bad',[{'data':[]},{'data':[],'pagination':{'nextCursor':'impossible'}},{'data':[payout(),payout()],'pagination':{'nextCursor':None}}])
def test_bad_pagination_or_duplicate_page_fails(client,bad):
    client._rest.return_value=bad
    with pytest.raises(WhopError):get(client)

def test_indexed_owned_lookup_and_private_db(client):
    get(client)
    with op.journal_lock(client.config) as db:
        plan=db.execute("EXPLAIN QUERY PLAN SELECT request_id FROM operations WHERE json_extract(payload,'$.submission_id')=? AND campaign=? LIMIT 2",(SUBMISSION,CAMPAIGN)).fetchall()
        assert any('operation_submission' in r[-1] for r in plan)
    path=client.config.get_profile_data_dir()/'submission-operations'/'operations.sqlite3'
    assert path.stat().st_mode&0o777==0o600

def test_explicit_one_shared_sync_serves_batch_without_repeated_history(client):
    client._rest.return_value=reply([payout()])
    synced=client.sync_submission_revenue()
    assert synced['complete']
    client._rest.reset_mock()
    first=client.submission_revenue(SUBMISSION,CAMPAIGN,refresh_payouts=False)
    second=client.submission_revenue(SUBMISSION,CAMPAIGN,refresh_payouts=False)
    assert first['received_cents']=='90' and second['received_cents']=='90'
    client._rest.assert_not_called()
    assert first['observed_at']==synced['completed_at']

def test_moderation_429_stops_before_any_link_or_payout_reads(client):
    client._action.side_effect=WhopError('limited',category='rate_limit',status=429,retry_after_seconds=172800)
    with pytest.raises(WhopError) as caught:get(client)
    assert caught.value.retry_after_seconds==172800
    client.linked_accounts.assert_not_called();client._rest.assert_not_called()
    client.account.reset_mock()
    with pytest.raises(WhopError,match='cooldown'):get(client)
    client.account.assert_not_called();client.linked_accounts.assert_not_called();client._rest.assert_not_called()

def test_crash_after_terminal_payout_page_recovers_generation(client,monkeypatch):
    client._rest.side_effect=[reply([payout()], 'last'),reply([payout('second')])]
    original=rev.promote
    def crash(*args): raise KeyboardInterrupt()
    monkeypatch.setattr(rev,'promote',crash)
    with pytest.raises(KeyboardInterrupt):get(client)
    monkeypatch.setattr(rev,'promote',original)
    client._rest.side_effect=None;client._rest.return_value=reply([payout()], 'last')
    result=get(client)
    assert result['sync']['complete'] and result['allocation_count']==2
    # Recovery must not revisit the committed terminal cursor or cycle.
    assert client._rest.call_args.args[1].get('cursor') is None

def test_crash_after_terminal_submission_page_recovers_end_bookkeeping(client,monkeypatch):
    with op.journal_lock(client.config) as db:
        row=op.load(db,REQUEST);row.pop('submission_id');op.save(db,row)
    other={'id':'unrelated','campaignId':CAMPAIGN,'socialMediaPost':{'platform':'tiktok','postId':'987'}}
    client._action.side_effect=[{'data':[other],'nextCursor':'last'},{'data':[{'id':SUBMISSION,'campaignId':CAMPAIGN,'status':'approved','socialMediaPost':{'platform':'tiktok','postId':POST}}],'nextCursor':None}]
    original=op.save
    def crash_after_terminal(db,row):
        original(db,row)
        if row.get('reconciliation',{}).get('pass_end_pending'):raise KeyboardInterrupt()
    monkeypatch.setattr(op,'save',crash_after_terminal)
    with pytest.raises(KeyboardInterrupt):client.reconcile_submission(REQUEST)
    monkeypatch.setattr(op,'save',original)
    client._action.side_effect=None;client._action.return_value={'data':[other],'nextCursor':'last'}
    result=client.reconcile_submission(REQUEST)
    assert result['state']=='submitted_verified' and result['inspection_complete']
    assert result['reconciliation']['completed_scans']==1
    assert client._action.call_count==3

def test_pending_gross_basis_does_not_hide_known_received_net(client):
    client._rest.return_value=reply([payout(),payout('pending',status='pending',accruedAmount='80',netAmount=None)])
    result=get(client)
    assert result['pending_cents'] is None and result['received_cents']=='90' and result['total_earned_cents'] is None
    assert result['provider_display_pending_cents']=='80'
    assert result['allocations'][1]['pending_amount_basis']=='accruedAmount'
    assert result['amount_basis']=='creator_net'

def test_unordered_observation_interval_includes_both_initial_records(client):
    get(client)
    scope,_=rev.owner(client)
    with op.journal_lock(client.config) as db:
        rev.tables(db)
        for index,observed in enumerate(['2026-10-04T00:00:00Z','2026-10-01T00:00:00Z','2026-10-03T00:00:00Z']):
            p=rev.allocation(payout('id_'+str(index)))
            db.execute('INSERT INTO payout_current VALUES(?,?,?,?,?,?)',(scope,p['id'],SUBMISSION,CAMPAIGN,op.canonical(p),observed))
        db.commit()
    result=client.submission_revenue(SUBMISSION,CAMPAIGN,refresh_payouts=False)
    assert result['allocation_observation_started_at']=='2026-10-01T00:00:00Z'
    assert result['allocation_observation_ended_at']=='2026-10-04T00:00:00Z'

def test_moderation_cooldown_blocks_shared_sync_and_other_submission(client):
    client._action.side_effect=WhopError('limited',category='rate_limit',status=429,retry_after_seconds=172800)
    with pytest.raises(WhopError):get(client)
    client.account.reset_mock()
    with pytest.raises(WhopError,match='cooldown'):client.sync_submission_revenue()
    with pytest.raises(WhopError,match='cooldown'):client.submission_revenue('another',CAMPAIGN)
    client.account.assert_not_called();client.linked_accounts.assert_not_called();client._rest.assert_not_called()

def test_old_429_not_resurrected_after_recovery_and_clean_later_miss(client,monkeypatch):
    clock=[1000.0];monkeypatch.setattr(rev.time,'time',lambda:clock[0])
    original_reply=client._action.return_value
    client._action.side_effect=WhopError('limited',category='rate_limit',status=429,retry_after_seconds=100)
    with pytest.raises(WhopError):get(client)
    clock[0]+=101
    client._action.side_effect=None;client._action.return_value=original_reply
    client._rest.return_value=reply([payout()])
    assert get(client)['received_cents']=='90'
    with op.journal_lock(client.config) as db:
        row=op.load(db,REQUEST)
        assert 'failure' not in row and 'retry_not_before' not in row
    client._action.return_value={'data':[],'nextCursor':None}
    client._rest.reset_mock()
    result=get(client)
    assert result['readback_fresh'] is False and result['received_cents'] is None
    client._rest.assert_called_once()
    assert result['sync']['failure'] is None

def test_disappeared_allocation_cannot_resurface_with_foreign_binding(client):
    client._rest.return_value=reply([payout()]);get(client)
    client._rest.return_value=reply([]);get(client)
    client._rest.return_value=reply([payout(campaignId='other_campaign')])
    with pytest.raises(WhopError,match='binding_changed'):get(client)
