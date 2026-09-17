"""Public SSR extraction is static, bounded, and separate from display caches."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path

import pytest

from chatglance import codex_collector as collector
from chatglance import codex_forecast
from chatglance import codex_resets as resets
from test_reset_guards import GuardClient, forecast, policy
from test_codex_resets import NOW

FIXTURE = Path(__file__).parent / 'fixtures' / 'codexreset-forecast.html'
SOURCE_TIME = '2027-01-15T08:00:00.000Z'
SOURCE_EPOCH = datetime.fromisoformat(SOURCE_TIME.replace('Z', '+00:00')).timestamp()


def test_static_ssr_parser_selects_only_current_top_level_score():
    result = codex_forecast.parse_public_forecast(FIXTURE.read_text(), now=SOURCE_EPOCH + 10)
    assert result['status'] == 'ok'
    assert result['probability_24h_percent'] == 28
    assert result['horizon'] == '24h'
    assert result['source'] == collector.PUBLIC_RESET_SOURCE
    assert datetime.fromisoformat(result['source_updated_at']).timestamp() == SOURCE_EPOCH


@pytest.mark.parametrize('old,new', [
    ('score24h:28,', ''),
    ('score24h:28,', 'score24h:28,score24h:5,'),
    ('score24h:28', 'score24h:NaN'),
    ('score24h:28', 'score24h:"28"'),
    ('score24h:28', 'score24h:(globalThis.DO_NOT_EXECUTE=true,20)'),
    ('score24h:28', 'score24h:101'),
    ('status:"live"', 'status:"stale"'),
    ('forecastStatus:"current"', 'forecastStatus:"stale"'),
    ('updatedAt:"' + SOURCE_TIME + '"', 'updatedAt:null'),
    ('forecast:$R[344]={', 'renamedForecast:$R[344]={'),
    ('forecast:$R[344]={', 'forecast:$R[344]=['),
    ('snapshot:$R[14]={', 'renamedSnapshot:$R[14]={'),
    ('score24h:28,score48h:49', 'score48h:49'),
])
def test_ssr_format_changes_and_lookalike_fields_fail_closed(old, new):
    page = FIXTURE.read_text().replace(old, new)
    assert codex_forecast.parse_public_forecast(page, now=SOURCE_EPOCH)['status'] != 'ok'


@pytest.mark.parametrize('delta,status', [(-1, 'future'), (7200, 'ok'), (7201, 'stale')])
def test_source_timestamp_not_fetch_time_controls_freshness(delta, status):
    result = codex_forecast.parse_public_forecast(FIXTURE.read_text(), now=SOURCE_EPOCH + delta)
    assert result['status'] == status
    assert datetime.fromisoformat(result['source_updated_at']).timestamp() == SOURCE_EPOCH


def test_no_structured_forecast_is_not_inferred_from_text_history_or_api():
    for page in ['<div>Next 24h: 0%</div>', '{"probability48h":5}', '<script>forecastHistory:[{score24h:1}]</script>']:
        assert codex_forecast.parse_public_forecast(page, now=SOURCE_EPOCH)['status'] != 'ok'


def test_ambiguous_multiple_ssr_snapshots_fail_closed():
    assert codex_forecast.parse_public_forecast(FIXTURE.read_text() * 2, now=SOURCE_EPOCH)['status'] != 'ok'


DECOY_SNAPSHOT = ('snapshot:$R[900]={status:"live",updatedAt:"' + SOURCE_TIME
                  + '",forecastStatus:"current",forecast:{score24h:1,score48h:99}}')
DECOY_ROUTER = ('$_TSR.router=($R=>$R[901]={matches:[{i:"//",s:"success",l:{'
                + DECOY_SNAPSHOT + '}}]})($R["tsr"]);')


INERT_HTML_SCRIPTS = [
    '<!-- <script>{router}</script> -->',
    *[pytest.param('<!-- note --' + space + '> <script>{router}</script> -->',
                   id='spaced-comment-close-' + str(index))
      for index, space in enumerate((' ', '\t', '\r\n'))],
    *['<' + tag + '><script>{router}</script></' + tag + '>' for tag in (
        'template', 'noscript', 'textarea', 'title', 'style', 'xmp', 'iframe',
        'noembed', 'noframes',
    )],
    '<template><template><script>{router}</script></template></template>',
    '<template><textarea></template><script>{router}</script></textarea></template>',
    '<template/><script>{router}</script></template>',
    '<textarea/><script>{router}</script></textarea>',
    *['<script ' + attrs + '>{router}</script>' for attrs in (
        'type="application/json"', 'type="text/plain"', 'type="importmap"',
        'type="speculationrules"', 'type="application/json" TYPE="text/javascript"',
        'src=""', 'src="/ignored.js"', 'nomodule', 'nomodule="false"',
        'language="vbscript"',
    )],
]


@pytest.mark.parametrize('wrapper', INERT_HTML_SCRIPTS)
def test_inert_html_script_never_supplies_current_snapshot(wrapper):
    result = codex_forecast.parse_public_forecast(
        wrapper.format(router=DECOY_ROUTER), now=SOURCE_EPOCH)
    assert result['status'] == 'invalid'
    assert result['probability_24h_percent'] is None


@pytest.mark.parametrize('wrapper', INERT_HTML_SCRIPTS)
def test_valid_current_snapshot_ignores_inert_html_script(wrapper):
    page = FIXTURE.read_text().replace('<div>Next 24h: 0%</div>',
                                    wrapper.format(router=DECOY_ROUTER))
    result = codex_forecast.parse_public_forecast(page, now=SOURCE_EPOCH)
    assert result['status'] == 'ok'
    assert result['probability_24h_percent'] == 28


@pytest.mark.parametrize('attrs', [
    '', 'type=""', 'type="text/javascript"', 'type="application/javascript"',
    'type="module"', 'TYPE=" TEXT/JAVASCRIPT " data-note=">"',
])
def test_real_inline_javascript_script_is_readable(attrs):
    page = '<SCRIPT ' + attrs + '>' + DECOY_ROUTER + '</SCRIPT>'
    result = codex_forecast.parse_public_forecast(page, now=SOURCE_EPOCH)
    assert result['status'] == 'ok'
    assert result['probability_24h_percent'] == 1


def test_plaintext_never_reopens_html_script_context():
    decoy = '<plaintext></plaintext><script>' + DECOY_ROUTER + '</script>'
    assert codex_forecast.parse_public_forecast(decoy, now=SOURCE_EPOCH)['status'] == 'invalid'
    page = FIXTURE.read_text().replace('</body>', decoy + '</body>')
    result = codex_forecast.parse_public_forecast(page, now=SOURCE_EPOCH)
    assert result['status'] == 'ok'
    assert result['probability_24h_percent'] == 28


def _with_snapshot_decoy(page, location):
    if location == 'history':
        return page.replace('forecastHistory:$R[354]=[',
                            'forecastHistory:$R[354]=[{' + DECOY_SNAPSHOT + '},')
    if location == 'history-route':
        return page.replace('matches:$R[10]=[', 'matches:$R[10]=['
                            + '{i:"/history",s:"success",l:{' + DECOY_SNAPSHOT + '}},')
    if location == 'nested-loader':
        return page.replace('l:$R[13]={', 'l:$R[13]={nested:{' + DECOY_SNAPSHOT + '},')
    decoy = {
        'string': "const note='" + DECOY_SNAPSHOT + "';",
        'block-comment': '/* ' + DECOY_SNAPSHOT + ' */',
        'line-comment': '// ' + DECOY_SNAPSHOT + '\n',
        'router-string': "const note='" + DECOY_ROUTER + "';",
        'router-comment': '/* ' + DECOY_ROUTER + ' */',
    }[location]
    return page.replace(';$_TSR.router=', ';' + decoy + '\n;$_TSR.router=')


@pytest.mark.parametrize('location', [
    'history', 'history-route', 'nested-loader', 'string', 'block-comment',
    'line-comment', 'router-string', 'router-comment',
])
def test_missing_current_snapshot_never_uses_decoy(location):
    page = FIXTURE.read_text().replace('snapshot:$R[14]={', 'unrelated:$R[14]={')
    page = _with_snapshot_decoy(page, location)
    result = codex_forecast.parse_public_forecast(page, now=SOURCE_EPOCH)
    assert result['status'] == 'invalid'
    assert result['probability_24h_percent'] is None


@pytest.mark.parametrize('location', [
    'history', 'history-route', 'nested-loader', 'string', 'block-comment',
    'line-comment', 'router-string', 'router-comment',
])
def test_valid_current_snapshot_ignores_decoy(location):
    page = _with_snapshot_decoy(FIXTURE.read_text(), location)
    result = codex_forecast.parse_public_forecast(page, now=SOURCE_EPOCH)
    assert result['status'] == 'ok'
    assert result['probability_24h_percent'] == 28


@pytest.mark.parametrize('wrapper', [
    "const note='{router}';", '/* {router} */', '// {router}\n',
    'function unused(){{{router}}}',
])
def test_router_assignment_must_be_a_top_level_code_statement(wrapper):
    page = '<script>' + wrapper.format(router=DECOY_ROUTER) + '</script>'
    assert codex_forecast.parse_public_forecast(page, now=SOURCE_EPOCH)['status'] == 'invalid'


@pytest.mark.parametrize('old,new', [
    ('i:"//"', 'i:"/"'),
    ('i:"//"', 'i:"/history"'),
    ('i:"//"', 'other:"//"'),
    ('s:"success",l:', 's:"error",l:'),
    ('s:"success",l:', 'l:'),
    ('matches:$R[10]=[', 'oldMatches:$R[10]=['),
    ('l:$R[13]={', 'oldLoader:$R[13]={'),
])
def test_only_successful_home_route_direct_loader_is_current(old, new):
    page = FIXTURE.read_text().replace(old, new)
    assert codex_forecast.parse_public_forecast(page, now=SOURCE_EPOCH)['status'] == 'invalid'


@pytest.mark.parametrize('status', ['success', 'error'])
def test_duplicate_current_routes_fail_closed_even_if_only_one_has_snapshot(status):
    page = FIXTURE.read_text().replace('matches:$R[10]=[',
        'matches:$R[10]=[{i:"//",s:"' + status + '"},')
    assert codex_forecast.parse_public_forecast(page, now=SOURCE_EPOCH)['status'] == 'invalid'


def test_public_fetch_reuses_one_bounded_html_request(monkeypatch):
    page = FIXTURE.read_text().replace(SOURCE_TIME, datetime.fromtimestamp(NOW, tz=timezone.utc).isoformat())
    calls = []

    class Response(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 2_000_001
            calls.append(('read', size))
            return super().read(size)

    def open_request(request, *, timeout):
        assert request.full_url == collector.PUBLIC_RESET_SOURCE
        calls.append(('request', timeout))
        return Response(page.encode())

    monkeypatch.setattr(collector.urllib.request, 'urlopen', open_request)
    monkeypatch.setattr(codex_forecast.time, 'time', lambda: NOW)
    result = collector.fetch_public_codex_reset(7)
    assert calls[0] == ('request', 7)
    assert len(calls) == 2
    assert result['forecast']['probability_24h_percent'] == 28
    assert result['forecast']['status'] == 'ok'
    assert result['events'] == []  # missing history does not destroy a valid forecast


@pytest.mark.parametrize('mode', ['oversize', 'timeout'])
def test_fetch_failure_never_leaks_body_or_exception_text(monkeypatch, mode):
    def fail(request, *, timeout):
        if mode == 'timeout':
            raise TimeoutError('DO_NOT_RENDER')
        return io.BytesIO(b'DO_NOT_RENDER' + b' ' * 2_000_001)

    monkeypatch.setattr(collector.urllib.request, 'urlopen', fail)
    result = collector.fetch_public_codex_reset(3)
    assert result['status'] == 'error'
    assert result['forecast']['status'] != 'ok'
    assert 'DO_NOT_RENDER' not in json.dumps(result)


@pytest.mark.parametrize('mode', ['fresh', 'failed', 'skipped'])
def test_collector_fetches_before_accounts_and_never_uses_cached_forecasts(tmp_path, monkeypatch, mode):
    calls, clients = [], []
    monkeypatch.setattr(resets.time, 'time', lambda: NOW)
    monkeypatch.setattr(collector, 'collection_settings', lambda **kw: {
        'reset_policies': '{}', 'reset_base_url': None, 'execute_resets': False,
    })
    path = tmp_path / 'snapshot.json'
    cached_event = {'event_id': 'old-confirmed', 'time_utc': '2026-01-01T00:00:00Z'}
    path.write_text(json.dumps({'generated_at': '2026-01-01T00:00:00Z', 'codex_reset': {
        'status': 'ok', 'events': [cached_event], 'forecast': forecast(0),
    }}))

    def fetch(timeout):
        assert mode != 'skipped'
        calls.append('fetch')
        return {'status': 'empty' if mode == 'fresh' else 'error', 'events': [],
                'forecast': forecast(71) if mode == 'fresh' else None}

    def scan(profile, **kwargs):
        calls.append(profile)
        client = GuardClient()
        clients.append(client)
        return resets.scan_profile(profile, client=client, state_dir=tmp_path / 'state', now=NOW, **kwargs)

    monkeypatch.setattr(collector, 'fetch_public_codex_reset', fetch)
    monkeypatch.setattr(collector, 'scan_profile', scan)
    policies = json.dumps({'example': policy().__dict__, 'other': policy().__dict__})
    result = collector.collect_account_limits(profiles=['example', 'other'], output_path=path,
        history_path=path, execute_resets=True, reset_policies=policies,
        home=tmp_path, no_public_reset=(mode == 'skipped'))
    assert calls == (['example', 'other'] if mode == 'skipped' else ['fetch', 'example', 'other'])
    assert all(not client.posts for client in clients)
    assert all(not item['auto_reset']['eligible'] for item in result['codex'])
    if mode != 'skipped':
        assert result['codex_reset']['events'] == [cached_event]
        assert result['codex_reset']['using_last_known_values'] is True
    assert result['codex_reset']['forecast'] != forecast(0)
    assert json.loads(path.read_text())['codex_reset']['forecast'] == result['codex_reset']['forecast']
