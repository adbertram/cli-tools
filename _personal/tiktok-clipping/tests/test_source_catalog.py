"""Mechanical catalog contracts use injected providers, not live permission grants."""
import copy
import json
import os
import sqlite3
from types import SimpleNamespace

import pytest

from tiktok_clipping_cli import source_catalog as sc
from tiktok_clipping_cli.safety import SafetyError

VIDEO='https://www.youtube.com/watch?v=abcdefghijk'
DOC='https://docs.google.com/document/d/document_TEST/edit'
POLICY={'base_seconds':10,'max_seconds':60,'refresh_seconds':120}

class ProviderFailure(Exception):
    def __init__(self,category='transient',retry_after=None):
        super().__init__('SECRET must not enter catalog failures')
        self.category=category;self.code='test_failure';self.status=429 if category=='rate_limit' else 503
        self.retry_after_seconds=retry_after

class Providers:
    binding={'whop_account_id':'user_TEST','whop_profile':'rewards','google_profile':'test',
             'experience':'https://example.apps.whop.com/c/exp_TEST'}
    def __init__(self):
        self.calls=[];self.failures={};self.pages={None:{'rows':[{'id':'campaign_TEST'}],'next_cursor':None}}
        self.details={'campaign_TEST':{'id':'campaign_TEST','name':'Test','description':'Source-backed requirements',
            'private':False,'requiresApplication':False,'platforms':['tiktok'],'status':'active',
            'referenceMaterials':[{'type':'brandAsset','url':DOC}],
            'payouts':[{'platform':'tiktok','payoutType':'cpm','rateCents':100,'minPayoutCents':100,
                        'maxPayoutCents':35000,'budgetCents':15000,'spentCents':0}]}}
        self.briefs={DOC:{'documentId':'document_TEST','content':'Test rights facts. '+VIDEO,'links':[VIDEO],'suggestions_view_mode':'SUGGESTIONS_INLINE','suggestions_present':False,'tabs_complete':True}}
        self.assets={VIDEO:{'id':'abcdefghijk','title':'Test asset','duration':60,'channel_id':'channel_TEST'}}
    def read(self,kind,key,deadline):
        assert deadline==120
        self.calls.append((kind,key))
        if (kind,key) in self.failures:raise self.failures[(kind,key)]
    def campaigns_page(self,*,limit,sort,cursor,deadline):
        assert limit==50 and sort=='newest'
        self.read('page',cursor,deadline)
        page=copy.deepcopy(self.pages[cursor]);page.update(provider_end=page['next_cursor'] is None,
            observed_at='2026-10-04T00:00:00Z',scope='collapsed_groups')
        return page
    def campaign(self,identifier,*,deadline):self.read('detail',identifier,deadline);return copy.deepcopy(self.details[identifier])
    def brief(self,url,*,deadline):self.read('brief',url,deadline);return copy.deepcopy(self.briefs[url])
    def asset(self,url,*,deadline):self.read('asset',url,deadline);return copy.deepcopy(self.assets[url])

@pytest.fixture
def state(tmp_path):
    timer=SimpleNamespace(now=1000)
    catalog=sc.SourceCatalog(tmp_path/'private'/'catalog.sqlite3',clock=lambda:timer.now,monotonic=lambda:0)
    return catalog,Providers(),timer

def refresh(catalog,providers,**changes):
    args={'page_budget':2,'campaign_budget':20,'brief_budget':20,'asset_budget':20,
          'retry_policy':POLICY,'timeout_seconds':120,**changes}
    return catalog.refresh(providers,**args)

def sources(catalog):
    with catalog._db() as db:return [dict(row) for row in db.execute('SELECT * FROM catalog_sources ORDER BY id')]

def reviewed_test_compiler(evidence):
    # A trusted test compiler establishes mechanics only, not real reuse rights.
    return {'video_url':evidence['source_url'],'audio_scope':'original_asset_only','external_audio':False}

def test_default_pending_permission_never_accepts_model_facts(state):
    catalog,provider,_=state
    result=refresh(catalog,provider)
    assert result['pages_read']==1 and result['sources_updated']==1 and not result['failures']
    source=sources(catalog)[0]
    assert source['state']=='pending_permission' and source['reason']=='unsupported_permission_contract'
    assert catalog.eligible(limit=5)['sources']==[]
    assert catalog.admit(source['id'],source['facts_version'],'model_verified_permission')['eligible'] is False
    assert catalog.candidate_evidence(source['id'],source['facts_version'])['asset']['id']=='abcdefghijk'

def test_individual_versions_survive_refresh_restart_and_unrelated_source_growth(state,monkeypatch):
    catalog,provider,timer=state
    monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    refresh(catalog,provider);initial=sources(catalog)[0]
    snapshot=catalog.get_version(initial['id'],initial['current_version'])
    other='https://www.youtube.com/watch?v=lmnopqrstuv'
    provider.briefs[DOC]['links'].append(other)
    provider.assets[other]={'id':'lmnopqrstuv','duration':90}
    timer.now+=121;refresh(catalog,provider)
    assert len(catalog.eligible(limit=5)['sources'])==2
    assert catalog.get_version(initial['id'],initial['current_version'])==snapshot
    reopened=sc.SourceCatalog(catalog.path,clock=lambda:timer.now,monotonic=lambda:0)
    assert reopened.get_version(initial['id'],initial['current_version'])==snapshot
    assert reopened.eligible(limit=5)['complete']

def test_popularity_and_funding_spend_do_not_rewrite_permission_evidence(state,monkeypatch):
    catalog,provider,timer=state;monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    refresh(catalog,provider);before=sources(catalog)[0]
    provider.assets[VIDEO]['view_count']=500
    provider.details['campaign_TEST']['payouts'][0]['spentCents']=1000
    timer.now+=121;refresh(catalog,provider);after=sources(catalog)[0]
    assert after['current_version']==before['current_version']
    assert after['observed_at']>before['observed_at']

def test_changed_rules_revoke_stale_permission_before_asset_budget_can_refresh(state,monkeypatch):
    catalog,provider,timer=state;monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    refresh(catalog,provider);source=sources(catalog)[0];timer.now+=121
    provider.details['campaign_TEST']['creatorRequirements']=['New unsupported requirement']
    provider.failures[('asset',VIDEO)]=ProviderFailure()
    refresh(catalog,provider)
    assert catalog.eligible(limit=5)['sources']==[]
    with pytest.raises(SafetyError,match='dependencies_stale'):
        catalog.admit(source['id'],source['facts_version'],'test-reviewed-v1')

def test_expired_dependency_read_cannot_be_reactivated_by_direct_admit(state,monkeypatch):
    catalog,provider,timer=state;monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    refresh(catalog,provider);source=sources(catalog)[0];timer.now+=121
    assert not catalog.eligible(limit=5)['sources']
    with pytest.raises(SafetyError,match='dependencies_stale'):catalog.admit(source['id'],source['facts_version'],'test-reviewed-v1')

def test_brief_failures_are_due_refreshable_and_removed_asset_scope_is_revoked(state,monkeypatch):
    catalog,provider,timer=state;monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    refresh(catalog,provider);timer.now+=121
    provider.failures[('brief',DOC)]=ProviderFailure()
    result=refresh(catalog,provider)
    assert result['failures'] and not catalog.eligible(limit=5)['sources']
    del provider.failures[('brief',DOC)];timer.now+=11
    refresh(catalog,provider)
    assert len(catalog.eligible(limit=5)['sources'])==1
    timer.now+=121;provider.briefs[DOC]={'documentId':'document_TEST','content':'Asset removed','links':[],'suggestions_view_mode':'SUGGESTIONS_INLINE','suggestions_present':False,'tabs_complete':True}
    refresh(catalog,provider)
    assert not catalog.eligible(limit=5)['sources']
    assert sources(catalog)[0]['reason']=='source_scope_missing_or_incomplete'

def test_provider_cooldown_persists_restart_and_stops_all_later_provider_calls(state):
    catalog,provider,timer=state
    provider.failures[('page',None)]=ProviderFailure('rate_limit',172801)
    result=refresh(catalog,provider)
    assert provider.calls==[('page',None)]
    assert result['cooldowns']['whop']==timer.now+172801
    assert 'SECRET' not in json.dumps(result)
    reopened=sc.SourceCatalog(catalog.path,clock=lambda:timer.now,monotonic=lambda:0)
    provider.calls.clear();timer.now+=121;refresh(reopened,provider)
    assert provider.calls==[]

def test_transient_source_failure_does_not_starve_other_due_source(state):
    catalog,provider,_=state
    other=copy.deepcopy(provider.details['campaign_TEST']);other['id']='campaign_OTHER'
    provider.details['campaign_OTHER']=other;provider.pages[None]['rows'].append({'id':'campaign_OTHER'})
    provider.failures[('detail','campaign_OTHER')]=ProviderFailure()
    result=refresh(catalog,provider)
    assert result['campaigns_updated']==1 and result['sources_updated']==1 and len(result['failures'])==1
    assert ('detail','campaign_TEST') in provider.calls

def test_page_failure_commits_neither_cursor_visit_nor_page_queue_then_resumes(state):
    catalog,provider,timer=state
    provider.pages={None:{'rows':[{'id':'campaign_TEST'}],'next_cursor':'A'},
                    'A':{'rows':[{'id':'campaign_TEST'}],'next_cursor':'B'},
                    'B':{'rows':[{'id':'campaign_NEW'}],'next_cursor':None}}
    provider.failures[('page','A')]=ProviderFailure('rate_limit',30)
    first=refresh(catalog,provider)
    assert first['next_cursor']=='A' and first['pages_read']==1
    with catalog._db() as db:assert db.execute('SELECT count(*) FROM catalog_page_cursors').fetchone()[0]==0
    provider.calls.clear();del provider.failures[('page','A')];timer.now+=31
    second=refresh(catalog,provider)
    assert [key for kind,key in provider.calls if kind=='page']==[None,'A']
    assert second['next_cursor']=='B'
    provider.details['campaign_NEW']=copy.deepcopy(provider.details['campaign_TEST']);provider.details['campaign_NEW']['id']='campaign_NEW'
    provider.calls.clear();third=refresh(catalog,provider)
    assert third['provider_end'] and third['next_cursor'] is None
    assert [key for kind,key in provider.calls if kind=='page']==[None,'B']

def test_cursor_cycle_across_refreshes_is_explicit_not_infinite(state):
    catalog,provider,_=state
    provider.pages={None:{'rows':[{'id':'campaign_TEST'}],'next_cursor':'A'},
                    'A':{'rows':[{'id':'campaign_TEST'}],'next_cursor':'B'},
                    'B':{'rows':[{'id':'campaign_TEST'}],'next_cursor':'A'}}
    assert refresh(catalog,provider)['next_cursor']=='B'
    result=refresh(catalog,provider)
    assert result['next_cursor']=='B' and result['failures'][0]['category']=='invalid_data'

def test_terminal_page_and_due_marker_are_atomic_across_restart(state):
    catalog,provider,timer=state
    provider.pages={None:{'rows':[{'id':'campaign_TEST'}],'next_cursor':'A'},
                    'A':{'rows':[{'id':'campaign_TEST'}],'next_cursor':None}}
    assert refresh(catalog,provider)['provider_end']
    reopened=sc.SourceCatalog(catalog.path,clock=lambda:timer.now,monotonic=lambda:0)
    provider.calls.clear();refresh(reopened,provider);assert provider.calls==[]
    timer.now+=121;refresh(reopened,provider)
    assert [key for kind,key in provider.calls if kind=='page']==[None,'A']

@pytest.mark.parametrize('field,value',[('private',True),('requiresApplication',True),('platforms',['youtube']),('payouts',None)])
def test_unknown_or_ineligible_campaign_never_calls_brief_or_asset(state,field,value):
    catalog,provider,_=state;provider.details['campaign_TEST'][field]=value
    result=refresh(catalog,provider)
    assert result['sources_updated']==0
    assert not any(kind in ('brief','asset') for kind,_ in provider.calls)

def test_missing_platform_funding_allows_rights_selection_with_explicit_publish_gate(state,monkeypatch):
    catalog,provider,timer=state;payout=provider.details['campaign_TEST']['payouts'][0]
    monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    del payout['budgetCents'];del payout['spentCents'];provider.details['campaign_TEST']['budgetCents']=100000
    refresh(catalog,provider)
    with catalog._db() as db:
        row=db.execute('SELECT state,funding FROM catalog_campaigns').fetchone()
        assert row['state']=='funding_unknown' and json.loads(row['funding'])=={'budget_cents':None,'spent_cents':None}
    result=catalog.eligible(limit=5)
    assert result['eligibility_scope']=='candidate_selection_only' and result['publish_readiness_required'] is True
    assert len(result['sources'])==1 and result['sources'][0]['platform_funding']=={'budget_cents':None,'spent_cents':None}
    assert result['sources'][0]['campaign_funding_state']=='funding_unknown'
    payout.update(budgetCents=15000,spentCents=0);timer.now+=121
    assert refresh(catalog,provider)['sources_updated']==1

def test_changed_identity_binding_refused_before_provider_calls(state):
    catalog,provider,_=state;refresh(catalog,provider);provider.calls.clear()
    provider.binding={**provider.binding,'whop_account_id':'user_OTHER'}
    with pytest.raises(SafetyError,match='binding_changed'):refresh(catalog,provider)
    assert provider.calls==[]

@pytest.mark.parametrize('changes',[{'page_budget':1},{'asset_budget':True},{'timeout_seconds':float('inf')},
    {'retry_policy':{'base_seconds':1,'max_seconds':2,'refresh_seconds':False}}])
def test_invalid_budgets_fail_before_provider_io(state,changes):
    catalog,provider,_=state
    with pytest.raises(SafetyError):refresh(catalog,provider,**changes)
    assert provider.calls==[]

def test_evidence_integrity_and_replaced_db_refused(state,tmp_path):
    catalog,provider,_=state;refresh(catalog,provider);source=sources(catalog)[0]
    with catalog._db() as db:db.execute('UPDATE catalog_blobs SET data=? WHERE version=?',('{}',source['facts_version']))
    with pytest.raises(SafetyError,match='integrity_changed'):catalog.get_version(source['id'],source['facts_version'])
    catalog.path.unlink();catalog.path.write_text('replacement')
    with pytest.raises(SafetyError,match='database_replaced'):catalog.eligible(limit=5)

@pytest.mark.parametrize('kind',['fifo','symlink','hardlink','public_file'])
def test_private_db_ownership_refuses_unsafe_file_before_sqlite(tmp_path,kind):
    root=tmp_path/'private';root.mkdir(mode=0o700);path=root/'catalog.db'
    if kind=='fifo':os.mkfifo(path,0o600)
    elif kind=='symlink':path.symlink_to(root/'missing')
    elif kind=='hardlink':
        other=root/'other';other.write_text('');other.chmod(0o600);os.link(other,path)
    else:path.write_text('');path.chmod(0o644)
    with pytest.raises((SafetyError,OSError)):sc.SourceCatalog(path)

def test_symlink_parent_refused_and_private_permission_change_refused(tmp_path,state):
    actual=tmp_path/'actual';actual.mkdir(mode=0o700)
    link=tmp_path/'link';link.symlink_to(actual,target_is_directory=True)
    with pytest.raises(SafetyError,match='path_unsafe'):sc.SourceCatalog(link/'catalog.sqlite3')
    catalog,_,_=state;catalog.path.chmod(0o644)
    with pytest.raises(SafetyError,match='database_replaced'):catalog.eligible(limit=5)

@pytest.mark.parametrize('url',['https://www.youtube.com/@channel','https://www.youtube.com/watch?v=abcdefghijk&token=SECRET',
    'https://www.youtube.com:bad/watch?v=abcdefghijk','https://evil.test/watch?v=abcdefghijk','https://youtu.be//abcdefghijk'])
def test_exact_asset_scope_never_infers_channel_or_ambiguous_url(url):assert sc.video_url(url) is None

def test_refresh_lock_refuses_competing_catalog_writer(state):
    catalog,provider,_=state
    with catalog._refresh_lock():
        with pytest.raises(SafetyError,match='already_running'):refresh(catalog,provider)

def test_metadata_due_fairness_new_sources_do_not_starve_old_failure(state):
    catalog,provider,timer=state
    refresh(catalog,provider)
    with catalog._db() as db:
        db.execute("UPDATE catalog_work SET status='failed',due=? WHERE kind='detail'",(timer.now-1,))
        catalog._queue(db,'detail','AAA_NEW','AAA_NEW',None,{'id':'AAA_NEW'})
    assert catalog._due('detail',1)[0]['id']=='campaign_TEST'

def test_no_lifetime_1000_campaign_cap_and_continuation_survives_calls(state):
    catalog,provider,_=state
    provider.pages={}
    for index in range(23):
        cursor=None if index==0 else str(index)
        provider.pages[cursor]={'rows':[{'id':f'campaign_{index*50+n:04}'} for n in range(50)],
                                'next_cursor':str(index+1) if index<22 else None}
    for _ in range(23):
        result=refresh(catalog,provider,campaign_budget=1)
        if result['provider_end']:break
    assert result['provider_end']
    with catalog._db() as db:assert db.execute("SELECT count(*) FROM catalog_work WHERE kind='detail'").fetchone()[0]==1150

def test_deadline_stops_future_calls_and_retains_atomic_page_checkpoint(state):
    catalog,provider,_=state
    provider.pages[None]['next_cursor']='A'
    ticks=iter([0,0,121,121,121,121,121])
    catalog.monotonic=lambda:next(ticks)
    result=refresh(catalog,provider)
    assert provider.calls==[('page',None)]
    assert result['next_cursor']=='A' and result['deadline_reached']

def test_large_combined_briefs_refused_before_expanded_evidence_materializes(state,monkeypatch):
    catalog,provider,_=state;refresh(catalog,provider);source=sources(catalog)[0]
    monkeypatch.setattr(sc,'MAX_EVIDENCE_BYTES',800)
    with pytest.raises(SafetyError,match='exceeds_bound'):catalog.get_version(source['id'],source['facts_version'])


def test_admission_rejects_refresh_that_changes_facts_during_compilation(state,monkeypatch):
    catalog,provider,timer=state;refresh(catalog,provider);source=sources(catalog)[0]
    def compiler(evidence):
        provider.details['campaign_TEST']['description']='Changed authoritative terms'
        timer.now+=121
        # No compiler is used by this nested refresh; it only changes current facts.
        with monkeypatch.context() as context:
            context.setattr(sc,'COMPILERS',{})
            refresh(catalog,provider)
        return reviewed_test_compiler(evidence)
    monkeypatch.setitem(sc.COMPILERS,'test-racing-v1',compiler)
    with pytest.raises(SafetyError,match='admission_version_changed'):
        catalog.admit(source['id'],source['facts_version'],'test-racing-v1')
    assert not catalog.eligible(limit=5)['sources']


def test_admission_locks_before_dependency_reads_and_keeps_same_snapshot(state,monkeypatch):
    catalog,provider,_=state;refresh(catalog,provider);source=sources(catalog)[0]
    monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    original=catalog._fresh_until;attempts=[]
    def racing_writer(db,row):
        assert db.in_transaction
        competitor=sqlite3.connect(catalog.path,timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError,match='locked'):
                competitor.execute("UPDATE catalog_sources SET facts_version='changed' WHERE id=?",(row['id'],))
            attempts.append(row['facts_version'])
        finally:competitor.close()
        return original(db,row)
    monkeypatch.setattr(catalog,'_fresh_until',racing_writer)
    assert catalog.admit(source['id'],source['facts_version'],'test-reviewed-v1')['eligible']
    assert attempts==[source['facts_version']]
    assert sources(catalog)[0]['facts_version']==source['facts_version']


def test_asset_failure_invalidates_only_that_source_in_same_campaign(state,monkeypatch):
    catalog,provider,timer=state;other='https://www.youtube.com/watch?v=lmnopqrstuv'
    provider.briefs[DOC]['links'].append(other);provider.assets[other]={'id':'lmnopqrstuv','duration':90}
    monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    refresh(catalog,provider);assert len(catalog.eligible(limit=5)['sources'])==2
    provider.failures[('asset',VIDEO)]=ProviderFailure();timer.now+=121
    assert len(refresh(catalog,provider)['failures'])==1
    assert [row['url'] for row in catalog.eligible(limit=5)['sources']]==[other]
    assert next(row for row in sources(catalog) if row['url']==VIDEO)['state']=='stale'


def test_metadata_whitelist_excludes_signed_urls_and_format_inventory(state,monkeypatch):
    catalog,provider,timer=state;monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    provider.assets[VIDEO].update(channel='Test channel',upload_date='20260923',
        url='https://media.test/?token=SECRET',formats=[{'url':'SECRET'}],thumbnails=[{'url':'SECRET'}])
    refresh(catalog,provider);before=sources(catalog)[0]
    asset=catalog.candidate_evidence(before['id'],before['facts_version'])['asset']
    assert set(asset)=={'id','title','duration','channel','channel_id','upload_date'}
    assert 'SECRET' not in json.dumps(asset)
    provider.assets[VIDEO].update(url='DIFFERENT_SECRET',formats=[1,2,3],thumbnails=[4])
    timer.now+=121;refresh(catalog,provider)
    assert sources(catalog)[0]['current_version']==before['current_version']
    with catalog._db() as db:
        assert not db.execute("SELECT 1 FROM catalog_blobs WHERE data LIKE '%SECRET%'").fetchone()


def test_observed_short_share_link_token_is_removed_without_changing_exact_id():
    assert sc.video_url('https://youtu.be/KE4wmYSSzTs?si=abcdefghijklmnop')=='https://www.youtube.com/watch?v=KE4wmYSSzTs'
    for query in ('si=','si=a&si=b','si=a&token=SECRET','v=other'):
        assert sc.video_url('https://youtu.be/KE4wmYSSzTs?'+query) is None


COMMISSION_DESCRIPTION=('Clip any episode of Call It a Day with Sara K from Lyrical Lemonade TV. '
    '14 episodes: Frost Children, Sturniolo Triplets, Slayr, Lucy Bedroque and more. '
    'Inspirational, sad or happy moments over trending sounds hit hardest. '
    '$1.50 per 1K views on TikTok, Instagram and YouTube. Pays from 1,000 views.')

def commission_provider(provider):
    detail=provider.details['campaign_TEST']
    detail.update(name='CLIP ANY CALL IT A DAY EPISODE',description=COMMISSION_DESCRIPTION,
        creatorRequirements=[sc.EDITORIAL_REQUIREMENT],referenceMaterials=[{'type':'brandAsset','url':VIDEO}])
    detail['payouts'][0].update(rateCents=150,minPayoutCents=150,maxPayoutCents=10000)
    provider.assets[VIDEO].update(channel='Lyrical Lemonade TV',channel_id='UCMreYZfbzsP4eHgJMlpqRYQ',upload_date='20260923')


def test_full_commission_family_admits_exact_audiovisual_source_with_embedded_audio(state):
    catalog,provider,_=state;commission_provider(provider)
    assert refresh(catalog,provider)['sources_updated']==1
    result=catalog.eligible(limit=5);assert len(result['sources'])==1
    source=result['sources'][0];permission=catalog.get_version(source['id'],source['current_version'])['permission']
    assert permission['audio_scope']=='embedded_original_asset_only' and permission['external_audio'] is False
    assert permission['recommendation_requires_external_music'] is False
    assert permission['reference_membership_indexes']==[0] and permission['publish_readiness_required']
    assert permission['video_id']=='abcdefghijk'
    for span in permission['evidence_spans'].values():
        assert COMMISSION_DESCRIPTION[span['start']:span['end']]==span['text']


def test_parameterized_commission_admits_new_campaign_publisher_and_supplied_video(state):
    catalog,provider,_=state;commission_provider(provider)
    detail=provider.details.pop('campaign_TEST');detail['id']='new_CAMPAIGN'
    detail['description']=detail['description'].replace('Call It a Day','New Episode Series').replace('Sara K','New Host').replace('Lyrical Lemonade TV','New Publisher').replace('14 episodes','27 episodes').replace('$1.50','$2.50')
    detail['payouts'][0].update(rateCents=250,minPayoutCents=250)
    other='https://www.youtube.com/watch?v=lmnopqrstuv';detail['referenceMaterials'][0]['url']=other
    provider.details={'new_CAMPAIGN':detail};provider.pages[None]['rows']=[{'id':'new_CAMPAIGN'}]
    provider.assets[other]={**provider.assets[VIDEO],'id':'lmnopqrstuv','channel':'New Publisher','channel_id':'new_CHANNEL'}
    refresh(catalog,provider)
    assert [r['url'] for r in catalog.eligible(limit=5)['sources']]==[other]


@pytest.mark.parametrize('change',[
    'extra_clause','numeric_demographics','audio_required','other_document','non_brand_asset',
    'wrong_channel','missing_channel_id','rate_conflict','minimum_conflict','unlisted_video'])
def test_full_compiler_refuses_unknown_contradictory_or_unbound_permission(state,change):
    catalog,provider,_=state;commission_provider(provider);detail=provider.details['campaign_TEST']
    if change=='extra_clause':detail['description']+=' Only post to pages with 50% US viewers.'
    elif change=='numeric_demographics':detail['creatorRequirements'].append('50% US viewers required')
    elif change=='audio_required':detail['description']=detail['description'].replace('hit hardest.','are mandatory.')
    elif change=='other_document':detail['referenceMaterials'].append({'type':'brandAsset','url':DOC})
    elif change=='non_brand_asset':detail['referenceMaterials'][0]['type']='other'
    elif change=='wrong_channel':provider.assets[VIDEO]['channel']='Other Publisher'
    elif change=='missing_channel_id':del provider.assets[VIDEO]['channel_id']
    elif change=='rate_conflict':detail['payouts'][0]['rateCents']=100
    elif change=='minimum_conflict':detail['payouts'][0]['minPayoutCents']=100
    elif change=='unlisted_video':
        detail['referenceMaterials'][0]['url']=DOC
        provider.briefs[DOC]['links']=[VIDEO]
    refresh(catalog,provider)
    assert not catalog.eligible(limit=5)['sources']


def test_playlist_does_not_expand_members_and_exhausted_platform_remains_excluded(state):
    catalog,provider,timer=state;commission_provider(provider);detail=provider.details['campaign_TEST']
    detail['referenceMaterials'].append({'type':'brandAsset','url':'https://www.youtube.com/playlist?list=PLprovided'})
    refresh(catalog,provider)
    assert len(sources(catalog))==1 and len(catalog.eligible(limit=5)['sources'])==1
    detail['payouts'][0]['spentCents']=detail['payouts'][0]['budgetCents'];timer.now+=121
    refresh(catalog,provider);assert not catalog.eligible(limit=5)['sources']


def test_current_lookup_refuses_historical_changed_removed_and_revoked_permissions(state,monkeypatch):
    catalog,provider,timer=state;commission_provider(provider);refresh(catalog,provider)
    source=catalog.eligible(limit=1)['sources'][0];old=source['current_version']
    valid=catalog.validate_current(source['id'],old)
    assert valid['funding']['scope']=='platform' and valid['publish_readiness_required']
    with monkeypatch.context() as context:
        context.setattr(sc,'COMPILERS',{})
        assert not catalog.eligible(limit=5)['sources']
        with pytest.raises(SafetyError,match='compiler_revoked'):catalog.validate_current(source['id'],old)
    with monkeypatch.context() as context:
        context.setitem(sc.COMPILERS,sc.COMMISSION_VERSION,lambda evidence:{'changed':True})
        with pytest.raises(SafetyError,match='compiler_changed'):catalog.validate_current(source['id'],old)
    timer.now+=121
    with pytest.raises(SafetyError,match='dependencies_stale'):catalog.validate_current(source['id'],old)
    provider.details['campaign_TEST']['referenceMaterials']=[];refresh(catalog,provider)
    assert catalog.get_version(source['id'],old)['permission']==valid['permission']
    with pytest.raises(SafetyError,match='current_permission_changed'):catalog.validate_current(source['id'],old)


def test_unresolved_doc_suggestions_retain_evidence_without_asset_or_permission(state,monkeypatch):
    catalog,provider,_=state
    monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    provider.briefs[DOC]['suggestions_present']=True
    result=refresh(catalog,provider)
    assert any(f['code'] is None and f['category']=='invalid_data' for f in result['failures'])
    assert not any(kind=='asset' for kind,key in provider.calls)
    assert not catalog.eligible(limit=5)['sources']
    with catalog._db() as db:
        row=db.execute("SELECT * FROM catalog_work WHERE kind='brief'").fetchone()
        assert row['status']=='failed' and catalog._blob(row['value_ref'])['suggestions_present'] is True


def test_transcript_availability_refresh_is_operational_not_permission_revision(state,monkeypatch):
    catalog,provider,timer=state;monkeypatch.setitem(sc.COMPILERS,'test-reviewed-v1',reviewed_test_compiler)
    provider.assets[VIDEO].update(observed_at='2026-10-04T00:00:00Z',transcript_availability={'manual_language_codes':None,'automatic_language_codes':['en'],'kind':'extractor_reported_language_codes'})
    refresh(catalog,provider);initial=sources(catalog)[0]
    provider.assets[VIDEO]['transcript_availability']['automatic_language_codes']=['en','fr']
    provider.assets[VIDEO]['observed_at']='2026-10-04T00:05:00Z';timer.now+=121;refresh(catalog,provider)
    assert sources(catalog)[0]['current_version']==initial['current_version']
    assert catalog.source_observation(initial['id'])=={'observed_at':'2026-10-04T00:05:00Z','transcript_availability':{'manual_language_codes':None,'automatic_language_codes':['en','fr'],'kind':'extractor_reported_language_codes'}}


def test_compiler_owns_distinct_video_shared_regime_and_terms_split(state):
    catalog,provider,timer=state;commission_provider(provider)
    other='https://www.youtube.com/watch?v=lmnopqrstuv'
    provider.details['campaign_TEST']['referenceMaterials'].append({'type':'brandAsset','url':other})
    provider.assets[other]={**provider.assets[VIDEO],'id':'lmnopqrstuv'}
    refresh(catalog,provider);eligible=catalog.eligible(limit=5)['sources']
    assert len(eligible)==2
    permissions=[catalog.get_version(r['id'],r['current_version'])['permission'] for r in eligible]
    assert permissions[0]['video_id']!=permissions[1]['video_id']
    assert permissions[0]['ranking_regime_digest']==permissions[1]['ranking_regime_digest']
    assert permissions[0]['on_video_ad_disclosure_required'] is False and permissions[0]['show_attribution']=='Call It a Day' and permissions[0]['creator_attribution']=='Sara K'
    provider.details['campaign_TEST']['description']+= ' You must burn an Ad disclaimer into every video.'
    timer.now+=121;refresh(catalog,provider)
    assert not catalog.eligible(limit=5)['sources']


def test_owning_sdk_provider_bridge_exact_profiles_scope_deadline_and_canonical_id(monkeypatch):
    from whop_cli import config as wc
    from google_cli import config as gc
    from whop_cli.client import WhopClient
    from google_cli.client import GoogleClient
    from youtube_cli.client import YoutubeClient
    calls=[]
    monkeypatch.setattr(wc,'Config',lambda **kw:SimpleNamespace(rewards_url='https://example.apps.whop.com/c/exp_TEST',profile=kw['profile']))
    monkeypatch.setattr(gc,'Config',lambda **kw:SimpleNamespace(profile=kw['profile']))
    monkeypatch.setattr(sc.time,'monotonic',lambda:100)
    def capture(name,result):
        def read(*args,**kwargs):calls.append((name,args,kwargs));return result
        return read
    page={'rows':[],'next_cursor':None,'provider_end':True,'scope':'collapsed_groups','observed_at':'2026-10-04T00:00:00Z'}
    monkeypatch.setattr(WhopClient,'campaigns_page_bounded',capture('page',page))
    monkeypatch.setattr(WhopClient,'campaign_bounded',capture('campaign',{'id':'campaign_TEST'}))
    monkeypatch.setattr(GoogleClient,'read_document_bounded',capture('doc',{'documentId':'document_TEST'}))
    monkeypatch.setattr(YoutubeClient,'get_source_metadata',capture('asset',{'id':'abcdefghijk'}))
    provider=sc.SDKProviders(whop_profile='rewards',whop_account_id='user_TEST',google_profile='adbertram')
    assert provider.campaigns_page(limit=50,sort='newest',cursor=None,deadline=112)==page
    provider.campaign('campaign_TEST',deadline=112);provider.brief(DOC,deadline=112);provider.asset('https://youtu.be/abcdefghijk?si=abcdefghijklmnop',deadline=112)
    assert provider.binding=={'whop_profile':'rewards','whop_account_id':'user_TEST','google_profile':'adbertram','experience':'https://example.apps.whop.com/c/exp_TEST'}
    assert all(c[2]['timeout_seconds']==12 for c in calls)
    assert calls[0][2]['expected_account_id']=='user_TEST' and calls[2][1][1]=='document_TEST' and calls[3][1][0]==VIDEO
    with pytest.raises(SafetyError,match='deadline_exceeded'):provider.asset(VIDEO,deadline=100)
    assert len(calls)==4


def test_status_restart_preserves_successful_page_and_provider_end_after_failed_refresh(state):
 catalog,provider,timer=state;refresh(catalog,provider);initial=catalog.status()
 assert initial['scan']['current_pass_provider_end'] and initial['scan']['last_successful_page']['recorded_at']==1000
 timer.now+=121;provider.failures[('page',None)]=ProviderFailure('rate_limit',172800)
 refresh(catalog,provider)
 reopened=sc.SourceCatalog(catalog.path,clock=lambda:timer.now,monotonic=lambda:0);current=reopened.status()
 assert current['scan']['last_successful_page']==initial['scan']['last_successful_page']
 assert current['scan']['last_provider_end']==initial['scan']['last_provider_end']
 assert current['last_refresh']['failures'][0]['category']=='rate_limit' and current['cooldowns']['whop']==timer.now+172800
 assert not current['global_empty_proven']


def test_partial_scan_with_no_eligible_supply_is_explicitly_unknown(state):
 catalog,provider,_=state
 provider.pages={None:{'rows':[],'next_cursor':None}}
 provider.failures[('page',None)]=ProviderFailure()
 refresh(catalog,provider)
 report=catalog.status()
 assert report['eligible_count']==0 and not report['scan']['current_pass_provider_end']
 assert report['scan']['last_successful_page'] is None and not report['global_empty_proven']


def test_status_document_access_denial_is_unit_failure_not_account_auth(state):
 catalog,provider,_=state;provider.failures[('brief',DOC)]=ProviderFailure('access_denied')
 refresh(catalog,provider)
 assert catalog.status()['unit_failures']==[{'provider':'google','category':'access_denied','count':1}]
 assert catalog.status()['cooldowns']=={}
 assert 'SECRET' not in json.dumps(catalog.status())


def test_interrupted_refresh_is_durable_even_when_injected_clock_does_not_advance(state,monkeypatch):
 catalog,provider,timer=state;refresh(catalog,provider);prior=catalog.status()['last_refresh']
 def interrupted(*args):raise KeyboardInterrupt()
 monkeypatch.setattr(catalog,'_walk',interrupted)
 with pytest.raises(KeyboardInterrupt):refresh(catalog,provider)
 reopened=sc.SourceCatalog(catalog.path,clock=lambda:timer.now,monotonic=lambda:0)
 assert reopened.status()['refresh_interrupted_or_in_progress'] is True
 assert reopened.status()['last_refresh']==prior and 'next_cursor' not in prior


def test_status_progress_tracks_successful_dependencies_and_survives_failed_refresh(state):
 catalog,provider,timer=state;refresh(catalog,provider)
 initial=catalog.status()['scan'];assert initial['last_progress']=={'kind':'asset','recorded_at':1000}
 assert initial['first_refresh_started']==1000
 timer.now+=121
 # Page reads now fail, but independently due dependency successes still progress.
 provider.failures[('page',None)]=ProviderFailure()
 refresh(catalog,provider)
 second=catalog.status()['scan'];assert second['last_successful_page']==initial['last_successful_page']
 assert second['last_progress']=={'kind':'asset','recorded_at':1121}
 timer.now+=121
 for kind,key in [('detail','campaign_TEST'),('brief',DOC),('asset',VIDEO)]:
  provider.failures[(kind,key)]=ProviderFailure()
 refresh(catalog,provider)
 reopened=sc.SourceCatalog(catalog.path,clock=lambda:timer.now,monotonic=lambda:0)
 assert reopened.status()['scan']['last_progress']==second['last_progress']
 assert reopened.status()['scan']['first_refresh_started']==1000


def test_never_successful_scan_retains_original_start_without_inventing_progress(state):
 catalog,provider,timer=state;provider.failures[('page',None)]=ProviderFailure()
 refresh(catalog,provider);timer.now+=121;refresh(catalog,provider)
 assert catalog.status()['scan']['first_refresh_started']==1000
 assert catalog.status()['scan']['last_progress'] is None
