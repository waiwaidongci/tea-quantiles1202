import {DOMAIN} from '../constants/domain.js';
import {store,load,loadRows} from '../stores/research.js';
import {studies,labels} from '../api/research.js';
import {studySelect} from '../components/common/study-select.js';
import {table} from '../components/common/table.js';
import {esc} from '../utils/format.js';
import {bindForm} from '../hooks/forms.js';

function labelForm(){
  return `<h2 id="label-heading">登记${DOMAIN.origin_label}与${DOMAIN.grade_label} <small>校准排队时冻结这份登记</small></h2>
  <form id="label-form" class="inline-form">
    <label>源记录<select name="row_id" id="label-row">${store.rows.map(r=>`<option value="${r.id}">${esc(r.source_key)}${r.origin?' · '+esc(r.origin)+'/'+esc(r.grade):' · 未登记'}</option>`).join('')}</select></label>
    <label>${DOMAIN.origin_label}<select name="origin">${DOMAIN.origins.map(o=>`<option value="${esc(o)}">${esc(o)}</option>`).join('')}</select></label>
    <label>${DOMAIN.grade_label}<select name="grade">${DOMAIN.grades.map(g=>`<option value="${esc(g)}">${esc(g)}</option>`).join('')}</select></label>
    <button type="submit">保存登记</button>
  </form>`;
}

export async function render(){
  await loadRows();
  const writable=localStorage.getItem('research-role')!=='viewer';
  return `<div class="eyebrow">01 / SOURCE REGISTER</div><h1>${DOMAIN.study_label}与${DOMAIN.row_label}</h1><p>${DOMAIN.note}</p><div class="toolbar">${studySelect()}</div>
  ${writable?`<details><summary>新增${DOMAIN.study_label}</summary><form id="study-form" class="inline-form"><label>名称<input name="name" required minlength="2"></label><label>来源文件<input name="source_filename" value="field-notes-202611.csv" required></label><label>说明<input name="description"></label><button type="submit">保存批次</button></form></details>
  <h2 id="row-heading">录入${DOMAIN.row_label}</h2><form id="row-form" class="inline-form"><label>源记录编号<input name="source_key" placeholder="如 FIELD-001" required></label>${DOMAIN.fields.map(([key,label,kind])=>`<label>${esc(label)}<input name="${key}" type="${kind}" ${kind==='number'?'step="any" min="0"':''} required></label>`).join('')}<button type="submit">保存观测</button><button type="button" id="cancel-edit" hidden>取消编辑</button></form>
  ${labelForm()}`:'<p class="method-note">观察员可阅读登记；分析师与负责人可以录入或登记产地等级。</p>'}
  <h2>观测明细 <small>${store.rows.length} 条 · 运行后更改不会改写历史快照</small></h2>
  ${table(['源记录',DOMAIN.origin_label,DOMAIN.grade_label,...DOMAIN.fields.map(f=>f[1]),...(writable?['操作']:[])],
    store.rows.map(row=>[row.source_key,row.origin||'未登记',row.grade||'未登记',...DOMAIN.fields.map(f=>row.values[f[0]]),
      ...(writable?[{html:`<button class="text" data-label="${row.id}">登记产地等级</button> <button class="text" data-edit="${row.id}">编辑</button> <button class="text" data-delete="${row.id}">移除</button>`}]:[])]))}`;
}

export function bind(refresh){
  let editing=null;
  const sel=document.getElementById('study-select');
  if(sel)sel.onchange=()=>{store.studyId=+sel.value;refresh();};
  bindForm('study-form',async data=>{const s=await studies.create(data);store.studyId=s.id;await load();refresh();});
  bindForm('label-form',async data=>{await labels.save(store.studyId,+data.row_id,{origin:data.origin,grade:data.grade});await refresh();});
  bindForm('row-form',async data=>{const source_key=data.source_key;delete data.source_key;const values=Object.fromEntries(DOMAIN.fields.map(([key,label,kind])=>[key,kind==='number'?+data[key]:data[key]]));await studies.save(store.studyId,{source_key,values},editing);await load();refresh();});
  document.querySelectorAll('[data-label]').forEach(el=>el.onclick=()=>{
    const row=store.rows.find(r=>r.id===+el.dataset.label),form=document.getElementById('label-form');
    if(!form)return;
    document.getElementById('label-row').value=String(row.id);
    form.elements.origin.value=row.origin||DOMAIN.origins[0];
    form.elements.grade.value=row.grade||DOMAIN.grades[0];
    form.scrollIntoView({behavior:'smooth',block:'center'});
  });
  document.querySelectorAll('[data-edit]').forEach(el=>el.onclick=()=>{const row=store.rows.find(r=>r.id===+el.dataset.edit),form=document.getElementById('row-form');editing=row.id;form.elements.source_key.value=row.source_key;DOMAIN.fields.forEach(([key])=>form.elements[key].value=row.values[key]);document.getElementById('row-heading').textContent='编辑 '+row.source_key;document.getElementById('cancel-edit').hidden=false;form.scrollIntoView({behavior:'smooth',block:'center'});});
  const cancel=document.getElementById('cancel-edit');
  if(cancel)cancel.onclick=()=>refresh();
  document.querySelectorAll('[data-delete]').forEach(el=>el.onclick=async()=>{try{await studies.remove(store.studyId,+el.dataset.delete);await load();refresh();}catch(e){document.getElementById('notice').textContent=e.message;}});
}
