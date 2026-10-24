"""Noninteractive bounded current Docs evidence using named saved credentials."""
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
import re
import stat
import sys
import time

from cli_tools_shared.bounded_read import run_bounded_read
from requests import RequestException
from .client import ClientError


class DocumentReadError(ClientError):
    def __init__(self,code,*,category='transient',status=None,retry_after_seconds=None):
        super().__init__(code)
        self.code=code;self.category=category;self.status=status;self.retry_after_seconds=retry_after_seconds


def retry_after(raw):
    if type(raw) is not str or len(raw)>200:return None
    raw=raw.strip()
    try:
        if re.fullmatch('[0-9]+',raw):value=float(raw)
        else:
            when=parsedate_to_datetime(raw)
            if when.tzinfo is None:return None
            value=max(0.,(when-datetime.now(timezone.utc)).total_seconds())
        return value if math.isfinite(value) else None
    except (ValueError,TypeError,OverflowError):return None


_QUOTA_SIGNALS={'rateLimitExceeded','userRateLimitExceeded','quotaExceeded','dailyLimitExceeded','RESOURCE_EXHAUSTED','usageLimits'}


def _error_body(response,deadline,limit=16384):
    raw=bytearray()
    try:
        for chunk in response.iter_content(2048):
            if time.monotonic()>=deadline or len(raw)+len(chunk)>limit:break
            raw.extend(chunk)
    except RequestException:return b''
    return bytes(raw)


def _quota_exceeded(raw):
    try:body=json.loads(raw.decode('utf-8'))
    except (ValueError,UnicodeError,RecursionError):return False
    if type(body) is not dict:return False
    error=body.get('error')
    if type(error) is not dict:return False
    values=[error.get('status')]
    for group in ('errors','details'):
        entries=error.get(group)
        if type(entries) is list:
            for entry in entries:
                if type(entry) is dict:values.extend((entry.get('reason'),entry.get('domain')))
    return any(value in _QUOTA_SIGNALS for value in values if type(value) is str)


def _office_file_rejected(raw):
    """True for the Docs API's permanent refusal of an uploaded Office file opened in Docs."""
    try:body=json.loads(raw.decode('utf-8'))
    except (ValueError,UnicodeError,RecursionError):return False
    error=body.get('error') if type(body) is dict else None
    return type(error) is dict and error.get('status')=='FAILED_PRECONDITION' and type(error.get('message')) is str and 'must not be an Office file' in error['message']


def _validate(profile,document_id,max_bytes,timeout_seconds):
    if type(profile) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,64}',profile):raise DocumentReadError('document_profile_invalid',category='invalid_request')
    if type(document_id) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,256}',document_id):raise DocumentReadError('document_id_invalid',category='invalid_request')
    if type(max_bytes) is not int or not 1024<=max_bytes<=32*1024*1024:raise DocumentReadError('document_byte_bound_invalid',category='invalid_request')
    if type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or not .75<timeout_seconds<=3600:raise DocumentReadError('document_timeout_invalid',category='invalid_request')


def read_document_bounded(config,document_id,*,timeout_seconds,max_bytes):
    profile=config.get_active_profile_name()
    _validate(profile,document_id,max_bytes,timeout_seconds)
    result=run_bounded_read([sys.executable,'-m','google_cli.bounded_documents',profile,document_id,str(max_bytes),str(timeout_seconds)],
        timeout_seconds=timeout_seconds-.75,max_stdout_bytes=max_bytes)
    try:
        envelope=json.loads(result.stdout.decode('utf-8'))
        if type(envelope) is not dict:raise ValueError()
        if set(envelope)=={'failure'}:
            if result.returncode!=1:raise ValueError()
            failure=envelope['failure']
            if type(failure) is not dict or set(failure)!={'code','category','status','retry_after_seconds'}:raise ValueError()
            if failure['category'] not in ('auth','access_denied','transient','rate_limit','upstream','invalid_data','invalid_request','unsupported'):raise ValueError()
            if type(failure['code']) is not str or not re.fullmatch('[a-z0-9_]{1,128}',failure['code']):raise ValueError()
            status=failure['status'];delay=failure['retry_after_seconds']
            if status is not None and (type(status) is not int or not 100<=status<=599):raise ValueError()
            if delay is not None and (type(delay) not in (int,float) or not math.isfinite(delay) or delay<0):raise ValueError()
            raise DocumentReadError(**failure)
        if result.returncode!=0 or set(envelope)!={'result'}:raise ValueError()
        document=envelope['result']
        if type(document) is not dict or document.get('documentId')!=document_id or type(document.get('content')) is not str or type(document.get('links')) is not list or document.get('suggestions_view_mode')!='SUGGESTIONS_INLINE' or type(document.get('suggestions_present')) is not bool or document.get('tabs_complete') is not True:raise ValueError()
        if any(type(link) is not str for link in document['links']):raise ValueError()
        return document
    except (ValueError,TypeError,KeyError,UnicodeError):raise DocumentReadError('document_worker_schema_changed',category='invalid_data') from None


def _token(config):
    try:
        fd=os.open(config.token_path_obj,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_size>65536:raise ValueError()
            raw=os.read(fd,65537)
            if len(raw)>65536:raise ValueError()
        finally:os.close(fd)
        token=json.loads(raw.decode('utf-8'))
        if type(token) is not dict:raise ValueError()
        from google.oauth2.credentials import Credentials
        return Credentials.from_authorized_user_info(token)
    except (OSError,ValueError,TypeError,UnicodeError):raise DocumentReadError('document_saved_credentials_unavailable',category='auth') from None


def normalize_document(document,document_id):
    if type(document) is not dict or document.get('documentId')!=document_id or type(document.get('tabs')) is not list or not document['tabs']:
        raise DocumentReadError('document_identity_or_tabs_changed',category='invalid_data')
    from .commands.docs import _extract_all_text
    if document.get('suggestionsViewMode')!='SUGGESTIONS_INLINE':raise DocumentReadError('document_suggestions_view_changed',category='invalid_data')
    tabs=list(document['tabs'])
    while tabs:
        tab=tabs.pop()
        if type(tab) is not dict or type(tab.get('documentTab')) is not dict or type(tab['documentTab'].get('body')) is not dict or type(tab['documentTab']['body'].get('content')) is not list:raise DocumentReadError('document_tab_structure_unsupported',category='invalid_data')
        children=tab.get('childTabs',[])
        if type(children) is not list:raise DocumentReadError('document_tab_structure_unsupported',category='invalid_data')
        tabs.extend(children)
    links=set();pending=[(document,0)];suggestions=False
    while pending:
        item,depth=pending.pop()
        if depth>64:raise DocumentReadError('document_structure_exceeds_bound',category='invalid_data')
        if type(item) is dict:
            suggestions=suggestions or any((key.startswith('suggested') or 'SuggestionIds' in key) and bool(value) for key,value in item.items())
            if any(key in item for key in ('inlineObjectElement','equation','richLink','person')):raise DocumentReadError('document_nontext_evidence_unsupported',category='invalid_data')
            if 'textRun' in item and type(item['textRun']) is not dict:raise DocumentReadError('document_text_schema_changed',category='invalid_data')
            run=item.get('textRun')
            if type(run) is dict:
                if type(run.get('content')) is not str:raise DocumentReadError('document_text_schema_changed',category='invalid_data')
                style=run.get('textStyle',{});link=style.get('link',{}) if type(style) is dict else {}
                url=link.get('url') if type(link) is dict else None
                if url is not None:
                    if type(url) is not str or len(url.encode())>4096:raise DocumentReadError('document_link_schema_changed',category='invalid_data')
                    links.add(url)
            pending.extend((v,depth+1) for v in item.values() if type(v) in (dict,list))
        elif type(item) is list:pending.extend((v,depth+1) for v in item if type(v) in (dict,list))
    title=document.get('title')
    if type(title) is not str or not title:raise DocumentReadError('document_title_missing',category='invalid_data')
    return {'documentId':document_id,'title':title,'content':_extract_all_text(document),'links':sorted(links),
            'observed_at':datetime.now(timezone.utc).isoformat(),'tabs_complete':True,'suggestions_view_mode':'SUGGESTIONS_INLINE','suggestions_present':suggestions}


def _worker(profile,document_id,max_bytes,timeout_seconds):
    _validate(profile,document_id,max_bytes,timeout_seconds)
    from .config import Config
    from google.auth.transport.requests import AuthorizedSession
    from google.auth.exceptions import RefreshError
    from requests import RequestException
    deadline=time.monotonic()+timeout_seconds
    credentials=_token(Config(profile=profile))
    try:
        with AuthorizedSession(credentials,max_refresh_attempts=1,refresh_timeout=timeout_seconds) as session:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise DocumentReadError('document_read_deadline_exceeded')
            response=session.get('https://docs.googleapis.com/v1/documents/'+document_id,
                params={'includeTabsContent':'true','suggestionsViewMode':'SUGGESTIONS_INLINE'},
                stream=True,allow_redirects=False,timeout=remaining,max_allowed_time=remaining)
            try:
                status=response.status_code;delay=retry_after(response.headers.get('Retry-After'))
                if status==400 and _office_file_rejected(_error_body(response,deadline)):
                    raise DocumentReadError('document_office_file_unsupported',category='unsupported',status=status,retry_after_seconds=delay)
                if status!=200:
                    limited=status==403 and _quota_exceeded(_error_body(response,deadline))
                    raise DocumentReadError('document_http_'+str(status),category='auth' if status==401 else 'rate_limit' if status==429 or limited else 'access_denied' if status==403 else 'transient' if status>=500 else 'upstream',status=status,retry_after_seconds=delay)
                raw=bytearray()
                for chunk in response.iter_content(4096):
                    if time.monotonic()>=deadline:raise DocumentReadError('document_read_deadline_exceeded')
                    if len(raw)+len(chunk)>max_bytes:raise DocumentReadError('document_response_exceeds_bound',category='invalid_data')
                    raw.extend(chunk)
            finally:response.close()
        try:document=json.loads(raw.decode('utf-8'))
        except (ValueError,UnicodeError,RecursionError):raise DocumentReadError('document_response_schema_changed',category='invalid_data') from None
        result=normalize_document(document,document_id)
        if len(json.dumps({'result':result},ensure_ascii=True).encode())>max_bytes:raise DocumentReadError('document_evidence_exceeds_bound',category='invalid_data')
        return result
    except RefreshError:raise DocumentReadError('document_credential_refresh_failed',category='auth') from None
    except RequestException:raise DocumentReadError('document_transport_failed') from None


if __name__=='__main__':
    try:
        profile,document_id,bound,timeout=sys.argv[1:]
        result=_worker(profile,document_id,int(bound),float(timeout))
        print(json.dumps({'result':result},ensure_ascii=True))
    except DocumentReadError as error:
        print(json.dumps({'failure':{key:getattr(error,key) for key in ('code','category','status','retry_after_seconds')}}))
        raise SystemExit(1)
    except Exception:
        print(json.dumps({'failure':{'code':'document_worker_failed','category':'transient','status':None,'retry_after_seconds':None}}))
        raise SystemExit(1)
