"""Browser-like DOM contract for cancel; no network or live notes."""
import json
import shutil
import subprocess
import pytest
from chatglance.page_control import CONTROL_JS


def test_cancel_discards_input_and_refreshes_only_note_frame():
    if not shutil.which('node'):
        pytest.skip('Node unavailable')
    script=r'''
const vm=require('vm');const calls=[];const handlers={};
const textarea={value:'unsaved',defaultValue:'original',focus(){}};
const form={reset(){textarea.value=textarea.defaultValue;calls.push('reset')},querySelector(){return textarea}};
const cancel={addEventListener(name,cb){handlers.cancel=cb}};
const status={textContent:'old error'};
const popover={hidePopover(){calls.push('closed')}};
const parent={location:{href:'https://example.invalid/servers',reload(){calls.push('parent-reload')}},getComputedStyle(){return {getPropertyValue(){return ''}}},document:{documentElement:{}}};
const win={parent,location:{href:'https://example.invalid/pages/?page=servers&view=note',origin:'https://example.invalid',reload(){calls.push('note-reload')}},frameElement:{closest(){return popover}}};
const doc={documentElement:{style:{setProperty(){}}},getElementById(id){return {'note':form,'note-cancel':cancel,'note-status':status}[id]||null}};
vm.runInNewContext(process.argv[1],{window:win,document:doc,URL,URLSearchParams,AbortController,setTimeout,clearTimeout});
handlers.cancel();console.log(JSON.stringify({value:textarea.value,calls,status:status.textContent}));
'''
    r=subprocess.run(['node','-e',script,CONTROL_JS],capture_output=True,text=True,check=True,timeout=5)
    result=json.loads(r.stdout)
    assert result['value']=='original'
    assert result['calls']==['reset','closed','note-reload']
    assert result['status']==''
