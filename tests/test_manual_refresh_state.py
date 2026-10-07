"""Run the shipped control JS with deterministic clock/network/UI state."""
import json
import shutil
import subprocess
import pytest
from chatglance.page_control import CONTROL_JS

HARNESS = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
let clock=0,id=0,queue=new Map(),storage=new Map(),posts=0,statusCalls=0,reloads=0;
let statusMode='running',networkErrors=0;
function page(kind='projects'){
 const handlers={},attrs={'aria-label':'手动刷新：尚未刷新'},button={disabled:false,title:'',getAttribute:k=>attrs[k],setAttribute:(k,v)=>attrs[k]=v,addEventListener:(k,fn)=>handlers[k]=fn};
 const badge={textContent:'',dataset:{},setAttribute(){},style:{}};
 const form={dataset:{state:'idle',runId:'',lastSuccessAt:'',lastObservedAt:''},elements:{page:{value:kind}},action:'https://example.invalid/pages/refresh'};
 const style={setProperty(){}},doc={getElementById:k=>({'refresh-button':button,'refresh':form,'refresh-status':badge})[k]||null,documentElement:{style},body:{style}};
 const host={querySelector:k=>k==='[data-refresh-feedback]'?badge:null,appendChild(){}};
 const location={origin:'https://example.invalid',href:'https://example.invalid/pages/?page='+kind,reload:()=>reloads++};
 const owner={location:{href:'https://example.invalid/'+kind,reload:()=>reloads++},getComputedStyle:()=>({getPropertyValue:()=>'',backgroundColor:'transparent'}),document:{documentElement:{},body:{}}};
 const window={parent:owner,frameElement:{parentElement:host,style:{}},location};
 const sandbox={window,parent:owner,location,document:doc,Date:class extends Date{static now(){return clock}},URL,URLSearchParams,AbortController,sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},FormData:class{constructor(){return [['page',kind],['csrf','synthetic']]}} ,setTimeout:(fn,ms)=>{queue.set(++id,{fn,at:clock+ms});return id},clearTimeout:i=>queue.delete(i),fetch:async(url,opts)=>{
   if(opts.method==='POST'){posts++;return {ok:true,json:async()=>({state:'running',run_id:'own-run'})}}
   statusCalls++;if(networkErrors){networkErrors--;throw Error('temporary offline')}
   const r={state:statusMode,run_id:'own-run',finished_at:'2026-10-07T06:00:00+00:00',observed_at:'2026-10-07T05:59:00+00:00',last_success_at:'2026-10-07T01:00:00+00:00',last_observed_at:'2026-10-07T00:59:00+00:00'};
   return {ok:true,json:async()=>r};
 }};
 vm.runInNewContext(source,sandbox);return {button,badge,handlers,attrs};
}
async function step(){const next=[...queue.entries()].sort((a,b)=>a[1].at-b[1].at)[0];assert(next,'poll must remain scheduled');queue.delete(next[0]);clock=Math.max(clock,next[1].at);await next[1].fn();await Promise.resolve()}
(async()=>{
 const a=page(PAGE);await a.handlers.click();assert(a.button.disabled);assert.equal(posts,1);
 if(CASE==='outage'){
   networkErrors=5;for(let i=0;i<5;i++)await step();assert(a.button.disabled,'poll outage must not permit duplicate click while run is unknown');assert.equal(a.attrs['aria-busy'],'true');assert.match(a.badge.textContent,/刷新/);assert.equal(posts,1);await step();assert(a.button.disabled);
 }else if(CASE==='long'){
   clock=3700000;await step();assert(a.button.disabled,'backend running must stay busy even beyond old UI deadline');assert.equal(a.attrs['aria-busy'],'true');assert(queue.size);
 }else if(CASE==='resume'){
   queue.clear();const b=page(PAGE);assert(b.button.disabled,'same tab must resume its own running request');assert.equal(b.attrs['aria-busy'],'true');await step();assert.equal(posts,1);
 }else if(CASE==='success'){
   statusMode='success';await step();assert.match(a.badge.textContent,/刷新完成/);assert.match(a.badge.textContent,/14:00:00/);assert.equal(a.attrs['aria-busy'],'false');assert(!a.button.disabled);await step();assert.equal(reloads,1);queue.clear();const b=page(PAGE);assert.match(b.badge.textContent,/刷新完成/);assert.equal(queue.size,0);assert.equal(reloads,1,'receipt restoration must not reload parent in a loop');
 }
 console.log(JSON.stringify({case:CASE,page:PAGE,posts,statusCalls,reloads}));
})().catch(e=>{console.error(e);process.exitCode=1});
'''

@pytest.mark.parametrize('page',['projects','servers'])
@pytest.mark.parametrize('case',['outage','long','resume','success'])
def test_manual_invocation_stays_running_until_confirmed_terminal(page,case):
    node=shutil.which('node')
    if not node:pytest.skip('Node runtime unavailable')
    script='const PAGE='+json.dumps(page)+', CASE='+json.dumps(case)+';\n'+HARNESS
    result=subprocess.run([node,'-e',script],input=json.dumps(CONTROL_JS),text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
