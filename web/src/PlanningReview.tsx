import {useState} from 'react';
import {request} from './api';
import {FieldEditor,type Assistance,type Plan,type Fields} from './Assistance';

const pretty=(value:unknown):string=>value===null||value===undefined?'未设置':Array.isArray(value)?value.map(pretty).join('\n\n'):typeof value==='object'?Object.entries(value).map(([k,v])=>`${translate(k)}：${pretty(v)}`).join('\n'):String(value);
const fieldNames:Record<string,string>={title:'活动名称',description:'活动内容',starts_at:'开始时间',ends_at:'结束时间',opens_at:'报名开放时间',closes_at:'报名截止时间',capacity:'人数',location:'地点',contact:'联系方式',requirements:'岗位要求',estimated_minutes:'预计服务分钟',target_volunteers:'计划招募人数',name:'岗位名称',organization_name:'组织名称',information_source:'信息来源',recognition_conditions:'服务认定条件',registration_mode:'报名方式',jobs:'岗位'};
function translate(text:string){return Object.entries(fieldNames).sort((a,b)=>b[0].length-a[0].length).reduce((v,[key,label])=>v.replaceAll(key,label),text.replace(/^fields\./,''));}
export function PlanningReview({plan,conversation,version,disabled,onChange,onReview}:{plan:Plan;conversation:string;version:number;disabled:boolean;onChange:(v:Assistance)=>void;onReview:()=>void}){
 const [working,setWorking]=useState(false),[error,setError]=useState(''),[editing,setEditing]=useState<string|null>(null),[patch,setPatch]=useState<Fields>({}),[target,setTarget]=useState<number|null>(null);
 async function decide(id:string,decision:string,fields?:Fields,targetValue?:number|null){setWorking(true);setError('');try{
   onChange(await request<Assistance>(`/api/guide/assistance/${conversation}/proposals/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,decision,...(fields?{fields}:{}),...(targetValue!==undefined?{target_volunteers:targetValue}:{})})}));setEditing(null);
 }catch(e){setError(e instanceof Error?e.message:'操作失败');}finally{setWorking(false);}}
 const review=plan.review;const busy=working||disabled||plan.status!=='draft';
 return <section className="planning-review" aria-label="方案检查与修改影响">
  <div className="section-heading"><h4>方案检查</h4><button type="button" className="button secondary" disabled={busy} onClick={onReview}>让引航员评估方案</button></div>
  {plan.checks?.length?<ul className="plan-blockers">{plan.checks.map((r,i)=><li key={i}><strong>需修复</strong> {translate(r.message)}</li>)}</ul>:<p>当前已填字段通过发布规则检查。可进一步评估执行安排。</p>}
  {!!plan.changes?.length&&<details open className="plan-changes"><summary>本次修改 {plan.changes.length} 项</summary>{plan.changes.map((c,i)=><div className="plan-difference" key={i}><strong>{translate(c.label||c.path)}</strong><div><span>修改前</span><pre>{pretty(c.before)}</pre></div><div><span>修改后</span><pre>{pretty(c.after)}</pre></div></div>)}<p className="guide-intro">未列出的字段未自动联动。需要调整关联岗位、报名窗口或筹备安排时，请明确修改或采纳建议。</p></details>}
  {!!plan.impacts?.length&&<><h4>确定影响</h4><ul>{plan.impacts.map((i,n)=><li key={n}>{translate(i.message)}</li>)}</ul></>}
  {review&&<div className="plan-ai-review"><h4>AI 规划建议{review.stale?' · 已过期':''}</h4>
   {!!review.questions.length&&<><strong>待确认条件</strong><ul>{review.questions.map((q,i)=><li key={i}>{q}</li>)}</ul></>}
   {!!review.rechecks.length&&<><strong>建议复核</strong><ul>{review.rechecks.map((q,i)=><li key={i}>{q}</li>)}</ul></>}
   {review.proposals.map(p=><article className="plan-proposal" key={p.id}><h4>{p.title} {p.status==='rejected'?'· 已拒绝':''}</h4><p>{p.reason}</p><details><summary>建议依据</summary>{p.evidence.map((e,i)=><p key={i}>{translate(e.path)}：{pretty(e.value)}</p>)}</details>
    {p.target_volunteers!=null&&<p>拟调整计划招募总人数：{p.target_volunteers} 名志愿者</p>}<details><summary>拟修改的字段</summary><dl>{Object.entries(p.fields).map(([key,value])=><div key={key}><dt>{translate(key)}</dt><dd><pre>{pretty(value)}</pre></dd></div>)}</dl></details>
    {editing===p.id&&<div>{p.target_volunteers!=null&&<label>建议招募总人数<input type="number" min="1" value={target??''} onChange={e=>setTarget(e.target.value?Number(e.target.value):null)}/></label>}<FieldEditor keys={Object.keys(patch).filter(k=>k!=='jobs')} fields={patch} onChange={setPatch}/>{Array.isArray(patch.jobs)&&(patch.jobs as Fields[]).map((job,i)=><div className="plan-job" key={i}><h4>建议岗位 {i+1}</h4><FieldEditor keys={Object.keys(job)} fields={job} onChange={next=>setPatch({...patch,jobs:(patch.jobs as Fields[]).map((x,n)=>n===i?next:x)})}/></div>)}</div>}
    <div className="draft-actions"><button disabled={busy||review.stale||p.status!=='pending'} className="text-button" onClick={()=>void decide(p.id,'reject')}>拒绝</button><button disabled={busy||review.stale||p.status!=='pending'} className="button secondary" onClick={()=>{setEditing(p.id);setPatch(p.fields);setTarget(p.target_volunteers??null);}}>编辑建议</button><button disabled={busy||review.stale||p.status!=='pending'} className="button" onClick={()=>void decide(p.id,'accept',editing===p.id?patch:undefined,editing===p.id&&p.target_volunteers!=null?target:undefined)}>{editing===p.id?'采纳编辑后的建议':'采纳到草稿'}</button></div>
   </article>)}<p className="guide-intro">采纳会更新草稿并重新校验，其他旧建议随版本变化失效；正式发布仍需单独确认。</p></div>}
  {error&&<p className="form-error" role="alert">{error}</p>}
 </section>;
}
