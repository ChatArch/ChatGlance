"""Offline acceptance: no credential reads or external requests are needed."""
import copy
import json
import sqlite3
from uuid import UUID

import pytest

from test_codex_resets import FakeClient, NOW, credits, module, usage


@pytest.mark.parametrize('field,value', [
    ('enabled', 'true'), ('enabled', 1), ('threshold_percent', True),
    ('threshold_percent', float('nan')), ('threshold_percent', 101),
    ('min_remaining_seconds', -1), ('min_remaining_seconds', '86400'),
    ('min_remaining_seconds', float('inf')),
])
def test_invalid_policy_never_coerces(field, value):
    with pytest.raises(ValueError):
        module().ResetPolicy(**{field: value})


@pytest.mark.parametrize('text', ['[]', 'null', '{"a":{"enable":true}}', '{"a":null}',
                                  '{"a":{},"a":{"enabled":true}}'])
def test_invalid_policy_json_rejected(text):
    with pytest.raises(ValueError):
        module().parse_policies(text)


@pytest.mark.parametrize('value', [None, True, 'bad', float('nan'), float('inf'), -1])
def test_invalid_absolute_time_not_replaced_by_stale_countdown(value):
    data = usage()
    data['rate_limit']['primary_window']['reset_at'] = value
    assert not module().evaluate_policy(data, credits(), module().ResetPolicy(enabled=True), now=NOW)['eligible']


def test_no_absolute_reset_anchor_fails_closed():
    data = usage()
    del data['rate_limit']['primary_window']['reset_at']
    assert not module().evaluate_policy(data, credits(), module().ResetPolicy(enabled=True), now=NOW)['eligible']


@pytest.mark.parametrize('stale_key', ['stale', 'using_last_known_values'])
def test_stale_data_cannot_trigger(stale_key):
    data = usage(**{stale_key: True})
    assert not module().evaluate_policy(data, credits(), module().ResetPolicy(enabled=True), now=NOW)['eligible']


def test_dry_run_does_not_create_state_directory(tmp_path):
    state = tmp_path / 'no-state'
    result = module().scan_profile('example', client=FakeClient(), state_dir=state,
                                   policy=module().ResetPolicy(enabled=True), now=NOW)
    assert result['auto_reset']['status'] == 'dry_run'
    assert not state.exists()


def test_zero_unknown_and_count_only_are_distinct(tmp_path):
    m = module()
    class Zero(FakeClient):
        def reset_credits(self): return credits(0)
    class Unknown(FakeClient):
        def reset_credits(self): return {'error': 'DO_NOT_RENDER'}
    zero = m.scan_profile('example', client=Zero(), state_dir=tmp_path, now=NOW)
    unknown = m.scan_profile('example', client=Unknown(), state_dir=tmp_path, now=NOW)
    assert zero['reset_credits']['available_count'] == 0
    assert zero['reset_credits']['status'] == 'ok'
    assert unknown['reset_credits']['available_count'] is None
    assert unknown['reset_credits']['status'] == 'unknown'


def test_reserved_uuid_committed_before_consume(tmp_path):
    m = module()
    class InspectPending(FakeClient):
        def consume(self, request_id, *, execute=False, credit_id=None):
            assert execute is True
            assert str(UUID(request_id)) == request_id
            files = list(tmp_path.glob('*.sqlite3'))
            assert len(files) == 1
            with sqlite3.connect(files[0]) as db:
                pending = db.execute('select request_id,status from reset_ledger').fetchall()
            assert pending == [(request_id, 'pending')]
            return super().consume(request_id, execute=execute)
    result = m.scan_profile('example', client=InspectPending(), state_dir=tmp_path,
                            policy=m.ResetPolicy(enabled=True), execute=True, now=NOW)
    assert result['auto_reset']['status'] == 'reset_verified'


@pytest.mark.parametrize('outcome', ['unknown', 'already_redeemed'])
def test_unknown_outcomes_block_forever_even_after_a_month(tmp_path, outcome):
    m = module(); client = FakeClient(outcome)
    m.scan_profile('a', client=client, state_dir=tmp_path, policy=m.ResetPolicy(enabled=True), execute=True, now=NOW)
    row = m.scan_profile('b', client=client, state_dir=tmp_path, policy=m.ResetPolicy(enabled=True), execute=True, now=NOW+2592000)
    assert len(client.posts) == 1
    assert row['auto_reset']['status'] == 'blocked_pending'


@pytest.mark.parametrize('outcome', ['nothing_to_reset', 'no_credit'])
def test_known_no_reset_cools_down(tmp_path, outcome):
    m = module(); client = FakeClient(outcome)
    first = m.scan_profile('a', client=client, state_dir=tmp_path, policy=m.ResetPolicy(enabled=True), execute=True, now=NOW)
    row = m.scan_profile('b', client=client, state_dir=tmp_path, policy=m.ResetPolicy(enabled=True), execute=True, now=NOW+1)
    assert len(client.posts) == 1
    assert first['auto_reset']['status'] == outcome
    assert row['auto_reset']['status'] == 'cooldown'


def test_account_identities_are_independent(tmp_path):
    m = module(); a = FakeClient('timeout'); b = FakeClient('timeout'); b.identity = 'different-account'
    for client in (a, b):
        m.scan_profile('same-profile', client=client, state_dir=tmp_path, policy=m.ResetPolicy(enabled=True), execute=True, now=NOW)
    assert len(a.posts) == len(b.posts) == 1


@pytest.mark.parametrize('mode', ['same_usage', 'same_count', 'zero_windows', 'bool_windows'])
def test_success_requires_code_windows_and_both_readbacks_lower(tmp_path, mode):
    m = module()
    class NotVerified(FakeClient):
        def usage(self): return usage() if mode == 'same_usage' else super().usage()
        def reset_credits(self): return credits() if mode == 'same_count' else super().reset_credits()
        def consume(self, request_id, *, execute=False, credit_id=None):
            result = super().consume(request_id, execute=execute)
            if mode == 'zero_windows': result['windows_reset'] = 0
            if mode == 'bool_windows': result['windows_reset'] = True
            return result
    c = NotVerified()
    row = m.scan_profile('example', client=c, state_dir=tmp_path, policy=m.ResetPolicy(enabled=True), execute=True, now=NOW)
    assert row['auto_reset']['status'] == 'uncertain'
    assert len(c.posts) == 1


def test_verified_snapshot_cannot_be_redeemed_again_under_alias(tmp_path):
    m = module(); first = FakeClient()
    m.scan_profile('a', client=first, state_dir=tmp_path, policy=m.ResetPolicy(enabled=True), execute=True, now=NOW)
    stale = FakeClient()
    row = m.scan_profile('b', client=stale, state_dir=tmp_path, policy=m.ResetPolicy(enabled=True), execute=True, now=NOW+7200)
    assert not stale.posts
    assert row['auto_reset']['last_action']['status'] == 'reset_verified'


def test_query_failure_never_posts_or_leaks_arbitrary_error(tmp_path):
    m = module()
    class Broken(FakeClient):
        def usage(self): raise RuntimeError('arbitrary_sensitive_value_DO_NOT_RENDER')
    c = Broken()
    row = m.scan_profile('example', client=c, state_dir=tmp_path,
                         policy=m.ResetPolicy(enabled=True), execute=True, now=NOW)
    assert not c.posts
    assert row['status'] != 'ok'
    assert 'DO_NOT_RENDER' not in json.dumps(row)


def test_row_excludes_raw_account_and_credit_identifiers(tmp_path):
    m = module()
    class Secret(FakeClient):
        def usage(self): return usage(account_id='raw-id', email='private@example.com', access_token='secret-value')
        def reset_credits(self): return {'available_count': 1, 'credits': [
            {'id': 'credit-id-private', 'status': 'available', 'expires_at': '2030-01-01T00:00:00Z'}]}
    row = m.scan_profile('example', client=Secret(), state_dir=tmp_path, now=NOW)
    encoded = json.dumps(row)
    for secret in ['raw-id', 'private@example.com', 'secret-value', 'credit-id-private', 'account-A']:
        assert secret not in encoded
