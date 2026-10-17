import copy
import pytest
from tiktok_clipping_cli.safety import SafetyError,edit_segments,edit_duration,validate_proposal
from tiktok_clipping_cli.rights import validate_policy,required_overlays
from tiktok_clipping_cli.media import clip_segments


def scoped_policy(source):
    return {'schema_version':1,'campaign_id':source['campaign']['id'],'brief_url':source['reuse_evidence'],'brief_content_sha256':'b'*64,'source_url':source['feed'],'source_sha256':'a'*64,'source_bytes':100,'video_reuse_allowed':True,'original_audio_reuse_allowed':True,'external_audio_allowed':False,'full_source_repost_allowed':False,'minimum_clip_seconds':7,'required_caption_tokens':['@hardscope','#ad'],'required_on_screen_text':['Ad','@hardscope'],'clip_rules':[{'segments':[{'start_seconds':70.25,'end_seconds':77.1},{'start_seconds':54.8,'end_seconds':56.2}],'caption_tokens':['#loveandjustice'],'on_screen_text':['Love and Justice']}]}


def test_ordered_edit_sums_cuts_not_source_bounds(config):
    p={'start_seconds':54.8,'end_seconds':77.1,'segments':[{'start_seconds':70.25,'end_seconds':77.1},{'start_seconds':54.8,'end_seconds':56.2}],'caption':'TEST','style':'plain'}
    config['limits']['min_clip_seconds']=7
    validate_proposal('clip',p,{'duration_seconds':115},config)
    assert edit_segments(p)==p['segments']
    assert abs(edit_duration(p)-8.25)<1e-9
    config['limits']['min_clip_seconds']=10
    with pytest.raises(SafetyError):validate_proposal('clip',p,{'duration_seconds':115},config)


@pytest.mark.parametrize('cuts',[
    [{'start_seconds':0,'end_seconds':4},{'start_seconds':3,'end_seconds':5}],
    [{'start_seconds':0,'end_seconds':5},{'start_seconds':0,'end_seconds':5}],
    [{'start_seconds':2,'end_seconds':2}],
    [{'start_seconds':float('nan'),'end_seconds':5}],
    [{'start_seconds':0,'end_seconds':float('inf')}],
    [{'start_seconds':i,'end_seconds':i+1} for i in range(5)],
])
def test_invalid_edits_fail_explicitly(cuts):
    with pytest.raises(SafetyError):edit_segments({'start_seconds':0,'end_seconds':5,'segments':cuts},10)


def test_edit_bounds_and_out_of_source_cuts_rejected():
    with pytest.raises(SafetyError,match='edit_bounds'):edit_segments({'start_seconds':0,'end_seconds':10,'segments':[{'start_seconds':2,'end_seconds':5}]},10)
    with pytest.raises(SafetyError):edit_segments({'start_seconds':0,'end_seconds':11},10)
    assert edit_segments({'start_seconds':2,'end_seconds':5})==[{'start_seconds':2,'end_seconds':5}]


def test_reordered_caption_offsets_follow_rendered_timeline():
    segments=[{'start':0,'end':2,'text':'First sentence.'},{'start':2,'end':4,'text':'Second sentence.'}]
    p={'start_seconds':0,'end_seconds':4,'segments':[{'start_seconds':2,'end_seconds':4},{'start_seconds':0,'end_seconds':2}]}
    assert clip_segments(segments,p)==[{'start':0,'end':2,'text':'Second sentence.'},{'start':2,'end':4,'text':'First sentence.'}]


def test_rights_bind_exact_campaign_brief_source_and_audio(config):
    source=config['sources'][0];source['reuse_evidence']='https://docs.google.com/document/d/TEST/edit'
    p=scoped_policy(source);validate_policy(p,source)
    for field,value in [('campaign_id','other'),('brief_url','https://docs.google.com/document/d/OTHER/edit'),('source_url','https://other.example/video'),('external_audio_allowed',True),('original_audio_reuse_allowed',False),('full_source_repost_allowed',True)]:
        altered={**p,field:value}
        with pytest.raises(SafetyError):validate_policy(altered,source)


def test_clip_specific_show_label_only_for_exact_qualified_edit(config):
    p=scoped_policy(config['sources'][0])
    proposal={'start_seconds':54.8,'end_seconds':77.1,'segments':p['clip_rules'][0]['segments'],'caption':'Watch Love and Justice @hardscope #loveandjustice #ad'}
    assert required_overlays(p,proposal)==['Ad','@hardscope','Love and Justice']
    unrelated={'start_seconds':0,'end_seconds':10,'caption':'A trailer moment @hardscope #ad'}
    assert required_overlays(p,unrelated)==['Ad','@hardscope']
    with pytest.raises(SafetyError,match='clip_specific_claim'):required_overlays(p,{**unrelated,'caption':proposal['caption']})
    with pytest.raises(SafetyError,match='caption_token_missing'):required_overlays(p,{**unrelated,'caption':'@hardscope123 #ad'})


@pytest.mark.parametrize('caption', ['@hardscope.evil #ad', '@hardscope_123 #ad', '@hardscope. #ad'])
def test_mention_requires_full_native_handle_boundary(caption):
    from tiktok_clipping_cli.rights import has_token
    assert not has_token(caption, '@hardscope')
    assert has_token('Watch (@hardscope), #ad', '@hardscope')


def test_new_policy_excludes_added_ad_text_but_preserves_historical_audit(config):
    from tiktok_clipping_cli.rights import current_render_policy
    source=config['sources'][0];source['reuse_evidence']='https://docs.google.com/document/d/TEST/edit'
    old=scoped_policy(source);assert validate_policy(old,source)==old
    with pytest.raises(SafetyError,match='current_no_ad'):current_render_policy(old)
    current={**old,'schema_version':2,'required_on_screen_text':['HardScope']}
    assert validate_policy(current,source)==current
    assert '#ad' in current['required_caption_tokens']
    for disclaimer in ['Ad','Advertisement','Sponsored','Paid partnership','This is an ad']:
        with pytest.raises(SafetyError,match='forbidden_on_video'):
            validate_policy({**current,'required_on_screen_text':['HardScope',disclaimer]},source)
        modified=copy.deepcopy(current);modified['clip_rules'][0]['on_screen_text'].append(disclaimer)
        with pytest.raises(SafetyError,match='forbidden_on_video'):validate_policy(modified,source)
