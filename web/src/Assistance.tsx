import {useEffect,useState} from 'react';
import {request,formatTime} from './api';
import './assistance.css';
import {PlanningReview} from './PlanningReview';
import {SemanticProfile} from './SemanticProfile';

export type Fields=Record<string,unknown>;
export type Plan={kind:'volunteer'|'activity';fields:Fields;status:string;ready:boolean;issues:string[];suggestions?:string[];checklist?:string[];href?:string;
 target_volunteers?:number|null;job_ids?:string[];checks?:{code:string;message:string;path:string}[];impacts?:{message:string}[];changes?:{path:string;label:string;before:unknown;after:unknown}[];
 review?:{base_version:number;stale?:boolean;questions:string[];rechecks:string[];proposals:{id:string;title:string;reason:string;evidence:{path:string;value:unknown}[];fields:Fields;target_volunteers?:number|null;status:string}[]}|null};
export type Assistance={conversation_id:string;version:number;plan:Plan|null;preference_proposal:{fields:Profile;base_version:number}|null};
type Slot={starts_at:string;ends_at:string};
type Weekly={weekday:number;starts:string;ends:string};
type Profile={skills:string[];interests:string[];locations:string[];available_slots:Slot[];unavailable_slots:Slot[];weekly_slots:Weekly[];valid_until:string|null;content_types:string[];notifications_enabled:boolean};
type SavedProfile={version:number;fields:Profile;confirmed_at:string|null};
type Opportunity={id:number;title:string;subtitle:string;location:string;starts_at:string|null;ends_at:string|null;score:number;href:string;reasons:string[];checks:string[];server_time:string;matching_method?:string;semantic_evidence?:{label:string;profile_quote:string;opportunity_quote:string}[]};
type Recommendations={items:Opportunity[];total:number;last_checked_at:string|null;error:string|null};
const labels:Record<string,string>={title:'活动名称',description:'活动内容',organization_name:'组织名称',information_source:'信息来源',contact:'联系方式',recognition_conditions:'志愿服务认定条件',starts_at:'开始时间',ends_at:'结束时间',opens_at:'报名开放时间',closes_at:'报名截止时间',registration_mode:'报名方式',location:'地点',capacity:'招募人数',recognition_tags:'认定类型',recognition_description:'认定说明',participation_requirements:'参与条件',name:'岗位名称',requirements:'岗位要求',estimated_minutes:'预计服务分钟',estimated_hours_description:'预计服务时长说明'};
const volunteerKeys=['title','description','organization_name','information_source','contact','recognition_conditions','starts_at','ends_at','opens_at','closes_at','registration_mode'];
const activityKeys=['title','description','location','starts_at','ends_at','opens_at','closes_at','capacity','registration_mode','recognition_tags','recognition_description','organization_name','information_source','contact','participation_requirements'];
const jobKeys=['name','description','requirements','location','starts_at','ends_at','capacity','estimated_minutes','estimated_hours_description'];
const local=(value:unknown)=>{if(typeof value!=='string'||!value)return '';const date=new Date(value);if(!Number.isFinite(date.getTime()))return '';return new Date(date.getTime()+8*3600000).toISOString().slice(0,16);};
const iso=(value:string)=>value?value+':00+08:00':null;
function ListInput({value,onChange}:{value:string[];onChange:(v:string[])=>void}){
  const [text,setText]=useState(value.join('、'));
  const serialized=value.join('、');
  useEffect(()=>setText(serialized),[serialized]);
  return <input value={text} placeholder="使用顿号或逗号分隔" onChange={e=>setText(e.target.value)} onBlur={()=>onChange(text.split(/[、,，]/).map(s=>s.trim()).filter(Boolean))}/>;
}
export function FieldEditor({keys,fields,onChange}:{keys:string[];fields:Fields;onChange:(next:Fields)=>void}){
  return <div className="assistance-fields">{keys.map(key=><label key={key}>{labels[key]||key}
    {key==='registration_mode'?<select value={String(fields[key]||'')} onChange={e=>onChange({...fields,[key]:e.target.value})}><option value="">请选择</option><option value="direct">直接报名</option><option value="review">审核报名</option></select>
    :key==='recognition_tags'?<div className="assistance-checks">{Object.entries({second_class:'二课分',aesthetic:'美育分',ideological:'形策二分'}).map(([tag,label])=><label key={tag}><input type="checkbox" checked={(fields[key] as string[]||[]).includes(tag)} onChange={e=>onChange({...fields,[key]:e.target.checked?[...(fields[key] as string[]||[]),tag]:(fields[key] as string[]||[]).filter(v=>v!==tag)})}/>{label}</label>)}</div>
    :key.endsWith('_at')?<input type="datetime-local" value={local(fields[key])} onChange={e=>onChange({...fields,[key]:iso(e.target.value)})}/>
    :['capacity','estimated_minutes'].includes(key)?<input type="number" min="1" value={fields[key] as number??''} onChange={e=>onChange({...fields,[key]:e.target.value?Number(e.target.value):null})}/>
    :<textarea rows={['description','requirements','participation_requirements'].includes(key)?3:1} value={String(fields[key]||'')} onChange={e=>onChange({...fields,[key]:e.target.value||null})}/>}
  </label>)}</div>;
}
function ProfileEditor({value,onChange}:{value:Profile;onChange:(p:Profile)=>void}){
  const list=(key:'skills'|'interests'|'locations',label:string)=><label>{label}<ListInput value={value[key]} onChange={next=>onChange({...value,[key]:next})}/></label>;
  const slots=(key:'available_slots'|'unavailable_slots',label:string)=><div><strong>{label}</strong>{value[key].map((slot,index)=><div className="slot-row" key={index}><input aria-label={`${label}开始`} type="datetime-local" value={local(slot.starts_at)} onChange={e=>onChange({...value,[key]:value[key].map((s,i)=>i===index?{...s,starts_at:iso(e.target.value)||''}:s)})}/><span>至</span><input aria-label={`${label}结束`} type="datetime-local" value={local(slot.ends_at)} onChange={e=>onChange({...value,[key]:value[key].map((s,i)=>i===index?{...s,ends_at:iso(e.target.value)||''}:s)})}/><button type="button" className="text-button" onClick={()=>onChange({...value,[key]:value[key].filter((_,i)=>i!==index)})}>移除</button></div>)}<button type="button" className="text-button" onClick={()=>onChange({...value,[key]:[...value[key],{starts_at:'',ends_at:''}]})}>添加{label}</button></div>;
  return <div className="profile-editor"><div className="assistance-fields">{list('skills','自述技能与熟练程度')}{list('interests','兴趣方向')}{list('locations','优先地点')}</div>
    <div><strong>每周空闲时段（北京时间）</strong>{value.weekly_slots.map((slot,index)=><div className="slot-row" key={index}><select aria-label="星期" value={slot.weekday} onChange={e=>onChange({...value,weekly_slots:value.weekly_slots.map((s,i)=>i===index?{...s,weekday:Number(e.target.value)}:s)})}>{['周一','周二','周三','周四','周五','周六','周日'].map((s,i)=><option key={i} value={i}>{s}</option>)}</select><input aria-label="每周开始" type="time" value={slot.starts} onChange={e=>onChange({...value,weekly_slots:value.weekly_slots.map((s,i)=>i===index?{...s,starts:e.target.value}:s)})}/><span>至</span><input aria-label="每周结束" type="time" value={slot.ends} onChange={e=>onChange({...value,weekly_slots:value.weekly_slots.map((s,i)=>i===index?{...s,ends:e.target.value}:s)})}/><button type="button" className="text-button" onClick={()=>onChange({...value,weekly_slots:value.weekly_slots.filter((_,i)=>i!==index)})}>移除</button></div>)}<button type="button" className="text-button" onClick={()=>onChange({...value,weekly_slots:[...value.weekly_slots,{weekday:5,starts:'14:00',ends:'17:00'}]})}>添加每周时段</button></div>
    {slots('available_slots','一次性空闲时段')}{slots('unavailable_slots','不可参与时段')}
    <label>偏好有效至（可留空）<input type="datetime-local" value={local(value.valid_until)} onChange={e=>onChange({...value,valid_until:iso(e.target.value)})}/></label>
    <div className="assistance-checks">{Object.entries({volunteer:'志愿服务',activity:'综素活动',ordinary:'普通互助'}).map(([key,label])=><label key={key}><input type="checkbox" checked={value.content_types.includes(key)} onChange={e=>onChange({...value,content_types:e.target.checked?[...value.content_types,key]:value.content_types.filter(s=>s!==key)})}/>{label}</label>)}</div>
    <label className="consent"><input type="checkbox" checked={value.notifications_enabled} onChange={e=>onChange({...value,notifications_enabled:e.target.checked})}/>授权保存以上偏好，并持续匹配、通过站内消息提醒新机会</label>
  </div>;
}

export function AssistancePanel({value,onChange,disabled,onPrompt,onReview}:{value:Assistance|null;onChange:(v:Assistance)=>void;disabled:boolean;onPrompt:(message:string)=>void;onReview:()=>void}){
  const [profile,setProfile]=useState<SavedProfile|null>(null);
  const [editing,setEditing]=useState<Profile|null>(null);
  const [editingVersion,setEditingVersion]=useState(0);
  const [planFields,setPlanFields]=useState<Fields>({});
  const [target,setTarget]=useState<number|null>(null);
  const [jobIds,setJobIds]=useState<string[]>([]);
  const [opportunities,setOpportunities]=useState<Recommendations|null>(null);
  const [error,setError]=useState('');const [working,setWorking]=useState(false);
  async function load(){try{const [p,r]=await Promise.all([request<SavedProfile>('/api/guide/preferences'),request<Recommendations>('/api/guide/recommendations')]);setProfile(p);setOpportunities(r);}catch(e){setError(e instanceof Error?e.message:'加载失败');}}
  useEffect(()=>{void load();const timer=setInterval(()=>void load(),10000);return()=>clearInterval(timer);},[]);
  useEffect(()=>{setPlanFields(value?.plan?.fields||{});setTarget(value?.plan?.target_volunteers??null);setJobIds(value?.plan?.job_ids||[]);},[value?.version,value?.conversation_id]);
  useEffect(()=>{if(value?.preference_proposal){setEditing(value.preference_proposal.fields);setEditingVersion(value.preference_proposal.base_version);}},[value?.version,value?.conversation_id]);
  async function execute(fn:()=>Promise<void>){setWorking(true);setError('');try{await fn();await load();}catch(e){setError(e instanceof Error?e.message:'操作失败');}finally{setWorking(false);}}
  async function confirm(action:string){if(!value)return;await execute(async()=>onChange(await request<Assistance>(`/api/guide/assistance/${value.conversation_id}/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:value.version,profile_version:value.preference_proposal?.base_version})})));}
  async function savePlan(){if(!value)return;await execute(async()=>onChange(await request<Assistance>(`/api/guide/assistance/${value.conversation_id}/plan`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:value.version,target_volunteers:target,clear_target:target===null,job_ids:jobIds,fields:Object.fromEntries(Object.entries(planFields).filter(([,v])=>v!==null))})})));}
  function moveJob(index:number){if(index<1)return;const jobs=[...((planFields.jobs||[]) as Fields[])],ids=[...jobIds];[jobs[index-1],jobs[index]]=[jobs[index],jobs[index-1]];[ids[index-1],ids[index]]=[ids[index],ids[index-1]];setPlanFields({...planFields,jobs});setJobIds(ids);}
  const busy=working||disabled;
  const plan=value?.plan;
  return <section className="assistance-panel" aria-label="活动筹备与参与助手">
    <details className="preferences-panel" open={Boolean(value?.preference_proposal)||Boolean(editing)}><summary>我的参与偏好 {profile?.confirmed_at?'· 已保存':'· 尚未登记'}{value?.preference_proposal?' · 有待确认草稿':''}</summary>
      <p className="guide-intro">技能为本人自述。偏好仅用于本人机会匹配，可随时编辑或关闭提醒；一次性与每周空闲分开保存。未登记时间时，推荐会提示核对。</p>
      {!editing&&profile&&<><p>技能：{profile.fields.skills.join('、')||'未设置'} · 兴趣：{profile.fields.interests.join('、')||'未设置'} · 提醒：{profile.fields.notifications_enabled?'已开启':'已关闭'}</p><button className="button secondary" disabled={busy} onClick={()=>{setEditing(profile.fields);setEditingVersion(profile.version);}}>编辑参与偏好</button></>}
      {editing&&<><fieldset disabled={busy}><ProfileEditor value={editing} onChange={setEditing}/></fieldset><div className="draft-actions"><button className="text-button" disabled={busy} onClick={()=>setEditing(null)}>收起编辑</button><button className="button" disabled={busy||!profile} onClick={()=>void execute(async()=>{
        const proposal=value?.preference_proposal;
        if(proposal&&JSON.stringify(editing)===JSON.stringify(proposal.fields)){onChange(await request<Assistance>(`/api/guide/assistance/${value!.conversation_id}/preferences`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:value!.version,profile_version:proposal.base_version})}));}
        else {setProfile(await request<SavedProfile>('/api/guide/preferences',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:editingVersion,fields:editing})}));if(value)onChange(await request<Assistance>(`/api/guide/assistance/${value.conversation_id}`));}
        setEditing(null);
      })}>核对并保存偏好{editing.notifications_enabled?'与提醒授权':''}</button></div></>}
      <SemanticProfile disabled={busy} onChanged={()=>void load()}/>
    </details>
    <div className="section-heading"><div><p className="eyebrow">从活动构想到参与机会</p><h2>筹备与发现</h2></div></div>
    <div className="assistance-start"><button disabled={busy} className="button secondary" onClick={()=>onPrompt('我想筹备一次志愿活动，请先帮我明确需求，再形成招募方案和筹备清单。')}>筹备志愿活动</button><button disabled={busy} className="button secondary" onClick={()=>onPrompt('我想组织一次综素活动，请帮我规划招募方案。')}>筹备综素活动</button><button disabled={busy} className="button secondary" onClick={()=>onPrompt('请根据我的已保存偏好寻找适合我的参与机会，并解释推荐原因。')}>寻找参与机会</button><button disabled={busy} className="text-button" onClick={()=>onPrompt('我想登记或修改我的技能、兴趣和空闲时间，请帮我整理偏好草稿。')}>对话登记偏好</button></div>
    {error&&<p className="form-error" role="alert">{error}<button onClick={()=>void load()} className="text-button">重新加载</button></p>}
    {plan&&<section className="activity-plan"><div className="section-heading"><h3>{plan.kind==='volunteer'?'志愿服务':'综素活动'}方案 · {plan.status==='published'?'已发布':plan.status==='cancelled'?'已取消':'待核对'}</h3><span>版本 {value!.version}</span></div>
      <fieldset disabled={busy||plan.status!=='draft'}>{plan.kind==='volunteer'&&<label className="target-volunteers">计划招募志愿者总人数（可留空）<input type="number" min="1" value={target??''} onChange={e=>setTarget(e.target.value?Number(e.target.value):null)}/></label>}<FieldEditor keys={plan.kind==='volunteer'?volunteerKeys:activityKeys} fields={planFields} onChange={setPlanFields}/>
      {plan.kind==='volunteer'&&<div className="plan-jobs"><h4>志愿岗位</h4>{((planFields.jobs||[]) as Fields[]).map((job,index)=><div className="plan-job" key={jobIds[index]||index}><h4>岗位 {index+1}</h4>{index>0&&<button type="button" className="text-button" onClick={()=>moveJob(index)}>上移此岗位</button>}<FieldEditor keys={jobKeys} fields={job} onChange={next=>setPlanFields({...planFields,jobs:(planFields.jobs as Fields[]).map((j,i)=>i===index?next:j)})}/><button type="button" className="text-button" onClick={()=>{setPlanFields({...planFields,jobs:(planFields.jobs as Fields[]).filter((_,i)=>i!==index)});setJobIds(jobIds.filter((_,i)=>i!==index));}}>移除此岗位</button></div>)}<button className="text-button" onClick={()=>{setPlanFields({...planFields,jobs:[...((planFields.jobs||[]) as Fields[]),{}]});setJobIds([...jobIds,'']);}}>添加岗位</button></div>}
      </fieldset>
      <PlanningReview plan={plan} version={value!.version} conversation={value!.conversation_id} disabled={busy||JSON.stringify(planFields)!==JSON.stringify(plan.fields)||target!==(plan.target_volunteers??null)} onChange={onChange} onReview={onReview}/>
      {!!plan.suggestions?.length&&<><h4>待确认的规划建议</h4><ul>{plan.suggestions.map((s,i)=><li key={i}>{s}</li>)}</ul><p className="guide-intro">采纳建议后，请在上方字段填写或通过对话确认。</p></>}
      {!!plan.checklist?.length&&<><h4>筹备清单</h4><ol>{plan.checklist.map((s,i)=><li key={i}>{s}</li>)}</ol></>}
      {plan.status==='draft'&&<><details><summary>待补全或核对 {plan.issues.length} 项</summary><ul>{plan.issues.map((s,i)=><li key={i}>{Object.entries(labels).reduce((v,[k,label])=>v.replaceAll(k,label),s)}</li>)}</ul></details><div className="draft-actions"><button className="button secondary" disabled={busy} onClick={()=>void savePlan()}>保存表单修改</button><button className="text-button" disabled={busy} onClick={()=>void confirm('cancel')}>取消方案</button><button className="button" disabled={busy||!plan.ready||(JSON.stringify(planFields)!==JSON.stringify(plan.fields)||target!==(plan.target_volunteers??null))} onClick={()=>void confirm('publish')}>核对并确认发布</button></div><p className="guide-intro">正式发布前请保存修改并核对时间、岗位与认定条件。所有时间均为北京时间。</p></>}
      {plan.href&&<a className="button" href={plan.href}>查看活动与报名状态 ↗</a>}
    </section>}
    <section className="opportunities"><div className="section-heading"><h3>适合我的机会</h3><button disabled={busy} className="text-button" onClick={()=>void execute(async()=>setOpportunities(await request<Recommendations>('/api/guide/recommendations/refresh',{method:'POST'})))}>重新匹配</button></div>
      {opportunities?.error&&<p role="alert">{opportunities.error}</p>}
      {!opportunities?.items.length&&<p className="guide-empty">暂时没有匹配机会。可先登记技能、兴趣和空闲时间；后台会持续关注新发布的内容。</p>}
      {opportunities?.items.map(item=><article key={item.id} className="opportunity"><h4><a href={item.href}>{item.title} ↗</a></h4><p>{item.subtitle} · {item.location} · {item.starts_at?formatTime(item.starts_at):'协作时段待协商'}</p><small>{item.matching_method==='semantic_tags'?'语义标签匹配':'关键词匹配 · 语义整理未完成'}</small><strong>为什么推荐</strong><ul>{item.reasons.map((s,i)=><li key={i}>{s}</li>)}</ul><details><summary>参与前需核对</summary><ul>{item.checks.map((s,i)=><li key={i}>{s}</li>)}</ul></details><small>数据查询于 {formatTime(item.server_time)}</small><div className="draft-actions"><a className="button secondary" href={item.href}>查看并自主报名</a><button disabled={busy} className="text-button" onClick={()=>void execute(async()=>{await request(`/api/guide/recommendations/${item.id}/dismiss`,{method:'POST'});})}>不再推荐此机会</button><button disabled={busy} className="text-button" onClick={()=>onPrompt(`请查询并解释推荐机会“${item.title}”，核对当前名额、参与条件及我的报名状态。`)}>让引航员解释</button></div></article>)}
      {opportunities?.last_checked_at&&<p className="guide-intro">最近匹配：{formatTime(opportunities.last_checked_at)} · 新机会提醒可在<a href="#/messages">站内消息</a>查看。</p>}
    </section>
  </section>;
}
