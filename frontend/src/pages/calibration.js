import {DOMAIN} from '../constants/domain.js';
import {store,load} from '../stores/research.js';
import {calibrations} from '../api/research.js';
import {studySelect} from '../components/common/study-select.js';
import {table} from '../components/common/table.js';
import {esc,fmt} from '../utils/format.js';
import {bindForm} from '../hooks/forms.js';
import {CALIBRATION_LABELS} from '../types/enums.js';

const state=x=>`<span class="status ${x}">${CALIBRATION_LABELS[x]||x}</span>`;

function matrix(title,origins,grades,rows,extra){
  return `<h2>${esc(title)}</h2><div class="table-wrap"><table><thead><tr><th>${DOMAIN.origin_label} \\ ${DOMAIN.grade_label}</th>${grades.map(g=>`<th>${esc(g)}</th>`).join('')}<th>${esc(extra)}</th></tr></thead><tbody>${origins.map((o,i)=>`<tr><td>${esc(o)}</td>${grades.map((g,j)=>`<td>${rows[i]?.[j]??0}</td>`).join('')}<td>${rows[i]?rows[i].reduce((a,b)=>a+b,0):0}</td></tr>`).join('')}<tr><td>合计</td>${grades.map((g,j)=>`<td>${origins.reduce((n,o,i)=>n+(rows[i]?.[j]??0),0)}</td>`).join('')}<td>${origins.reduce((n,o,i)=>n+(rows[i]?.reduce((a,b)=>a+b,0)||0),0)}</td></tr></tbody></table></div>`;
}

function targetsForm(){
  return `<form id="calibration-form" class="worksheet">
    ${studySelect()}
    <label>本次校准名称<input name="name" required minlength="2" value="${esc(DOMAIN.names[0])} · 产地等级校准"></label>
    <h3>${DOMAIN.origin_label}目标份数</h3>
    <div class="inline-form">${DOMAIN.origins.map(o=>`<label>${esc(o)}<input name="origin:${esc(o)}" type="number" min="0" step="1" value="0" required></label>`).join('')}</div>
    <h3>${DOMAIN.grade_label}目标份数</h3>
    <div class="inline-form">${DOMAIN.grades.map(g=>`<label>${esc(g)}<input name="grade:${esc(g)}" type="number" min="0" step="1" value="0" required></label>`).join('')}</div>
    <p>只给有茶样的格子分配整数份数；两套目标必须同时达标，且各格份数与实收份数的绝对差之和最小。并列时取按产地、等级排序后字典序最小的一组。</p>
    <button type="submit">冻结目标并排队 →</button>
  </form>`;
}

function summary(row){
  const result=row.result;
  if(row.status==='infeasible'){
    const d=result?.diagnostics||{};
    const axis=d.axis||{};
    const reach=`<p>产地轴单独可达：<strong>${axis.origin?.reachable?'是':'否'}</strong> · 等级轴单独可达：<strong>${axis.grade?.reachable?'是':'否'}</strong> · 可同时达标：<strong>${d.simultaneous_feasible?'是':'否'}</strong></p>`;
    const comps=d.components?.length?`<ul>${d.components.map(c=>`<li>产地组 [${c.origins.map(esc).join(', ')}] 目标 ${fmt(c.origin_total)} · 等级组 [${c.grades.map(esc).join(', ')}] 目标 ${fmt(c.grade_total)} · ${c.balanced?'平衡':'不平衡'}</li>`).join('')}</ul>`:'';
    return `<div class="method-note error"><strong>无解：${esc(result?.message||row.error||'')}</strong>${result?.blocking?.length?`<ul>${result.blocking.map(b=>`<li>${esc(b)}</li>`).join('')}</ul>`:''}${comps}${reach}<p>生效的仍是旧版本${result?.retained_active_id?` #${result.retained_active_id}`:'（此前没有生效版本）'}。</p></div>`;
  }
  if(row.status==='failed')return `<div class="error">计算失败：${esc(row.error)}</div>`;
  if(row.status==='superseded')return `<div class="method-note">这次申请已被较新的申请取代，不再生效，结果仅留档。</div>`;
  if(row.status!=='completed'||!result)return `<p class="method-note">正在计算。此页每2秒刷新。</p>`;
  const w=result.weighted;
  const d=result.diagnostics;
  return `<section class="result-intro"><strong>校准后含水率中位数 ${fmt(w.quantiles['中位数'])}%，均值 ${fmt(w.mean)}%</strong><p>${esc(result.caveat)}</p></section>
  <h2>核心数值</h2>${table(['加权指标','值'],Object.entries(w.quantiles).map(([k,v])=>[k,fmt(v)+'%']).concat([['均值',fmt(w.mean)+'%'],['权重合计',fmt(w.weight_sum)],['目标总份数',fmt(result.total)],['绝对差之和',fmt(result.objective)]]))}
  <div class="method-note"><strong>两轴核对通过</strong><p>产地目标合计 ${fmt(d.origin_total)} · 等级目标合计 ${fmt(d.grade_total)} · 各自可达且可同时达标，权重合计与累计分布已核对到 1，然后一次性切换。</p></div>
  ${matrix('份数分配（整数）',result.origins,result.grades,result.allocated,'合计')}
  ${matrix('实收份数',result.origins,result.grades,result.received,'合计')}
  ${matrix('绝对差 |份数-实收|',result.origins,result.grades,result.allocated.map((r,i)=>r.map((v,j)=>Math.abs(v-result.received[i][j]))),'合计')}
  <h2>${esc('加权经验累积分布')} <small>同格样本平分权重 · 合计 ${fmt(result.total)}</small></h2>
  <div class="chart">${w.points.map(([x,y])=>`<div class="chart-row"><span>${esc(fmt(x))}</span><i style="width:${Math.max(1,Math.min(100,y*100))}%"></i><b>${esc(fmt(y))}</b></div>`).join('')}</div>
  <h2>原始未加权分布 <small>${result.raw.count} 份登记茶样</small></h2>${table(['分位点','未加权值','加权值'],Object.keys(w.quantiles).map(k=>[k,fmt(result.raw.quantiles[k])+'%',fmt(w.quantiles[k])+'%']))}`;
}

export async function render(id){
  const writable=localStorage.getItem('research-role')!=='viewer';
  const rows=await calibrations.list(store.studyId||undefined);
  const active=store.studyId?await calibrations.active(store.studyId).catch(()=>null):null;
  let detail='';
  const current=id?await calibrations.get(id):(rows.find(r=>r.active)||rows[0]);
  const detailRow=current?await calibrations.get(current.id):null;
  if(detailRow)detail=`<h2>申请 #${detailRow.id} ${esc(current.name)} ${state(current.status)} ${current.active?'<span class="status completed">生效中</span>':''}</h2>
    <div class="checksum">INPUT SHA256 ${detailRow.checksum}</div>
    <p>${esc(detailRow.created_at)} · 快照 ${detailRow.snapshot.length} 份 · 目标 ${JSON.stringify(detailRow.origin_targets)} / ${JSON.stringify(detailRow.grade_targets)}</p>
    ${summary(detailRow)}`;
  return `<div class="eyebrow">06 / CALIBRATION WORKSHEET</div><h1>产地与等级校准</h1>
  <p class="lead">收样偏向部分产地和等级时，冻结茶样与两套目标份数，求整数份数使两轴同时达标且与实收的绝对差之和最小，查看校准后的含水率分布。</p>
  <p>当前生效版本：${active?`#${active.id} ${esc(active.name)} · ${esc(active.activated_at)}`:'尚无生效版本'}。</p>
  ${writable?targetsForm():'<p class="method-note">观察员可查看校准与分布；分析师与负责人可以提交目标。</p>'}
  ${detail}
  <h2>校准申请记录</h2>
  ${table(['编号 / 名称','状态','生效','目标合计','动作'],rows.map(r=>[{html:`<a href="#calibration/${r.id}">#${r.id} ${esc(r.name)}</a>`},state(r.status),r.active?'生效中':(r.active_calibration_id?`现生效 #${r.active_calibration_id}`:'—'),fmt(Object.values(r.origin_targets).reduce((a,b)=>a+b,0)),{html:`<a href="#calibration/${r.id}">查看 →</a>`}]))}`;
}

export function bind(refresh){
  bindForm('calibration-form',async data=>{
    const origin_targets={},grade_targets={};
    for(const key of Object.keys(data)){
      if(key.startsWith('origin:'))origin_targets[key.slice(7)]=+data[key];
      if(key.startsWith('grade:'))grade_targets[key.slice(6)]=+data[key];
    }
    const r=await calibrations.create({study_id:+data.study_id,name:data.name,origin_targets,grade_targets});
    await load();
    location.hash='calibration/'+r.id;
  });
  const sel=document.getElementById('study-select');
  if(sel)sel.onchange=()=>{store.studyId=+sel.value;refresh();};
}
