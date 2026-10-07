"""Exact original subscription status action; synthetic accounts only."""
import json
import re
from pathlib import Path
import pytest
from chatglance import reset_control as api
from chatglance.account_limits import render_account_limits_html
from chatglance.codex_resets import parse_policies
from chatglance.page_control import render_page, PageControlApp

OLD='2026-10-06T01:00:00+00:00';NEW='2026-10-07T01:00:00+00:00';COOKIE='session=fixture';ORIGIN='https://dashboard.example.invalid'
@pytest.fixture
def app(tmp_path,monkeypatch):
 r=tmp_path/'runtime';(r/'data').mkdir(parents=True);(r/'data/account-limits.json').write_text(json.dumps({'codex':[{'profile':'demo','status':'ok','observed_at':OLD,'windows':[]}]}))
 a=api.ControlApp(runtime_home=r,public_origin=ORIGIN,home=tmp_path/'home',authenticate=lambda c:c==COOKIE,diagnose=lambda row,policy,**kw:{'profile':row['profile'],'observed_at':row['observed_at'],'business_eligible':False,'automatic_allowed':False,'controls':{'account_enabled':False,'execute_enabled':True},'checks':[]})
 policies=parse_policies(json.dumps({'demo':{'enabled':False}}));monkeypatch.setattr(a,'flags',lambda profile:({},policies,'revision') if profile=='demo' else (_ for _ in ()).throw(api.ControlError('unknown',404)))
 return a

def test_original_refresh_is_button_and_entry_performs_no_fetch(app,monkeypatch):
 calls=[];monkeypatch.setattr(api,'read_status_account',lambda *a,**kw:calls.append(a),raising=False)
 html=app.page('demo',COOKIE)
 assert 'id="status-refresh-button"' in html and '刷新状态</button>' in html
 assert 'action="refresh-status"' in html and not calls

def test_new_top_subscription_button_is_removed():
 html=render_account_limits_html({'generated_at':OLD,'codex':[]})
 assert 'page=account-limits&amp;view=icon' not in html and '订阅详情手动刷新' not in html

def test_background_run_cannot_make_untouched_page_button_spin(tmp_path,monkeypatch):
 a=PageControlApp(tmp_path,ORIGIN);monkeypatch.setattr(a,'status',lambda page:{'state':'running','source':'scheduled','run_id':'scheduled-id'})
 html=render_page(a,'projects',COOKIE,view='icon');button=re.search(r'<button[^>]+id="refresh-button"[^>]*>',html).group()
 assert 'disabled' not in button and 'data-state="idle"' in html

def test_original_click_reads_only_selected_account_and_advances_real_status_time(app,monkeypatch):
 calls=[]
 def read(profile,policy,home):
  calls.append(profile);return {'profile':profile,'status':'ok','observed_at':NEW,'windows':[],'reset_credits':{'status':'ok','available_count':2},'auto_reset':{'execute':False}}
 monkeypatch.setattr(api,'read_status_account',read,raising=False);before=(app.runtime_home/'data/account-limits.json').read_bytes()
 result=app.refresh_status({'profile':'demo','csrf':app.token(COOKIE)},COOKIE,ORIGIN)
 assert result['state']=='success' and result['checked_at']==NEW and calls==['demo']
 html=app.page('demo',COOKIE);assert '最近状态刷新' in html and '上次计划检查' in html and '状态刷新成功' in html
 assert app.account('demo')['observed_at']==NEW and (app.runtime_home/'data/account-limits.json').read_bytes()==before
 assert app.account('demo')['status_refresh']['planned_at']==OLD

def test_failed_refresh_preserves_previous_status_and_returns_new_csrf(app,monkeypatch):
 monkeypatch.setattr(api,'read_status_account',lambda *a:{'profile':'demo','status':'error','observed_at':NEW,'error':'secret-canary'},raising=False)
 result=app.refresh_status({'profile':'demo','csrf':app.token(COOKIE)},COOKIE,ORIGIN)
 assert result['state']=='error' and result['csrf'] and 'secret-canary' not in json.dumps(result)
 assert app.account('demo')['observed_at']==OLD

@pytest.mark.parametrize('change',[{'profile':'../escape'},{'extra':'value'},{'csrf':'invalid'}])
def test_invalid_refresh_is_rejected_before_read(app,monkeypatch,change):
 calls=[];monkeypatch.setattr(api,'read_status_account',lambda *a:calls.append(a),raising=False);values={'profile':'demo','csrf':app.token(COOKIE),**change}
 with pytest.raises(api.ControlError):app.refresh_status(values,COOKIE,ORIGIN)
 assert not calls
