"""Offline safety contract: exact quota windows and public 24h forecast veto."""
from datetime import datetime, timezone
import json

import pytest

from chatglance import codex_resets as resets
from test_codex_resets import FakeClient, NOW, credits, usage


WEEK = 604800


def forecast(probability=70, age=0, **updates):
    return {
        'source': 'https://codexreset.org/', 'horizon': '24h', 'status': 'ok',
        'probability_24h_percent': probability,
        'source_updated_at': datetime.fromtimestamp(NOW - age, timezone.utc).isoformat(),
        **updates,
    }


def policy(**updates):
    return resets.ResetPolicy(**{
        'enabled': True, 'min_remaining_seconds': 129600,
        'target_window_seconds': WEEK, 'skip_if_forecast_24h_above': 70,
        **updates,
    })


def windows(weekly_used=95, weekly_name='secondary_window', seconds=172800):
    week = usage(weekly_used, seconds)['rate_limit']['primary_window']
    short = {'used_percent': 100, 'reset_at': NOW + 200000, 'limit_window_seconds': 18000}
    other = 'primary_window' if weekly_name == 'secondary_window' else 'secondary_window'
    return {'rate_limit': {weekly_name: week, other: short}}


class GuardClient(FakeClient):
    def __init__(self, data=None):
        super().__init__('timeout')
        self.data = data if data is not None else windows()

    def usage(self):
        return self.data


@pytest.mark.parametrize('hours,eligible', [(35.99, False), (36, False), (36.01, True)])
def test_natural_reset_36_hour_boundary(hours, eligible):
    decision = resets.evaluate_policy(windows(seconds=hours * 3600), credits(), policy(), now=NOW, forecast=forecast())
    assert decision['eligible'] is eligible


@pytest.mark.parametrize('probability,eligible', [(70, True), (70.01, False), (100, False), (0, True)])
def test_forecast_is_strictly_above_threshold(probability, eligible):
    result = resets.evaluate_policy(windows(), credits(), policy(), now=NOW, forecast=forecast(probability))
    assert result['eligible'] is eligible
    if not eligible:
        assert result['reason'] == 'forecast_above_threshold'


@pytest.mark.parametrize('raw', [
    None, {}, [], forecast(float('nan')), forecast(float('inf')), forecast(-1),
    forecast(101), forecast(True), forecast('20'), forecast(source_updated_at=None),
    forecast(source_updated_at='not-a-date'), forecast(source_updated_at='2026-01-01T12:00:00'),
    forecast(age=-1), forecast(age=7200.01), forecast(status='error'),
    forecast(horizon='48h'), forecast(source='https://example.com/'),
    forecast(stale=True), forecast(using_last_known_values=True),
])
def test_unusable_forecast_fails_closed_even_with_execute(tmp_path, raw):
    client = GuardClient()
    row = resets.scan_profile('example', policy(), client=client, state_dir=tmp_path,
                              now=NOW, execute=True, forecast=raw)
    assert not client.posts
    assert not row['auto_reset']['eligible']
    assert row['auto_reset']['reason'] == 'forecast_unavailable'
    assert row['auto_reset']['forecast']['status'] != 'ok'
    assert not list(tmp_path.glob('*.sqlite3'))


def test_exact_ttl_is_usable_and_safe_snapshot_omits_raw_fields(tmp_path):
    row = resets.scan_profile('example', policy(), client=GuardClient(), state_dir=tmp_path,
                              now=NOW, forecast=forecast(age=7200, raw_body='DO_NOT_RENDER'))
    assert row['auto_reset']['status'] == 'dry_run'
    assert row['auto_reset']['forecast']['status'] == 'ok'
    assert 'DO_NOT_RENDER' not in json.dumps(row)


@pytest.mark.parametrize('name', ['primary_window', 'secondary_window'])
def test_weekly_target_is_independent_of_window_position(tmp_path, name):
    client = GuardClient(windows(weekly_name=name))
    row = resets.scan_profile('example', policy(), client=client, state_dir=tmp_path,
                              now=NOW, forecast=forecast())
    assert row['auto_reset']['status'] == 'dry_run'
    assert row['auto_reset']['target']['name'] == name
    assert row['auto_reset']['target']['window_seconds'] == WEEK
    assert not client.posts


@pytest.mark.parametrize('data', [
    windows(weekly_used=0),
    {'rate_limit': {'primary_window': {'used_percent': 100, 'reset_at': NOW + 200000, 'limit_window_seconds': 18000}}},
    {'rate_limit': {'primary_window': {'used_percent': 100, 'reset_at': NOW + 200000}}},
    {'rate_limit': {'primary_window': {'used_percent': 100, 'reset_at': NOW + 200000, 'limit_window_seconds': '604800'}}},
    {'additional_rate_limits': [{'rate_limit': windows()['rate_limit']}]},
])
def test_short_or_missing_weekly_window_never_consumes(tmp_path, data):
    client = GuardClient(data)
    row = resets.scan_profile('example', policy(), client=client, state_dir=tmp_path,
                              now=NOW, execute=True, forecast=forecast())
    assert not client.posts
    assert not row['auto_reset']['eligible']


@pytest.mark.parametrize('cause', ['forecast_ttl', 'natural_reset', 'weekly_window'])
def test_all_guards_are_rechecked_after_reservation(tmp_path, monkeypatch, cause):
    current = [NOW]
    monkeypatch.setattr(resets.time, 'time', lambda: current[0])
    client = GuardClient(windows(seconds=129601 if cause == 'natural_reset' else 172800))
    original = resets._reserve

    def delayed_reserve(*args):
        result = original(*args)
        current[0] += 2
        if cause == 'weekly_window':
            client.data['rate_limit']['secondary_window']['limit_window_seconds'] = 18000
        return result

    monkeypatch.setattr(resets, '_reserve', delayed_reserve)
    row = resets.scan_profile('example', policy(), client=client, state_dir=tmp_path,
                              execute=True, forecast=forecast(age=7199 if cause == 'forecast_ttl' else 0))
    assert not client.posts
    assert row['auto_reset']['status'] == 'conditions_expired'
    if cause == 'forecast_ttl':
        assert row['auto_reset']['forecast']['status'] == 'stale'


@pytest.mark.parametrize('missing', ['usage', 'credits'])
def test_low_probability_never_replaces_original_guards(missing):
    decision = resets.evaluate_policy({} if missing == 'usage' else windows(),
                                      {} if missing == 'credits' else credits(),
                                      policy(), now=NOW, forecast=forecast(0))
    assert not decision['eligible']


def test_unconfigured_new_guards_preserve_compatibility():
    legacy = resets.ResetPolicy(enabled=True)
    assert legacy.target_window_seconds is None
    assert legacy.skip_if_forecast_24h_above is None
    assert resets.evaluate_policy(usage(), credits(), legacy, now=NOW)['eligible']


@pytest.mark.parametrize('field,value', [
    ('target_window_seconds', True), ('target_window_seconds', 0), ('target_window_seconds', -1),
    ('target_window_seconds', '604800'), ('target_window_seconds', float('nan')),
    ('skip_if_forecast_24h_above', True), ('skip_if_forecast_24h_above', '70'),
    ('skip_if_forecast_24h_above', float('inf')), ('skip_if_forecast_24h_above', -1),
    ('skip_if_forecast_24h_above', 101),
])
def test_new_policy_fields_are_strict(field, value):
    with pytest.raises(ValueError):
        resets.parse_policies(json.dumps({'example': {field: value}}))


def test_optional_policy_fields_are_loaded_by_exact_profile():
    parsed = resets.parse_policies(json.dumps({'example': {
        'enabled': True, 'target_window_seconds': WEEK, 'skip_if_forecast_24h_above': 70,
    }, 'other': {}}))
    assert parsed['example'].target_window_seconds == WEEK
    assert parsed['example'].skip_if_forecast_24h_above == 70
    assert parsed['other'].target_window_seconds is None


def test_ambiguous_matching_windows_never_consume(tmp_path):
    data = windows()
    data['rate_limit']['primary_window'].update(limit_window_seconds=WEEK, used_percent=0)
    client = GuardClient(data)
    row = resets.scan_profile('example', policy(), client=client, state_dir=tmp_path,
                              now=NOW, execute=True, forecast=forecast())
    assert not client.posts
    assert not row['auto_reset']['eligible']
    assert row['auto_reset']['reason'] == 'target_window_ambiguous'
