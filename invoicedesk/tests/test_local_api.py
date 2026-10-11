"""End-to-end command tests against an isolated, in-memory InvoiceDesk server."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest
from typer.testing import CliRunner
from invoicedesk_cli.client import InvoicedeskClient
from invoicedesk_cli.commands import customer, invoice, export

@pytest.fixture
def service():
    server = Path(__file__).resolve().parents[3] / 'InvoiceDesk' / 'server.js'
    assert server.is_file(), f'InvoiceDesk server missing: {server}'
    script = '''const {createApp}=await import(process.argv[1]);
const app=createApp({dbPath:':memory:',apiToken:'isolated-test-token'});
app.server.listen(0,'127.0.0.1',()=>console.log(JSON.stringify({port:app.server.address().port})));
process.on('SIGTERM',()=>app.close().then(()=>process.exit(0)));'''
    process = subprocess.Popen(['node','--input-type=module','-e',script,server.as_uri()],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        line=process.stdout.readline()
        assert line, 'Isolated InvoiceDesk server failed to start'
        port=json.loads(line)['port']
        config=SimpleNamespace(api_key='isolated-test-token',base_url=f'http://127.0.0.1:{port}',default_terms='Fixture payment instructions')
        yield InvoicedeskClient(config=config), config
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_command_parity_real_http(service,monkeypatch,tmp_path):
    client,config=service
    for module in [customer,invoice,export]:
        monkeypatch.setattr(module,'get_client',lambda:client)
    monkeypatch.setattr(invoice,'get_config',lambda:config)
    runner=CliRunner()
    def run(module,*args):
        result=runner.invoke(module.app,list(args[1:] if module is export else args))
        assert result.exit_code==0, result.output
        return json.loads(result.stdout) if result.stdout else None
    c=run(customer,'create','-e','buyer@example.com','-f','Ada','-l','Buyer','-o','Fixture Corp')
    run(customer,'update',c['id'],'-f','Augusta')
    assert run(customer,'get',c['id'])['fname']=='Augusta'
    assert run(customer,'find','buyer@example.com')['id']==c['id']
    created=run(invoice,'create','-c',c['id'],'-d','Article','-a','100','-q','2')
    raw=run(invoice,'get',created['id'])
    assert raw['amount']['amount']=='200.00'
    assert raw['terms']=='Fixture payment instructions'
    run(invoice,'update',created['id'],'-l',f"{raw['lines'][0]['lineid']}=125",'-n','Updated')
    run(invoice,'mark-sent',created['id'],'-F')
    run(invoice,'mark-paid',created['id'],'-a','100')
    assert run(invoice,'get',created['id'])['outstanding']['amount']=='150.00'
    run(invoice,'mark-paid',created['id'],'-a','150')
    assert run(invoice,'get',created['id'])['v3_status']=='paid'
    pdf=tmp_path/'invoice.pdf'
    run(invoice,'download',created['id'],'-o',str(pdf))
    assert pdf.read_bytes().startswith(b'%PDF')
    attached=run(invoice,'create','-c',c['id'],'-d','Attachment','-a','10','--no-terms','-f',str(pdf))
    raw=run(invoice,'get',attached['id'])
    assert raw['terms']=='' and raw['attachments'][0]['jwt']
    legacy_c={'id':77,'userid':77,'fname':'Legacy','lname':'Buyer','organization':'Legacy Org','email':'legacy@example.com','currency_code':'USD'}
    legacy_i={'id':88,'invoiceid':88,'invoice_number':'OLD-88','customerid':77,'currency_code':'USD','amount':{'amount':'20.00','code':'USD'},'paid':{'amount':'0.00','code':'USD'},'outstanding':{'amount':'20.00','code':'USD'},'create_date':'2026-01-01','due_date':'2026-01-31','vis_state':0,'v3_status':'sent','status':2,'terms':'Old terms','lines':[{'lineid':7,'name':'Legacy line','qty':'1','type':0,'unit_cost':{'amount':'20.00','code':'USD'},'amount':{'amount':'20.00','code':'USD'}}]}
    for kind,record in [('clients',legacy_c),('invoices',legacy_i)]:
        client._make_request('POST','/api/import/freshbooks',data={'account_id':'fixture','kind':kind,'records':[{'source_id':str(record['id']),'record':record}]})
    run(invoice,'update','88','-l','7=30')
    run(invoice,'mark-paid','88','-a','10')
    assert run(invoice,'get','88')['outstanding']['amount']=='20.00'
    run(customer,'update','77','-o','Changed Legacy Org')
    assert run(customer,'get','77')['organization']=='Changed Legacy Org'
    output=tmp_path/'export'
    assert run(export,'run','-o',str(output))['status']=='complete'
    run(invoice,'update',attached['id'],'-n','Changed before resume')
    assert run(export,'run','-o',str(output),'--resume')['status']=='complete'
    run(invoice,'delete',attached['id'],'-F')
    assert run(invoice,'get',attached['id'])['vis_state']==1


def test_list_limit_over_one_page_has_no_duplicates(service,monkeypatch):
    client,_=service
    expected=[]
    for index in range(155):
        row=client.create_client(f"buyer{index}@example.com", "Buyer", str(index), f"Fixture {index:03}")
        expected.append(row["id"])
    monkeypatch.setattr(customer,"get_client",lambda:client)
    result=CliRunner().invoke(customer.app,["list","--limit","150"])
    assert result.exit_code==0,result.output
    rows=json.loads(result.stdout)
    identifiers=[row["id"] for row in rows]
    assert len(identifiers)==150
    assert len(set(identifiers))==150
    assert identifiers==expected[:150]

def test_unpaid_and_overdue_include_source_statuses_exclude_inactive(service,monkeypatch):
    client,_=service
    legacy_c={'id':77,'userid':77,'fname':'Legacy','lname':'Buyer','organization':'Legacy Org','email':'legacy@example.com','currency_code':'USD'}
    client._make_request('POST','/api/import/freshbooks',data={'account_id':'fixture','kind':'clients','records':[{'source_id':'77','record':legacy_c}]})
    cases=[('overdue',0,'2026-01-31'),('partial',0,'2026-01-31'),('sent',0,'2099-01-31'),('viewed',0,'2026-01-31'),('draft',0,'2026-01-31'),('void',0,'2026-01-31'),('paid',0,'2026-01-31'),('overdue',1,'2026-01-31'),('overdue',2,'2026-01-31')]
    for index,(status,visibility,due) in enumerate(cases,100):
        paid='20.00' if status=='paid' else '5.00' if status=='partial' else '0.00'
        balance='0.00' if status=='paid' else '15.00' if status=='partial' else '20.00'
        raw={'id':index,'invoiceid':index,'invoice_number':f'OLD-{index}','customerid':77,'currency_code':'USD','amount':{'amount':'20.00','code':'USD'},'paid':{'amount':paid,'code':'USD'},'outstanding':{'amount':balance,'code':'USD'},'create_date':'2026-01-01','due_date':due,'vis_state':visibility,'v3_status':status,'status':4 if status=='paid' else 8 if status=='partial' else 2,'lines':[{'lineid':7,'name':'Legacy line','qty':'1','type':0,'unit_cost':{'amount':'20.00','code':'USD'},'amount':{'amount':'20.00','code':'USD'}}]}
        client._make_request('POST','/api/import/freshbooks',data={'account_id':'fixture','kind':'invoices','records':[{'source_id':str(index),'record':raw}]})
    monkeypatch.setattr(invoice,'get_client',lambda:client)
    runner=CliRunner()
    for args,expected in [(['--unpaid'],{100,101,102,103}),(['--status','overdue'],{100,101,103}),([],{100,101,102,103,104,105,106})]:
        result=runner.invoke(invoice.app,['list',*args])
        assert result.exit_code==0,result.output
        assert {int(row['id']) for row in json.loads(result.stdout)}==expected
