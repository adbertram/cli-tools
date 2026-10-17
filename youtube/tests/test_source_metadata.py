import json
from types import SimpleNamespace

import pytest

from youtube_cli import source_metadata as sm
from youtube_cli.client import YoutubeClient

FACTS={'id':'h1FbFhWkcGI','title':'Actual title','duration':3522,'channel':'Lyrical Lemonade TV',
       'channel_id':'UCMreYZfbzsP4eHgJMlpqRYQ','upload_date':'20260923'}
URL='https://www.youtube.com/watch?v=h1FbFhWkcGI'

def fake(monkeypatch,*,facts=None,languages=('NA','en, en-orig'),raw=None,returncode=0):
    captured=[];monkeypatch.setattr(sm.shutil,'which',lambda name:'/verified/yt-dlp')
    def runner(argv,**kwargs):
        captured.append((argv,kwargs))
        data=raw if raw is not None else ('\n'.join([json.dumps(FACTS if facts is None else facts),*languages])+'\n').encode()
        return SimpleNamespace(stdout=data,returncode=returncode,stderr_bytes=123)
    monkeypatch.setattr(sm,'run_bounded_read',runner)
    return captured

def test_sdk_class_call_avoids_unbounded_constructor_and_emits_only_stable_template(monkeypatch):
    calls=fake(monkeypatch)
    monkeypatch.setattr(YoutubeClient,'__init__',lambda *a:pytest.fail('unbounded constructor'))
    result=YoutubeClient.get_source_metadata(URL,timeout_seconds=12,max_bytes=65536)
    assert result['id']==FACTS['id'] and result['duration']==3522
    assert result['transcript_availability']['manual_language_codes'] is None
    assert result['transcript_availability']['automatic_language_codes']==['en','en-orig']
    argv,kwargs=calls[0]
    assert sm.TEMPLATE in argv and '--ignore-config' in argv and '--no-playlist' in argv and '--skip-download' in argv
    assert '--dump-json' not in argv and kwargs=={'timeout_seconds':11.25,'max_stdout_bytes':65536}
    assert not any(k in result for k in ('url','formats','subtitles','automatic_captions','thumbnails'))

@pytest.mark.parametrize('facts',[{**FACTS,'id':'differentID'},{**FACTS,'duration':float('nan')},
    {**FACTS,'duration':True},{**FACTS,'upload_date':'20261342'},{**FACTS,'url':'SECRET'}])
def test_schema_changes_refuse_without_raw_data(monkeypatch,facts):
    fake(monkeypatch,facts=facts)
    with pytest.raises(sm.SourceMetadataError,match='source_metadata_schema_changed') as error:
        YoutubeClient.get_source_metadata(URL,timeout_seconds=12,max_bytes=65536)
    assert error.value.category=='invalid_data' and 'SECRET' not in str(error.value)

@pytest.mark.parametrize('raw',[b'\xff',b'{partial\nNA\nen\n',b'{}\nNA\nen\nEXTRA\n'])
def test_invalid_utf8_partial_json_and_extra_output_fail_closed(monkeypatch,raw):
    fake(monkeypatch,raw=raw)
    with pytest.raises(sm.SourceMetadataError):YoutubeClient.get_source_metadata(URL,timeout_seconds=12,max_bytes=65536)

def test_nonzero_exit_is_sanitized_without_stderr_scraping(monkeypatch):
    fake(monkeypatch,returncode=1)
    with pytest.raises(sm.SourceMetadataError,match='source_metadata_read_failed') as error:
        YoutubeClient.get_source_metadata(URL,timeout_seconds=12,max_bytes=65536)
    assert error.value.status is None and error.value.retry_after_seconds is None

def test_observed_si_short_url_canonicalizes_but_untrusted_query_refuses(monkeypatch):
    calls=fake(monkeypatch)
    YoutubeClient.get_source_metadata('https://youtu.be/h1FbFhWkcGI?si=abcdefghijklmnop',timeout_seconds=12,max_bytes=65536)
    assert calls[0][0][-1]==URL
    with pytest.raises(sm.SourceMetadataError,match='url_invalid'):
        YoutubeClient.get_source_metadata(URL+'&token=SECRET',timeout_seconds=12,max_bytes=65536)
    assert len(calls)==1
