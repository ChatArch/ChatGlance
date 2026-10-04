from __future__ import annotations

import copy
import math
from concurrent.futures import ThreadPoolExecutor

import pytest

import chatglance

NOW = 1800000000.0


def module():
    from chatglance import codex_resets
    return codex_resets


def usage(used=95, seconds=86401, **extras):
    return {'rate_limit': {'primary_window': {'used_percent': used, 'reset_after_seconds': seconds, 'reset_at': NOW + seconds, 'limit_window_seconds': 604800}}, **extras}


def credits(count=2):
    return {'available_count': count, 'credits': [{'status': 'available', 'expires_at': '2030-01-01T00:00:00Z'} for _ in range(count)]}


def test_threshold_and_time_are_conjunctive():
    m = module()
    assert m.evaluate_policy(usage(), credits(), m.ResetPolicy(enabled=True), now=NOW)['eligible']
    assert not m.evaluate_policy(usage(94.99), credits(), m.ResetPolicy(enabled=True), now=NOW)['eligible']
    assert not m.evaluate_policy(usage(seconds=86400), credits(), m.ResetPolicy(enabled=True), now=NOW)['eligible']
    assert not m.evaluate_policy(usage(), credits(0), m.ResetPolicy(enabled=True), now=NOW)['eligible']
    assert not m.evaluate_policy(usage(), credits(), m.ResetPolicy(), now=NOW)['eligible']


@pytest.mark.parametrize('value', [None, True, float('nan'), float('inf'), -1, 101, '95'])
def test_bad_percent_fails_closed(value):
    m = module()
    assert not m.evaluate_policy(usage(value), credits(), m.ResetPolicy(enabled=True), now=NOW)['eligible']


def test_short_window_and_additional_limits_cannot_trigger():
    m = module()
    data = usage(5)
    data['additional_rate_limits'] = [{'rate_limit': usage(100)['rate_limit']}]
    assert not m.evaluate_policy(data, credits(), m.ResetPolicy(enabled=True), now=NOW)['eligible']
    data['rate_limit']['secondary_window'] = {'used_percent': 99, 'reset_at': NOW + 10000, 'limit_window_seconds': 18000}
    assert not m.evaluate_policy(data, credits(), m.ResetPolicy(enabled=True), now=NOW)['eligible']
    data['rate_limit']['secondary_window'] = usage()['rate_limit']['primary_window']
    assert m.evaluate_policy(data, credits(), m.ResetPolicy(enabled=True), now=NOW)['eligible']


@pytest.mark.parametrize('count', [None, True, -1, '2', 1.1])
def test_bad_count_fails_closed(count):
    m = module()
    assert not m.evaluate_policy(usage(), {'available_count': count}, m.ResetPolicy(enabled=True), now=NOW)['eligible']


def test_absolute_reset_prevents_stale_countdown_trigger():
    m = module()
    value = usage()
    value['rate_limit']['primary_window']['reset_at'] = NOW + 1
    assert not m.evaluate_policy(value, credits(), m.ResetPolicy(enabled=True), now=NOW)['eligible']


class FakeClient:
    identity = 'account-A'
    def __init__(self, outcome='reset', fail_after=False):
        self.posts = []
        self.outcome = outcome
        self.fail_after = fail_after
    def usage(self):
        if self.posts and self.fail_after:
            raise ValueError('secret=DO_NOT_RENDER')
        return usage(2, 604800) if self.posts and self.outcome == 'reset' else usage()
    def reset_credits(self):
        return credits(1 if self.posts and self.outcome == 'reset' else 2)
    def consume(self, request_id, *, credit_id=None, execute=False):
        assert execute is True
        self.posts.append(request_id)
        if self.outcome == 'timeout':
            raise TimeoutError('access_token=DO_NOT_RENDER')
        return {'code': self.outcome, 'windows_reset': 1 if self.outcome == 'reset' else 0}


def test_scan_default_never_consumes(tmp_path):
    m = module(); client = FakeClient()
    result = m.scan_profile('sample', policy=m.ResetPolicy(enabled=True), client=client, state_dir=tmp_path, now=NOW)
    assert not client.posts
    assert result['auto_reset']['status'] == 'dry_run'
    assert result['reset_credits']['available_count'] == 2


def test_scan_success_verifies_and_only_sends_once(tmp_path):
    m = module(); client = FakeClient()
    result = m.scan_profile('sample', policy=m.ResetPolicy(enabled=True), execute=True, client=client, state_dir=tmp_path, now=NOW)
    assert len(client.posts) == 1
    assert result['auto_reset']['status'] == 'reset_verified'
    assert result['reset_credits']['available_count'] == 1
    assert result['windows'][0]['used_percent'] == 2


def test_uncertain_never_retries_with_new_id_even_under_alias(tmp_path):
    m = module(); client = FakeClient('timeout')
    a = m.scan_profile('first', policy=m.ResetPolicy(enabled=True), execute=True, client=client, state_dir=tmp_path, now=NOW)
    b = m.scan_profile('same-account-alias', policy=m.ResetPolicy(enabled=True), execute=True, client=client, state_dir=tmp_path, now=NOW+2000)
    assert len(client.posts) == 1
    assert a['auto_reset']['status'] == 'uncertain'
    assert b['auto_reset']['status'] == 'blocked_pending'
    assert 'DO_NOT_RENDER' not in str(a) + str(b)


def test_readback_failure_is_not_verified_success(tmp_path):
    m = module(); client = FakeClient(fail_after=True)
    result = m.scan_profile('sample', policy=m.ResetPolicy(enabled=True), execute=True, client=client, state_dir=tmp_path, now=NOW)
    assert result['auto_reset']['status'] == 'uncertain'
    assert 'DO_NOT_RENDER' not in str(result)


@pytest.mark.parametrize('outcome', ['nothing_to_reset', 'no_credit', 'already_redeemed', 'unknown'])
def test_http_success_is_not_necessarily_reset(tmp_path, outcome):
    m = module(); client = FakeClient(outcome)
    result = m.scan_profile('sample', policy=m.ResetPolicy(enabled=True), execute=True, client=client, state_dir=tmp_path, now=NOW)
    assert result['auto_reset']['status'] != 'reset_verified'
    assert len(client.posts) == 1


def test_parallel_scans_reserve_same_account_once(tmp_path):
    m = module(); client = FakeClient('timeout')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: m.scan_profile(p, policy=m.ResetPolicy(enabled=True), execute=True, client=client, state_dir=tmp_path, now=NOW), ['a','b']))
    assert len(client.posts) == 1


def test_transport_payload_and_base_without_refresh(tmp_path):
    m = module(); calls = []
    def transport(method, url, headers, body, timeout):
        calls.append((method, url, body))
        if method == 'POST': return 200, {'code': 'reset', 'windows_reset': 1}
        return 200, credits() if 'reset-credits' in url else usage()
    client = m.CodexClient('test-access', 'test-account', 'https://relay.example/backend-api', transport=transport)
    assert client.usage()['rate_limit']
    assert client.reset_credits()['available_count'] == 2
    from uuid import uuid4
    request_id = str(uuid4())
    client.consume(request_id, execute=True)
    assert calls[-1] == ('POST','https://relay.example/backend-api/wham/rate-limit-reset-credits/consume',{'redeem_request_id':request_id})
    assert 'test-access' not in repr(client)


def test_count_fallback_does_not_allow_consumption(tmp_path):
    m = module()
    class CountOnly(FakeClient):
        def usage(self): return usage(rate_limit_reset_credits={'available_count': 2})
        def reset_credits(self): raise RuntimeError('detail404')
    c = CountOnly()
    result = m.scan_profile('sample', policy=m.ResetPolicy(enabled=True), execute=True, client=c, state_dir=tmp_path, now=NOW)
    assert result['reset_credits']['available_count'] == 2
    assert result['reset_credits']['status'] == 'count_only'
    assert not c.posts


def test_policy_config_is_strict_and_per_profile():
    m = module()
    policies = m.parse_policies('{"alpha":{"enabled":true,"threshold_percent":95,"min_remaining_seconds":86400},"beta":{"enabled":false}}')
    assert policies['alpha'].enabled
    assert not policies['beta'].enabled
    with pytest.raises(ValueError): m.parse_policies('{"x":{"enabled":"false"}}')


def test_card_displays_credit_and_policy_without_controls():
    m = module(); from chatglance.account_limits import render_account_limits_html
    data = {'codex':[m.scan_profile('sample', policy=m.ResetPolicy(enabled=True), client=FakeClient(), now=NOW)]}
    html = render_account_limits_html(data)
    assert '重置卡' in html and '2 张' in html and '最近到期' in html
    assert '仅预演' not in html and '自动重置：' not in html
    assert '到期' in html and '2030-01-01' in html
    assert '<button' not in html.lower()


def test_created_ledger_is_private(tmp_path):
    import os
    import stat
    if os.name != 'posix':
        pytest.skip('POSIX mode contract')
    m = module()
    m.scan_profile('sample', policy=m.ResetPolicy(enabled=True), execute=True, client=FakeClient('timeout'), state_dir=tmp_path, now=NOW)
    assert stat.S_IMODE((tmp_path/'codex-reset-ledger.sqlite3').stat().st_mode) == 0o600


def test_query_latency_rechecks_current_deadline(tmp_path, monkeypatch):
    m = module()
    current = [NOW]
    monkeypatch.setattr(m.time, 'time', lambda: current[0])
    class Slow(FakeClient):
        def reset_credits(self):
            current[0] += 2
            return credits()
    client = Slow()
    result = m.scan_profile('work', policy=m.ResetPolicy(enabled=True), execute=True, client=client, state_dir=tmp_path)
    assert not client.posts
    assert not result['auto_reset']['eligible']


def test_reservation_latency_rechecks_before_post(tmp_path, monkeypatch):
    m = module()
    current = [NOW]
    monkeypatch.setattr(m.time, 'time', lambda: current[0])
    reserve = m._reserve
    def slow_reserve(*args):
        result = reserve(*args)
        current[0] += 2
        return result
    monkeypatch.setattr(m, '_reserve', slow_reserve)
    client = FakeClient()
    result = m.scan_profile('work', policy=m.ResetPolicy(enabled=True), execute=True, client=client, state_dir=tmp_path)
    assert not client.posts
    assert result['auto_reset']['status'] == 'conditions_expired'
