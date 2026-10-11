"""Request-contract and failure-safety checks without remote mutations."""
from types import SimpleNamespace
import pytest
from invoicedesk_cli.client import InvoicedeskClient
from cli_tools_shared.exceptions import ClientError

@pytest.fixture
def client():
    return InvoicedeskClient(config=SimpleNamespace(api_key='fixture-token',base_url='https://example.invalid'),base_delay=0,jitter=0)

def response(payload=None,status=200,content=b'',headers=None):
    return SimpleNamespace(status_code=status,ok=status<400,text='fixture error',json=lambda:payload,content=content,headers=headers or {})

def test_mutation_timeout_never_retries(client,monkeypatch):
    calls=[]
    def fail(*args,**kwargs):
        calls.append(args)
        from requests import Timeout
        raise Timeout('fixture')
    monkeypatch.setattr('invoicedesk_cli.client.requests.request',fail)
    with pytest.raises(ClientError,match='Request failed'):
        client.mark_invoice_paid('88','2026-10-01','10')
    assert len(calls)==1

def test_reads_retry_transient_response(client,monkeypatch):
    replies=iter([response(status=503),response({'response':{'result':{'invoice':{'id':88}}}})])
    monkeypatch.setattr('invoicedesk_cli.client.requests.request',lambda *a,**k:next(replies))
    assert client.get_invoice('88')=={'id':88}

def test_list_limit_goes_to_server(client,monkeypatch):
    seen=[]
    def fetch(method,url,**kwargs):
        seen.append(kwargs['params'])
        return response({'response':{'result':{'clients':[{'id':1}],'pages':1}}})
    monkeypatch.setattr('invoicedesk_cli.client.requests.request',fetch)
    assert client.get_clients(max_records=1)==[{'id':1}]
    assert ('per_page',1) in seen[0]

def test_missing_list_collection_fails_explicitly(client,monkeypatch):
    monkeypatch.setattr('invoicedesk_cli.client.requests.request',lambda *a,**k:response({'response':{'result':{}}}))
    with pytest.raises(ClientError,match='lacks clients collection'):
        client.get_clients()

def test_pdf_validates_bytes_not_only_mime(client,monkeypatch):
    monkeypatch.setattr('invoicedesk_cli.client.requests.request',lambda *a,**k:response(content=b'not pdf',headers={'Content-Type':'application/pdf'}))
    with pytest.raises(ClientError,match='invalid PDF'):
        client.download_invoice_pdf('88')

def test_empty_terms_explicitly_preserved(client,monkeypatch):
    calls=[]
    monkeypatch.setattr(client,'_make_request',lambda method,path,**kwargs:(calls.append(kwargs) or {'response':{'result':{'invoice':{'id':1}}}}))
    client.create_invoice('77',[],terms='')
    assert calls[0]['data']['invoice']['terms']==''

def test_mark_sent_only_records_external_delivery(client,monkeypatch):
    calls=[]
    monkeypatch.setattr(client,'_make_request',lambda method,path,**kwargs:(calls.append((method,path,kwargs)) or {'response':{'result':{'invoice':{'id':'native:1'}}}}))
    assert client.mark_invoice_sent('native:1')['id']=='native:1'
    assert calls==[('POST','/api/compat/invoices/native%3A1/mark-sent',{'data':{}})]

def test_export_resume_refreshes_mutable_pdf(tmp_path):
    from invoicedesk_cli.exporter import Exporter
    class API:
        version=1
        def _make_request(self,method,path,**kwargs):
            if path=='/api/compat/export':
                return {'archive_files':[],'invoices':[{'id':'native:1','notes':str(self.version)}]}
            return response(content=f'%PDF-{self.version}'.encode())
    api=API()
    output=tmp_path/'export'
    assert Exporter(api,output).run()['status']=='complete'
    api.version=2
    assert Exporter(api,output,resume=True).run()['status']=='complete'
    assert (output/'invoices/native:1.pdf').read_bytes()==b'%PDF-2'

def test_email_lookup_ignores_substrings_and_searches_later_pages(client,monkeypatch):
    seen=[]
    def fetch(method,url,**kwargs):
        params=dict(kwargs['params'])
        seen.append(params)
        rows=[{'id':1,'email':'extra@example.com'}] if params['page']==1 else [{'id':2,'email':'A@example.com'}]
        return response({'response':{'result':{'clients':rows,'pages':2}}})
    monkeypatch.setattr('invoicedesk_cli.client.requests.request',fetch)
    assert client.get_client_by_email('a@example.com')['id']==2
    assert [row['page'] for row in seen]==[1,2]
    assert all(row['search[email]']=='a@example.com' for row in seen)

def test_email_lookup_returns_none_for_only_substring(client,monkeypatch):
    monkeypatch.setattr(client,'get_clients',lambda **kwargs:[{'email':'extra@example.com'}])
    assert client.get_client_by_email('a@example.com') is None

def test_read_retry_does_not_mask_final_transport_failure(client,monkeypatch):
    calls=[]
    def fetch(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:
            return response(status=503)
        from requests import Timeout
        raise Timeout('final transport failure')
    monkeypatch.setattr('invoicedesk_cli.client.requests.request',fetch)
    with pytest.raises(ClientError,match='final transport failure'):
        client.get_invoice('88')

def test_empty_forbidden_response_does_not_retry(client,monkeypatch):
    calls=[]
    def fetch(*args,**kwargs):
        calls.append(1)
        return response(status=403,content=b'')
    monkeypatch.setattr('invoicedesk_cli.client.requests.request',fetch)
    with pytest.raises(ClientError,match='403'):
        client.get_invoice('88')
    assert len(calls)==1
