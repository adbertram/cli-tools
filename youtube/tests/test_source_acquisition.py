import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_cli import source_acquisition as source


def fixture():
    return json.loads((Path(__file__).parent / 'fixtures/provider-json3-continuations.json').read_bytes())


def test_real_neighbor_fixture_preserves_all_words_once_and_offsets_inside_merged_interval():
    raw = fixture()
    result = source.normalize_json3(raw, duration_seconds=3522, max_cues=10000)
    original = [e for e in raw['events'] if any(s['utf8'].strip() for s in e.get('segs', []))]
    assert len(original) == 12 and len(result) == 8
    original_text = ''.join(''.join(s['utf8'] for s in e['segs']) for e in original)
    assert ''.join(original_text.split()) == ''.join(''.join(c['text'] for c in result).split())
    assert "'80s" in result[-2]['text'] and "' 80s" not in result[-2]['text']
    for event in original:
        cue = next(c for c in result if c['start'] <= event['tStartMs']/1000 < c['end'])
        assert all(cue['start'] <= (event['tStartMs'] + s.get('tOffsetMs', 0))/1000 < cue['end'] for s in event['segs'])
    assert all(a['end'] <= b['start'] for a,b in zip(result,result[1:]))
    assert raw == fixture()


@pytest.mark.parametrize('change', ['greater_overlap','speaker_change','other_window','spoken_append','unordered_offset','out_of_duration','noninteger_time'])
def test_ambiguous_or_invalid_provider_evidence_refuses(change):
    raw=fixture();event=raw['events'][0];following=raw['events'][1]
    if change=='greater_overlap':event['segs'][-1]['tOffsetMs'] += 10
    elif change=='speaker_change':following['segs'][0]['isSpeakerChange']=1
    elif change=='other_window':following['wWinId']=2
    elif change=='spoken_append':event['aAppend']=1
    elif change=='unordered_offset':event['segs'][1]['tOffsetMs']=-1
    elif change=='out_of_duration':event['dDurationMs']=4000000
    elif change=='noninteger_time':event['tStartMs']=1.5
    with pytest.raises(source.SourceAcquisitionError):source.normalize_json3(raw,duration_seconds=3522,max_cues=10000)


def test_control_and_whitespace_append_events_do_not_add_or_drop_words():
    raw=fixture();raw['events'].insert(0,{'tStartMs':0,'id':1})
    raw['events'].insert(2,{'tStartMs':991430,'aAppend':1,'segs':[{'utf8':'\n'}]})
    assert source.normalize_json3(raw,duration_seconds=3522,max_cues=10000)==source.normalize_json3(fixture(),duration_seconds=3522,max_cues=10000)


def test_raw_event_and_cue_limits_refuse():
    with pytest.raises(source.SourceAcquisitionError,match='bound|schema'):
        source.normalize_json3(fixture(),duration_seconds=3522,max_cues=1)


def args():
    return dict(url='https://www.youtube.com/watch?v=h1FbFhWkcGI',expected_video_id='h1FbFhWkcGI',duration_seconds=3522,language='en',timeout_seconds=30,max_caption_bytes=8388608,max_cues=10000,max_result_bytes=1048576)


@pytest.mark.parametrize('status,delay', [(429,172801),(503,30),(403,None)])
def test_typed_provider_failure_preserves_delay_without_text_or_retries(monkeypatch,status,delay):
    calls=[]
    def run(argv,**kw):
        calls.append((argv,kw))
        return SimpleNamespace(returncode=1,stdout=json.dumps({'failure':{'code':'source_caption_http_'+str(status),'category':'rate_limit' if status==429 else 'access_denied' if status==403 else 'transient','status':status,'retry_after_seconds':delay}}).encode())
    monkeypatch.setattr(source,'run_bounded_read',run)
    with pytest.raises(source.SourceAcquisitionError) as error:source.read_source_transcript(**args())
    assert error.value.status==status and error.value.retry_after_seconds==delay
    assert len(calls)==1 and calls[0][1]['timeout_seconds']==29.25


@pytest.mark.parametrize('code,envelope', [(1,{'result':{}}),(0,{'failure':{}}),(0,{'result':{'video_id':'WRONG'}})])
def test_worker_rc_and_shape_refuse(monkeypatch,code,envelope):
    monkeypatch.setattr(source,'run_bounded_read',lambda *a,**k:SimpleNamespace(returncode=code,stdout=json.dumps(envelope).encode()))
    with pytest.raises(source.SourceAcquisitionError,match='schema_changed'):source.read_source_transcript(**args())


def test_request_bounds_reject_before_launch(monkeypatch):
    monkeypatch.setattr(source,'run_bounded_read',lambda *a,**k:pytest.fail('must not launch'))
    for change in [{'expected_video_id':'WRONG'},{'language':'all'},{'timeout_seconds':.75},{'max_caption_bytes':True},{'max_cues':0},{'duration_seconds':float('nan')}]:
        with pytest.raises(source.SourceAcquisitionError):source.read_source_transcript(**(args()|change))


def test_retry_after_date_and_uncapped_numeric():
    assert source.retry_after('172801')==172801
    assert source.retry_after('Tue, 01 Jan 2030 00:00:00 GMT')>86400
    assert source.retry_after('NaN') is None
