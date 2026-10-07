"""Real original refresh HTTP path; auth/CSRF and snapshot boundaries."""
import json,re
import pytest
from test_reset_control import control,request,COOKIE,ORIGIN
from chatglance import reset_control as api


def test_original_status_refresh_http_success_and_csrf_one_use(control,monkeypatch):
 server,store,base=control;calls=[]
 def read(profile,policy,home):
  calls.append(profile);return {'profile':profile,'status':'ok','observed_at':'2027-01-01T01:00:00+00:00','windows':[]}
 monkeypatch.setattr(api,'read_status_account',read)
 code,html,_=request(base);token=re.search(r'<form id="status-refresh".*?name="csrf" value="([^"]+)"',html).group(1)
 before=store.load_active(api.ChatGlanceConfig)
 values={'profile':'demo','csrf':token}
 code,body,_=request(base,'/refresh-status',values=values);assert code==200 and json.loads(body)['state']=='success'
 assert calls==['demo'] and store.load_active(api.ChatGlanceConfig)==before
 assert request(base,'/refresh-status',values=values)[0]==403
 assert request(base,'/refresh-status',values={'profile':'demo','csrf':'x'},cookie=None)[0]==401
 assert request(base,'/refresh-status',values={'profile':'demo','csrf':'x'},origin='https://evil.invalid')[0]==403


def test_status_reader_is_explicitly_nonconsuming(monkeypatch):
 from chatglance import codex_collector,codex_resets
 seen={}
 monkeypatch.setattr(api,'collection_settings',lambda **kw:{})
 monkeypatch.setattr(codex_collector,'_managed_client_options',lambda settings,profiles:{'token_service':'CRS','client_factory':object()})
 monkeypatch.setattr(codex_resets,'scan_profile',lambda profile,**kw:seen.update(kw) or {'profile':profile})
 api.read_status_account('demo',codex_resets.ResetPolicy(),None)
 assert seen['execute'] is False and seen['token_service']=='CRS' and seen['timeout']==8
