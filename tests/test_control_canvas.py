"""Control iframe canvas follows its host, not Chrome's white default."""
import json
import shutil
import subprocess
import pytest
from chatglance.page_control import CONTROL_JS


def test_refresh_icon_uses_host_canvas_color():
    if not shutil.which('node'):
        pytest.skip('node unavailable')
    script = """
const vm = require('node:vm');
const root = {style:{}}; const body = {style:{}};
const button = {disabled:false,addEventListener(){}};
const document = {documentElement:root,body,getElementById(id){return id==='refresh-button'?button:null;}};
const parent = {location:{href:'https://example.invalid/projects'},document:{documentElement:{},body:{}},
  getComputedStyle(){return {getPropertyValue(){return '';},backgroundColor:'rgb(21, 21, 25)'};}};
const location = {origin:'https://example.invalid',href:'https://example.invalid/pages/'};
vm.runInNewContext(SOURCE,{document,parent,window:{parent},location,URL});
console.log(JSON.stringify({html:root.style.backgroundColor,body:body.style.backgroundColor}));
""".replace('SOURCE', json.dumps(CONTROL_JS))
    p = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=5, check=True)
    assert json.loads(p.stdout) == {'html':'rgb(21, 21, 25)','body':'rgb(21, 21, 25)'}
