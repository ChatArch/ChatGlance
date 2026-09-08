import importlib
import json
from click.testing import CliRunner


def test_collector_connects_profile_policy_without_model_calls(tmp_path, monkeypatch):
    m=importlib.import_module('chatglance.codex_collector')
    calls=[]
    def scan(profile, **kwargs):
        calls.append((profile, kwargs))
        return {'profile':profile,'status':'ok','token_service':'Codex','windows':[],'reset_history':[], 'reset_credits':{'available_count':2}}
    monkeypatch.setattr(m,'scan_profile',scan)
    result=m.collect_account_limits(profiles=['alpha','beta'],output_path=tmp_path/'out.json',reset_policies='{"alpha":{"enabled":true}}',no_public_reset=True,home=tmp_path)
    assert result['codex'][0]['reset_credits']['available_count']==2
    assert len(calls)==2 and calls[0][1]['policy'].enabled
    assert not calls[1][1]['policy'].enabled
    assert all(c[1]['execute'] is False for c in calls)
    assert json.loads((tmp_path/'out.json').read_text())['codex'] == result['codex']


def test_collect_cli_defaults_cannot_execute(tmp_path, monkeypatch):
    from chatglance.cli import main
    m=importlib.import_module('chatglance.codex_collector')
    monkeypatch.setenv('CHATARCH_HOME',str(tmp_path))
    calls=[]
    monkeypatch.setattr(m,'collect_account_limits',lambda **kw:calls.append(kw) or {'codex':[],'refresh_status':{'failed_count':0}})
    r=CliRunner().invoke(main,['account-limits','collect','--profiles','work','--output',str(tmp_path/'out.json'),'--no-public-reset'])
    assert r.exit_code==0, r.output
    assert calls[0]['execute_resets'] in (False,None)


def test_explicit_no_execute_beats_enabled_environment(tmp_path, monkeypatch):
    m=importlib.import_module('chatglance.codex_collector')
    monkeypatch.setenv('CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE','1')
    calls=[]
    monkeypatch.setattr(m,'scan_profile',lambda p,**kw:calls.append(kw) or {'profile':p,'status':'ok','windows':[],'reset_history':[]})
    m.collect_account_limits(profiles='work',output_path=tmp_path/'out.json',execute_resets=False,no_public_reset=True,home=tmp_path)
    assert calls[0]['execute'] is False
