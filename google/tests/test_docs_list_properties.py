import json
from types import SimpleNamespace
import pytest
from typer.testing import CliRunner
from google_cli.commands import docs

@pytest.fixture
def drive(monkeypatch):
    rows=[{'id':'document_TEST','webViewLink':'https://docs.google.com/document/d/document_TEST/edit','name':'A document','owner':{'name':'Creator'}}]
    response=SimpleNamespace(execute=lambda:{'files':rows})
    service=SimpleNamespace(files=lambda:SimpleNamespace(list=lambda **kwargs:response))
    monkeypatch.setattr(docs,'get_client',lambda **kwargs:SimpleNamespace(get_drive_service=lambda:service))

@pytest.mark.parametrize('args',[['--properties','webViewLink,id'],['--properties','webViewLink','--properties','id'],['--properties',' webViewLink , id ']])
def test_real_option_parsing_preserves_comma_and_repeated_properties(drive,args):
    result=CliRunner().invoke(docs.app,['list','--limit','1','--profile','adbertram',*args])
    assert result.exit_code==0,result.output
    assert json.loads(result.stdout)==[{'webViewLink':'https://docs.google.com/document/d/document_TEST/edit','id':'document_TEST'}]

def test_canonical_helper_preserves_nested_requested_keys(drive):
    result=CliRunner().invoke(docs.app,['list','--properties','owner.name,id','--profile','adbertram'])
    assert result.exit_code==0 and json.loads(result.stdout)==[{'owner.name':'Creator','id':'document_TEST'}]

def test_table_uses_normalized_requested_columns(drive,monkeypatch):
    captured=[];monkeypatch.setattr(docs,'print_table',lambda rows,cols,headers:captured.append((rows,cols,headers)))
    result=CliRunner().invoke(docs.app,['list','--table','--properties','webViewLink,id','--profile','adbertram'])
    assert result.exit_code==0,result.output
    assert captured[0][1]==['webViewLink','id'] and set(captured[0][0][0])=={'webViewLink','id'}
