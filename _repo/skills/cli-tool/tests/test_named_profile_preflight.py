"""Exercise the actual shell preflight with a hermetic service executable."""
import json,os,subprocess,sys
from pathlib import Path
import pytest

@pytest.mark.parametrize('requested,returned,success',[('clipper','clipper',True),('clipper','wrong',False),('','default',True)])
def test_preflight_propagates_exact_profile_without_activation(tmp_path,requested,returned,success):
    skill=Path(__file__).resolve().parents[1]
    trace=tmp_path/'trace.jsonl'
    cli=tmp_path/'demo'
    payload={'profiles':[{'name':returned,'auth_type':'browser_session','active':returned=='default','authenticated':True,'credential_types':{'browser_session':{'credentials_saved':True,'authenticated':True}}}]}
    cli.write_text('#!'+sys.executable+'\nimport json,sys\nfrom pathlib import Path\n'+f'with Path({str(trace)!r}).open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'+f'print(json.dumps({payload!r}) if sys.argv[1:3]==["auth","status"] else " auth status ")\n')
    cli.chmod(0o700)
    uv=tmp_path/'uv'
    uv.write_text('#!'+sys.executable+'\nimport os,sys\nos.execv(sys.executable,[sys.executable]+sys.argv[sys.argv.index("python3")+1:])\n');uv.chmod(0o700)
    # Run the preflight function directly from its canonical shell source.
    source=(skill/'scripts/test-cli-tool.sh').read_text().split('CLI_NAME=""\nCOMMAND=""')[0]
    environment={**os.environ,'PATH':str(tmp_path)+os.pathsep+os.environ['PATH'],'SKILL_DIR':str(skill),'SKILL_UV_ENV':str(tmp_path/'venv'),'CLI_NAME':'demo','CLI_EXECUTABLE':str(cli),'CLI_PROFILE':requested,'COMMAND':''}
    result=subprocess.run(['/bin/bash','-c',source+'\nrun_auth_status_schema_preflight\n'],env=environment,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['status']==('passed' if success else 'failed')
    calls=[json.loads(line) for line in trace.read_text().splitlines()]
    assert calls[-1]==['auth','status']+(['--profile',requested] if requested else [])
    assert all('select' not in args and 'login' not in args for args in calls)
