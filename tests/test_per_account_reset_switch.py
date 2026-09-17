"""There is one durable switch per account, never a hidden global gate."""
import json

import pytest

from chatenv import EnvStore, get_paths
from chatglance.config import ChatGlanceConfig, collection_settings
from chatglance import codex_collector as collector
from test_reset_control import control as control, request, form, POLICIES

LEGACY = 'CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE'


def test_provider_has_no_persistent_global_execution_switch(tmp_path):
    assert not hasattr(ChatGlanceConfig, LEGACY)
    assert 'execute_resets' not in collection_settings(home=tmp_path)


def test_unmigrated_legacy_state_fails_closed_instead_of_enabling_accounts(tmp_path):
    EnvStore(get_paths(tmp_path).envs_dir).save_active(ChatGlanceConfig, {
        LEGACY: 'false', POLICIES: json.dumps({'one': {'enabled': True}}),
    })
    with pytest.raises(ValueError, match='migrat'):
        collection_settings(home=tmp_path)


@pytest.mark.parametrize('override,mode', [(None, True), (False, False)])
def test_normal_scan_uses_independent_account_flags_and_explicit_preview_remains_safe(tmp_path, monkeypatch, override, mode):
    calls = []
    def payload(name, timeout, **kw):
        calls.append((name, kw['execute'], kw['policy'].enabled))
        return {'profile': name, 'status': 'ok', 'windows': [], 'reset_history': []}
    monkeypatch.setattr(collector, 'profile_payload', payload)
    result = collector.collect_account_limits(
        profiles=['one', 'two'], output_path=tmp_path/'scan.json', home=tmp_path,
        reset_policies=json.dumps({'one': {'enabled': True}, 'two': {'enabled': False}}),
        execute_resets=override, no_public_reset=True,
    )
    assert calls == [('one', mode, True), ('two', mode, False)]
    assert len(result['codex']) == 2


def test_dialog_contains_one_account_gate_and_no_global_action(control):
    server, _, base = control
    server.control_app.diagnose = lambda row, policy, **kw: {
        'profile':row['profile'], 'business_eligible':True,
        'automatic_allowed': policy.enabled and kw['execute_enabled'],
        'controls': {'account_enabled':policy.enabled}, 'checks': [],
    }
    code, page, _ = request(base)
    assert code == 200 and 'data-automation="ready"' in page
    assert page.count('name="scope"') == 1
    assert 'data-check="global"' not in page and '总开关' not in page
    assert '自动用卡' in page
    assert request(base, '/toggle', values=form(base, scope='global', enabled='true', confirm='enable'))[0] == 400
    assert request(base, '/toggle', values=form(base, enabled='false'))[0] == 303
    assert 'data-automation="paused"' in request(base)[1]


def test_another_account_change_does_not_invalidate_this_account_switch(control):
    _, store, base = control
    pending = form(base)
    values = store.load_active(ChatGlanceConfig)
    policies = json.loads(values[POLICIES]);policies['other'] = {'enabled':True,'threshold_percent':99}
    values[POLICIES] = json.dumps(policies);store.save_active(ChatGlanceConfig, values)
    assert request(base, '/toggle', values=pending)[0] == 303
    saved=json.loads(store.load_active(ChatGlanceConfig)[POLICIES])
    assert saved['demo']['enabled'] is False
    assert saved['other'] == policies['other']
