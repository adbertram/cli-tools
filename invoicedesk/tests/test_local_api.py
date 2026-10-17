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


def import_original(client, data):
    import base64
    import hashlib
    client._make_request('POST', '/api/import/freshbooks-file', data={
        'path': 'fixture/document.txt', 'mime': 'text/plain',
        'sha256': hashlib.sha256(data).hexdigest(), 'total_parts': 1,
        'part': 0, 'data': base64.b64encode(data).decode(),
    })


@pytest.mark.parametrize('number', ['folder/../../victim', r'folder\..\victim', 'unsafe\x01number', 'unsafe\x7fnumber'])
def test_download_rejects_unsafe_default_filename(service, monkeypatch, tmp_path, number):
    client, _ = service
    customer_row = client.create_client('fixture@example.com', 'Fixture', 'Buyer', 'Fixture')
    created = client.create_invoice(customer_row['id'], [{'name': 'Fixture', 'qty': '1', 'unit_cost': {'amount': '20.00', 'code': 'USD'}}])
    raw = client.get_invoice(created['id'])
    imported_customer = {'id':77, 'userid':77, 'fname':'Fixture', 'lname':'Buyer', 'email':'legacy@example.com', 'currency_code':'USD'}
    client._make_request('POST', '/api/import/freshbooks', data={'account_id':'fixture', 'kind':'clients', 'records':[{'source_id':'77', 'record': imported_customer}]})
    raw.update(id=88, invoiceid=88, customerid=77, invoice_number=number)
    client._make_request('POST', '/api/import/freshbooks', data={'account_id': 'fixture', 'kind': 'invoices', 'records': [{'source_id': '88', 'record': raw}]})
    downloads = tmp_path / 'downloads'
    downloads.mkdir()
    victim = tmp_path / 'victim.pdf'
    victim.write_bytes(b'KEEP THIS FILE')
    monkeypatch.chdir(downloads)
    monkeypatch.setattr(invoice, 'get_client', lambda: client)
    result = CliRunner().invoke(invoice.app, ['download', '88'])
    assert result.exit_code == 1, result.output
    assert 'Unsafe invoice number' in result.output
    assert victim.read_bytes() == b'KEEP THIS FILE'
    assert list(downloads.iterdir()) == []


def test_download_explicit_output_replaces_completed_pdf(service, monkeypatch, tmp_path):
    client, _ = service
    customer_row = client.create_client('fixture@example.com', 'Fixture', 'Buyer', 'Fixture')
    created = client.create_invoice(customer_row['id'], [{'name': 'Fixture', 'qty': '1', 'unit_cost': {'amount': '20.00', 'code': 'USD'}}])
    monkeypatch.setattr(invoice, 'get_client', lambda: client)
    destination = tmp_path / 'invoice.pdf'
    runner = CliRunner()
    result = runner.invoke(invoice.app, ['download', created['id'], '-o', str(destination)])
    assert result.exit_code == 0, result.output
    saved = destination.read_bytes()
    assert saved.startswith(b'%PDF')
    client.update_invoice(created['id'], notes='Changed before replacement')
    result = runner.invoke(invoice.app, ['download', created['id'], '-o', str(destination)])
    assert result.exit_code == 0, result.output
    assert destination.read_bytes().startswith(b'%PDF')
    assert destination.read_bytes() != saved
    assert list(tmp_path.iterdir()) == [destination]


def test_resume_rejects_other_deployment_without_changing_archive(service, tmp_path):
    from invoicedesk_cli.exporter import Exporter
    from cli_tools_shared.exceptions import ClientError
    first, _ = service
    import_original(first, b'Service A document')
    output = tmp_path / 'archive'
    assert Exporter(first, output).run()['status'] == 'complete'
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
    # Reuse the same fixture implementation to start a second real HTTP server.
    second_fixture = service_fixture_factory()
    try:
        second, _ = next(second_fixture)
        import_original(second, b'Service B document')
        with pytest.raises(ClientError, match='source identity'):
            Exporter(second, output, resume=True)
    finally:
        second_fixture.close()
    assert {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()} == before


def service_fixture_factory():
    return service.__wrapped__()


def test_resume_rejects_legacy_manifest_without_changing_archive(service, tmp_path):
    from invoicedesk_cli.exporter import Exporter
    from cli_tools_shared.exceptions import ClientError
    client, _ = service
    output = tmp_path / 'archive'
    Exporter(client, output).run()
    manifest_path = output / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    del manifest['source_identity']
    manifest_path.write_text(json.dumps(manifest))
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
    with pytest.raises(ClientError, match='source identity'):
        Exporter(client, output, resume=True)
    assert {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()} == before


def test_resume_checks_cached_original_against_current_source_inventory(service, tmp_path):
    import hashlib
    from invoicedesk_cli.exporter import Exporter
    client, _ = service
    import_original(client, b'Service A document')
    output = tmp_path / 'archive'
    assert Exporter(client, output).run()['status'] == 'complete'
    original = output / 'originals/fixture/document.txt'
    original.write_bytes(b'Service B document')
    manifest_path = output / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['files']['originals/fixture/document.txt']['sha256'] = hashlib.sha256(original.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    assert Exporter(client, output, resume=True).run()['status'] == 'complete'
    assert original.read_bytes() == b'Service A document'


@pytest.mark.parametrize('failure_method', ['replace', 'fsync'])
def test_download_default_existing_symlink_and_failed_explicit_write(service, monkeypatch, tmp_path, failure_method):
    client, _ = service
    customer_row = client.create_client('fixture@example.com', 'Fixture', 'Buyer', 'Fixture')
    created = client.create_invoice(customer_row['id'], [{'name': 'Fixture', 'qty': '1', 'unit_cost': {'amount': '20.00', 'code': 'USD'}}])
    monkeypatch.setattr(invoice, 'get_client', lambda: client)
    monkeypatch.chdir(tmp_path)
    default = tmp_path / f"invoice_{client.get_invoice(created['id'])['invoice_number']}.pdf"
    default.write_bytes(b'KEEP DEFAULT')
    runner = CliRunner()
    result = runner.invoke(invoice.app, ['download', created['id']])
    assert result.exit_code == 1 and 'already exists' in result.output
    assert default.read_bytes() == b'KEEP DEFAULT'
    destination = tmp_path / 'explicit.pdf'
    destination.write_bytes(b'KEEP EXPLICIT')
    symlink = tmp_path / 'symlink.pdf'
    symlink.symlink_to(destination)
    result = runner.invoke(invoice.app, ['download', created['id'], '-o', str(symlink)])
    assert result.exit_code == 1 and 'symbolic link' in result.output
    assert destination.read_bytes() == b'KEEP EXPLICIT'
    def fail_publish(*args):
        raise OSError('Fixture publication failure')
    monkeypatch.setattr(invoice.os, failure_method, fail_publish)
    result = runner.invoke(invoice.app, ['download', created['id'], '-o', str(destination)])
    assert result.exit_code == 1 and 'Fixture publication failure' in result.output
    assert destination.read_bytes() == b'KEEP EXPLICIT'
    assert not list(tmp_path.glob('.invoice-*'))


@pytest.mark.parametrize('bad_manifest', [[], {'files': []}, {'files': {'invoicedesk.json': []}}, {'files': {'invoicedesk.json': {'bytes': '10', 'sha256': 'x'}}}])
def test_resume_malformed_manifest_preserves_archive(service, tmp_path, bad_manifest):
    from invoicedesk_cli.exporter import Exporter
    from cli_tools_shared.exceptions import ClientError
    client, _ = service
    output = tmp_path / 'archive'
    Exporter(client, output).run()
    path = output / 'manifest.json'
    if isinstance(bad_manifest, dict):
        manifest = json.loads(path.read_text())
        manifest.update(bad_manifest)
    else:
        manifest = bad_manifest
    path.write_text(json.dumps(manifest))
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
    with pytest.raises(ClientError, match='Invalid archive manifest'):
        Exporter(client, output, resume=True)
    assert {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()} == before


def test_export_malformed_snapshot_does_not_create_archive(tmp_path):
    from invoicedesk_cli.exporter import Exporter
    from cli_tools_shared.exceptions import ClientError
    class InvalidSource:
        def _make_request(self, *args):
            return []
    output = tmp_path / 'archive'
    with pytest.raises(ClientError, match='Invalid export response'):
        Exporter(InvalidSource(), output)
    assert not output.exists()
