"""Execution readiness includes the account switch; presentation matches the host."""
import base64
import hashlib
import re

import pytest

from chatglance.account_limits import render_account_limits_html
from chatglance.reset_control import render_control_page
from test_reset_guard_rendering import profile


def report(account=True, business=True, guarded=False):
    return {
        'profile': 'Example', 'observed_at': '2027-01-15T08:00:00Z',
        'business_eligible': business,
        'automatic_allowed': account and business and not guarded,
        'controls': {'account_enabled': account},
        'checks': [{'key': 'used_percent', 'label': '当前使用率',
                    'state': 'pass' if business else 'fail', 'value': 97 if business else 70,
                    'rule': '使用率至少95%'}],
        'forecast': {'status': 'ok', 'probability_24h_percent': 28,
                     'source_updated_at': '2027-01-15T08:00:00Z'},
        'forecast_threshold': 70,
    }


@pytest.mark.parametrize('account,business,guarded,state', [
    (True, True, False, 'ready'),
    (False, True, False, 'paused'),
    (True, False, False, 'waiting'),
    (True, True, True, 'waiting'),
])
def test_overall_readiness_includes_the_account_switch(account, business, guarded, state):
    text = render_control_page(report(account, business, guarded), 'nonce', 'revision')
    assert f'data-automation="{state}"' in text
    assert 'data-check="global"' not in text
    assert f'data-check="account" data-state="{"pass" if account else "fail"}"' in text
    assert 'data-check="used_percent"' in text
    assert '本账号策略' not in text and '仅预演' not in text
    assert '自动用卡' in text and '总开关' not in text
    assert '一次计划刷新内' in text and '同一次刷新中判断并最多消费一次' in text
    assert '查看或刷新本小窗不会兑换' in text
    assert '下一次定时检查' not in text


def test_manual_pause_does_not_falsify_business_facts():
    text = render_control_page(report(account=False), 'nonce', 'revision')
    assert 'data-automation="paused"' in text
    assert 'data-check="used_percent" data-state="pass"' in text
    assert '业务条件已满足' in text


def test_unknown_evidence_is_rendered_as_a_failed_condition_not_a_human_check():
    value = report()
    value['checks'][0].update(state='unknown', value=None)
    text = render_control_page(value, 'nonce', 'revision')
    assert '待核对' not in text
    assert '未通过' in text
    assert '上次计划检查' in text


def test_card_contains_no_prediction_or_stale_execution_switch_claim():
    text = render_account_limits_html({'codex': [profile()], 'reset_control_path': '/_controls/'})
    assert '<aside class="reset-forecast' not in text
    assert '未来24小时重置预测' not in text and '仅预演' not in text
    assert '<summary>重置卡' in text and 'popovertarget=' in text
    assert '自动重置：' not in text
    assert 'font-size:var(--font-size-base,13px)' in text


def test_popup_uses_host_theme_and_compact_expandable_checks():
    text = render_control_page(report(), 'nonce', 'revision')
    assert '<table>' not in text
    assert '<details class="decision-row"' in text
    assert 'var(--color-primary' in text and 'font-size:inherit' in text
    assert 'font-size:24px' not in text
    assert 'parent.document' in text and '/static/' in text
    assert '<aside class="reset-forecast' in text


def test_theme_script_has_exact_csp_hash_without_broad_script_permission():
    from chatglance.reset_control import CONTROL_CSP
    text = render_control_page(report(), 'nonce', 'revision')
    scripts = re.findall(r'<script>(.*?)</script>', text, re.S)
    assert len(scripts) == 1
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
    assert f"script-src 'sha256-{digest}'" in CONTROL_CSP
    assert "script-src 'unsafe-inline'" not in CONTROL_CSP
    assert "form-action 'self'" in CONTROL_CSP
    assert "frame-ancestors 'self'" in CONTROL_CSP
    assert 'fetch(' not in scripts[0] and 'localStorage' not in scripts[0]
