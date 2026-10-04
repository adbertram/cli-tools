import json
from types import SimpleNamespace
import pytest
from google_cli import bounded_documents as bd
from google_cli.client import GoogleClient

DOCID='document_123'
def document():
 return {'documentId':DOCID,'title':'Authoritative brief','suggestionsViewMode':'SUGGESTIONS_INLINE','tabs':[{'documentTab':{'body':{'content':[{'paragraph':{'elements':[{'textRun':{'content':'First tab\n','textStyle':{'link':{'url':'https://youtu.be/h1FbFhWkcGI'}}}}]}}]}}},{'documentTab':{'body':{'content':[{'paragraph':{'elements':[{'textRun':{'content':'Second tab\n'}}]}}]}}}]}


def test_all_tabs_links_and_explicit_suggestions_view():
 result=bd.normalize_document(document(),DOCID)
 assert result['content']=='First tab\nSecond tab\n'
 assert result['links']==['https://youtu.be/h1FbFhWkcGI']
 assert result['tabs_complete'] is True and result['suggestions_present'] is False
 assert result['suggestions_view_mode']=='SUGGESTIONS_INLINE'

@pytest.mark.parametrize('field,value',[('suggestedInsertionIds',['id']),('suggestedDeletionIds',['id']),('suggestedTextStyleChanges',{'id':{}})])
def test_unresolved_suggestions_are_retained_and_explicit_not_accepted(field,value):
 doc=document();run=doc['tabs'][0]['documentTab']['body']['content'][0]['paragraph']['elements'][0]['textRun'];run[field]=value
 result=bd.normalize_document(doc,DOCID)
 assert result['suggestions_present'] is True and 'First tab' in result['content']

@pytest.mark.parametrize('change',[{'documentId':'other'},{'tabs':[]},{'suggestionsViewMode':'PREVIEW_SUGGESTIONS_ACCEPTED'}])
def test_identity_empty_tabs_or_wrong_view_refuses(change):
 with pytest.raises(bd.DocumentReadError):bd.normalize_document(document()|change,DOCID)


def test_sdk_avoids_interactive_constructor_and_uses_exact_named_worker(monkeypatch):
 calls=[];result=bd.normalize_document(document(),DOCID)
 monkeypatch.setattr(GoogleClient,'__init__',lambda *args:pytest.fail('interactive constructor'))
 def runner(argv,**kwargs):calls.append((argv,kwargs));return SimpleNamespace(stdout=json.dumps({'result':result}).encode(),returncode=0)
 monkeypatch.setattr(bd,'run_bounded_read',runner)
 config=SimpleNamespace(get_active_profile_name=lambda:'adbertram')
 assert GoogleClient.read_document_bounded(config,DOCID,timeout_seconds=12,max_bytes=65536)==result
 argv,options=calls[0]
 assert argv[1:]==['-m','google_cli.bounded_documents','adbertram',DOCID,'65536','12']
 assert options=={'timeout_seconds':11.25,'max_stdout_bytes':65536}


def transport(monkeypatch,*,status=200,chunks=None,header=None,error=None):
 import google.auth.transport.requests as auth
 import google_cli.config as cfg
 calls=[]
 response=SimpleNamespace(status_code=status,headers={} if header is None else {'Retry-After':header},closed=False)
 def close():response.closed=True
 response.close=close
 def content(n):
  calls.append(('chunks',n))
  yield from ([json.dumps(document()).encode()] if chunks is None else chunks)
 response.iter_content=content
 class Session:
  def __init__(self,*args,**kwargs):calls.append(('session',kwargs))
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def get(self,url,**kwargs):
   calls.append(('get',url,kwargs))
   if error:raise error
   return response
 monkeypatch.setattr(auth,'AuthorizedSession',Session)
 monkeypatch.setattr(cfg,'Config',lambda **kwargs:SimpleNamespace())
 monkeypatch.setattr(bd,'_token',lambda config:object())
 return response,calls


def test_worker_streams_exact_docs_route_no_redirects_and_all_tabs(monkeypatch):
 response,calls=transport(monkeypatch)
 result=bd._worker('adbertram',DOCID,65536,12)
 assert result['tabs_complete'] and response.closed
 get=next(c for c in calls if c[0]=='get')
 assert get[1]=='https://docs.googleapis.com/v1/documents/'+DOCID
 assert get[2]['params']=={'includeTabsContent':'true','suggestionsViewMode':'SUGGESTIONS_INLINE'}
 assert get[2]['stream'] is True and get[2]['allow_redirects'] is False

@pytest.mark.parametrize('status,category',[(401,'auth'),(403,'access_denied'),(429,'rate_limit'),(503,'transient')])
def test_error_stream_not_read_and_uncapped_provider_delay_preserved(monkeypatch,status,category):
 response,calls=transport(monkeypatch,status=status,header='172800')
 with pytest.raises(bd.DocumentReadError) as exc:bd._worker('adbertram',DOCID,65536,12)
 assert exc.value.status==status and exc.value.category==category and exc.value.retry_after_seconds==172800
 assert response.closed and not any(c[0]=='chunks' for c in calls)


def test_byte_bound_closes_stream_before_decode(monkeypatch):
 response,calls=transport(monkeypatch,chunks=[b'x'*1025])
 with pytest.raises(bd.DocumentReadError,match='document_response_exceeds_bound'):bd._worker('adbertram',DOCID,1024,12)
 assert response.closed

@pytest.mark.parametrize('raw',[b'\xff',b'{partial'])
def test_invalid_utf8_or_partial_provider_json_sanitized(monkeypatch,raw):
 response,calls=transport(monkeypatch,chunks=[raw])
 with pytest.raises(bd.DocumentReadError,match='document_response_schema_changed'):bd._worker('adbertram',DOCID,65536,12)
 assert response.closed


def test_credential_refresh_failure_never_starts_oauth(monkeypatch):
 from google.auth.exceptions import RefreshError
 transport(monkeypatch,error=RefreshError('SECRET'))
 with pytest.raises(bd.DocumentReadError,match='document_credential_refresh_failed') as exc:bd._worker('adbertram',DOCID,65536,12)
 assert exc.value.category=='auth' and 'SECRET' not in str(exc.value)

@pytest.mark.parametrize('profile,doc,bound,seconds',[('../other',DOCID,1024,12),('ok','bad/ID',1024,12),('ok',DOCID,0,12),('ok',DOCID,1024,float('nan')),('ok',DOCID,1024,True)])
def test_worker_validates_before_credentials(monkeypatch,profile,doc,bound,seconds):
 monkeypatch.setattr(bd,'_token',lambda config:pytest.fail('credentials touched'))
 with pytest.raises(bd.DocumentReadError) as exc:bd._worker(profile,doc,bound,seconds)
 assert exc.value.category=='invalid_request'


def test_http_date_retry_after_uses_utc_and_missing_invalid_is_unknown():
 from datetime import datetime,timedelta,timezone
 from email.utils import format_datetime
 assert 172790<bd.retry_after(format_datetime(datetime.now(timezone.utc)+timedelta(days=2)))<=172800
 assert bd.retry_after('not-a-date') is None and bd.retry_after('NaN') is None


def test_saved_token_fifo_refuses_without_blocking(tmp_path):
 import os
 path=tmp_path/'fifo';os.mkfifo(path)
 with pytest.raises(bd.DocumentReadError) as exc:bd._token(SimpleNamespace(token_path_obj=path))
 assert exc.value.category=='auth'


def test_nested_child_tabs_document_tab_text_is_not_omitted():
 doc=document();child=doc['tabs'].pop();doc['tabs'][0]['childTabs']=[child]
 result=bd.normalize_document(doc,DOCID)
 assert result['content']=='First tab\nSecond tab\n' and result['tabs_complete']

@pytest.mark.parametrize('tab',[{}, {'documentTab':{}}, {'documentTab':{'body':{'content':[]}},'childTabs':{}}])
def test_unsupported_tab_structure_refuses_authoritative_evidence(tab):
 doc=document();doc['tabs'][0]['childTabs']=[tab]
 with pytest.raises(bd.DocumentReadError,match='document_tab_structure_unsupported'):bd.normalize_document(doc,DOCID)


def test_nontext_evidence_cannot_silently_authorize_rights():
 doc=document();doc['tabs'][0]['documentTab']['body']['content'][0]['paragraph']['elements'].append({'inlineObjectElement':{'inlineObjectId':'picture'}})
 with pytest.raises(bd.DocumentReadError,match='document_nontext_evidence_unsupported'):bd.normalize_document(doc,DOCID)
