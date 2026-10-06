import json
from datetime import datetime, timezone
import pytest
from chatglance import page_control, refresh_history
from chatglance.account_limits import build_account_limits_page


def test_note_has_three_short_buttons(tmp_path):
    root = tmp_path / 'runtime'
    (root / 'config').mkdir(parents=True)
    (root / 'config/server-inventory.yml').write_text('inventory:\n  aliases: [fixture-host]\n')
    app = page_control.PageControlApp(root, 'https://example.invalid')
    html = page_control.render_page(app, 'servers', 'cookie', alias='fixture-host', view='note')
    assert '>保存</button>' in html and '>取消</button>' in html and '>清空</button>' in html
    assert 'id="note-clear"' in html


def test_subscription_has_authenticated_native_refresh_entry():
    page = build_account_limits_page({'generated_at': '2026-10-06T01:00:00+08:00'})
    source = page['columns'][0]['widgets'][0]['source']
    assert '<iframe title="订阅详情手动刷新"' in source
    assert '/_chatglance/reset-policy/pages/?page=account-limits&amp;view=icon' in source


def test_status_separates_active_run_last_success_and_observation(tmp_path, monkeypatch):
    records = [
        {'run_id': 'active-run', 'source': 'scheduled', 'status': 'running', 'effective_status': 'running', 'started_at': '2026-10-06T03:00:00+00:00', 'requested_pages': ['projects','account-limits'], 'pages': []},
        {'run_id': 'completed-run', 'source': 'scheduled', 'status': 'success', 'effective_status': 'success', 'started_at': '2026-10-06T01:00:00+00:00', 'finished_at': '2026-10-06T02:00:00+00:00', 'requested_pages': ['projects','account-limits'], 'published': True, 'pages': [{'page':'projects','status':'ok','generated_at':'2026-10-06T01:15:00+00:00'},{'page':'account-limits','status':'ok','generated_at':'2026-10-06T01:10:00+00:00'}]},
    ]
    monkeypatch.setattr(refresh_history, 'list_refresh_runs', lambda *a,**k: records)
    app = page_control.PageControlApp(tmp_path, 'https://example.invalid')
    status = app.status('projects')
    assert status['state'] == 'running' and status['run_id'] == 'active-run'
    assert status['last_success_at'] == '2026-10-06T02:00:00+00:00'
    assert status['last_observed_at'] == '2026-10-06T01:15:00+00:00'
    assert app.status('account-limits')['state'] == 'running'


def test_current_run_query_never_uses_previous_success(tmp_path, monkeypatch):
    record = {'run_id':'new-run','source':'browser','status':'running','effective_status':'running','requested_pages':['projects'],'pages':[],'started_at':'2026-10-06T03:00:00+00:00'}
    monkeypatch.setattr(refresh_history, 'show_refresh_run', lambda *a,**k: record)
    app = page_control.PageControlApp(tmp_path, 'https://example.invalid')
    app.jobs['projects'] = {'state':'success','run_id':'old-run'}
    assert app.status('projects', run_id='new-run')['state'] == 'running'
    with pytest.raises(page_control.PageControlError):
        app.status('servers', run_id='new-run')


def test_failed_refresh_keeps_last_success_time(tmp_path, monkeypatch):
    records = [
        {'run_id':'failed','status':'failed','effective_status':'failed','source':'browser','requested_pages':['projects'],'started_at':'2026-10-06T03:00:00+00:00','finished_at':'2026-10-06T04:00:00+00:00','published':False,'pages':[{'page':'projects','status':'error'}]},
        {'run_id':'good','status':'success','effective_status':'success','source':'scheduled','requested_pages':['projects'],'started_at':'2026-10-06T01:00:00+00:00','finished_at':'2026-10-06T02:00:00+00:00','published':True,'pages':[{'page':'projects','status':'ok','generated_at':'2026-10-06T01:30:00+00:00'}]},
    ]
    monkeypatch.setattr(refresh_history, 'list_refresh_runs', lambda *a,**k: records)
    app = page_control.PageControlApp(tmp_path, 'https://example.invalid')
    status = app.status('projects')
    assert status['state'] == 'error' and status['last_success_at'] == '2026-10-06T02:00:00+00:00'
    assert status['last_observed_at'] == '2026-10-06T01:30:00+00:00'
