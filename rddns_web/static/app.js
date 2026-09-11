'use strict';
const $ = id => document.getElementById(id);
const form = $('config');
let loaded = false, dirty = false, lastPhase = null;
const phases = {idle:'等待检查',queued:'任务排队中',reading:'读取 WAN 中',syncing:'同步解析中',tested:'取址测试成功',success:'同步正常',partial_error:'存在同步失败',error:'检查失败'};
const states = {updated:'已更新',unchanged:'记录已一致',error:'失败'};
function notice(text, error=false){$('notice').textContent=text;$('notice').className=error?'error':'';$('notice').hidden=false;}
async function api(path, method='GET', body){
 const options={method,cache:'no-store',headers:{'X-RDDNS-Request':'1'}};
 if(body!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}
 const r=await fetch(location.origin+'/api/'+path,options);
 if(r.status===401)throw new Error('登录已失效，请刷新页面重新登录');
 const data=await r.json(); if(!r.ok)throw new Error(data.error||'请求失败');return data;
}
function provider(){const ali=form.elements.provider.value==='alidns';$('ali-fields').hidden=!ali;$('cf-fields').hidden=ali;}
function stamp(value){return value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'—';}
async function load(){
 const c=await api('config');
 for(const [key,value] of Object.entries(c)){
  const e=form.elements.namedItem(key);if(!e)continue;
  if(e.type==='checkbox')e.checked=value;else e.value=Array.isArray(value)?value.join('\n'):value;
  if(c[key+'_set'])e.placeholder='已保存 · 留空保留';
 }
 provider();loaded=true;dirty=false;
}
form.addEventListener('input',()=>{dirty=true;});
form.elements.provider.addEventListener('change',provider);
form.addEventListener('submit',async e=>{
 e.preventDefault();if(!loaded)return;
 const c=Object.fromEntries(new FormData(form));
 c.enabled=form.elements.enabled.checked;c.ttl=Number(c.ttl);c.interval=Number(c.interval);
 c.domains=c.domains.split(/[\s,;]+/).filter(Boolean);
 $('save').disabled=true;
 try{await api('config','PUT',c);await load();notice('配置已保存。'+(c.enabled?'自动同步已启用。':'自动同步已暂停。'));await refresh();}
 catch(err){notice(err.message,true);}finally{$('save').disabled=false;}
});
for(const action of ['probe','sync'])$(action).addEventListener('click',async()=>{
 if(dirty){notice('请先保存配置，再执行'+(action==='probe'?'取址测试。':'同步。'),true);return;}
 try{await api(action,'POST',{});notice(action==='probe'?'正在测试取址，不会修改 DNS。':'同步任务已提交。');await refresh();}catch(err){notice(err.message,true);}
});
async function refresh(){
 try{
 const s=await api('status');$('connection').textContent='● 服务已连接';
 $('wan').textContent=s.wan_ip||'—';$('source').textContent=s.source||'等待可用地址';
 $('phase').textContent=phases[s.phase]||s.phase;$('checked').textContent='最近检查 '+stamp(s.checked_at);
 $('next').textContent=s.enabled?(s.running?'当前任务进行中':(s.next_run?stamp(s.next_run*1000):'即将检查')):'已暂停';
 $('success').textContent='最近全部成功 '+stamp(s.last_success);
 for(const id of ['probe','sync','save'])$(id).disabled=!loaded||s.running||s.phase==='queued';
 if(s.phase!==lastPhase){
  if(s.phase==='tested')notice('取址测试成功；未更新 DNS。');
  if(s.phase==='success')notice('全部域名已与 WAN 地址一致。');
  if(s.phase==='partial_error')notice('存在同步失败，请查看逐域名结果。',true);
  if(s.error)notice(s.error,true);
 }
 lastPhase=s.phase;
 $('records').replaceChildren();
 if(!s.records.length){$('records').textContent=s.running?'正在检查…':'尚无域名同步结果';}
 for(const r of s.records){const el=document.createElement('div');el.className='record '+r.state;
 const title=document.createElement('b');title.textContent=r.domain;
 const detail=document.createElement('span');detail.textContent=r.error||`${r.ip} · ${states[r.state]||r.state}`;
 el.append(title,detail);$('records').append(el);}
 $('events').replaceChildren();
 if(!s.events.length){const li=document.createElement('li');li.className='empty';li.textContent='等待首次检查';$('events').append(li);}
 for(const event of s.events){const li=document.createElement('li');const t=document.createElement('time');t.textContent=stamp(event.time);li.append(t,document.createTextNode(event.message));$('events').append(li);}
 }catch(err){$('connection').textContent='○ 服务连接中断';notice(err.message,true);}
}
async function poll(){await refresh();setTimeout(poll,2000);}
load().then(poll).catch(err=>notice(err.message,true));
