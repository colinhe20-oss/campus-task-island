import {useEffect, useState, type FormEvent} from 'react';
import {request, formatTime, type User} from './api';
import {LoginRequired, MyTasksPage} from './Collaboration';
import './activities.css';
import {useLiveResource,useManagementFocus,LiveFeedback as Feedback} from './live';
import {DiscoveriesPage} from './Discoveries';
import {VolunteerPersonalPage} from './Volunteers';

export const recognitionTags = {second_class:'二课分', aesthetic:'美育分', ideological:'形策二分'} as const;
type Tag = keyof typeof recognitionTags;
const activityStates: Record<string,string> = {not_open:'尚未开放',open:'报名中',full:'满额可候补',closed:'报名结束',cancelled:'已取消'};
const registrationStates: Record<string,string> = {pending:'待审核',registered:'报名成功',waitlisted:'候补中',rejected:'申请被拒绝',cancelled:'已取消报名',activity_cancelled:'活动方取消',not_selected:'未获名额'};
const eventNames: Record<string,string> = {applied:'提交申请',registered:'报名成功',waitlisted:'进入候补',approved:'审核通过',rejected:'审核拒绝',cancelled:'本人取消',activity_cancelled:'活动方取消',promoted:'候补转正',published:'发布活动'};
type Registration = {id:string;activity_id:string;status:string;application_note:string;review_reason:string;created_at:string;updated_at:string;queue_sequence:number|null;waitlist_position:number|null;can_cancel:boolean;user_id?:string;display_name?:string;events:{action:string;reason:string;created_at:string}[]};
type Activity = {id:string;owner_id:string;title:string;description:string;location:string;starts_at:string;ends_at:string;opens_at:string;closes_at:string;capacity:number;registration_mode:'direct'|'review';recognition_tags:Tag[];recognition_description:string;organization_name:string;information_source:string;contact:string;participation_requirements:string;created_at:string;cancelled_at:string|null;cancellation_reason:string|null;registered_count:number;remaining_capacity:number;status:string;is_owner:boolean;can_register:boolean;can_review:boolean;can_cancel_activity:boolean;my_registration:Registration|null;registration_history?:Registration[];server_time:string;next_boundary:string|null};
type Collection = {items:Activity[];total?:number;server_time:string;next_boundary:string|null};
type Roster = {items:Registration[];events:{registration_id:string|null;action:string;reason:string;created_at:string}[];server_time:string;next_boundary:string|null};

function Tags({activity}:{activity:Activity}) {return <div className="recognition-tags">{activity.recognition_tags.map(tag=><span className={`badge recognition-${tag}`} key={tag}>{recognitionTags[tag]}</span>)}</div>;}
function ActivityCard({activity}:{activity:Activity}) {
  return <a className="task-card activity-card" href={`#/activities/${activity.id}`}><div className="card-top"><Tags activity={activity}/><span className="status-dot">{activityStates[activity.status]}</span></div><h2>{activity.title}</h2>
    <p className="card-description">{activity.organization_name} · {activity.location}</p><div className="card-facts"><span>活动时间 <b>{formatTime(activity.starts_at)} — {formatTime(activity.ends_at)}</b></span><span>报名窗口 <b>{formatTime(activity.opens_at)} — {formatTime(activity.closes_at)}</b></span><span>名额 <b>{activity.registered_count} / {activity.capacity} · 剩余 {activity.remaining_capacity} 个</b></span></div>
    <div className="card-footer"><span>{activity.registration_mode==='review'?'审核报名 · 待审核不占名额':'直接报名 · 满额可候补'}</span><span className="card-link">查看活动 ↗</span></div></a>;
}

export function ActivitiesPage({query,user}:{query:URLSearchParams;user:User|null}) {
  const activeKeyword=query.get('q')||'', rawTag=query.get('tag')||'';
  const activeTag=Object.hasOwn(recognitionTags,rawTag)?rawTag:'';
  const rawPage=Number(query.get('page')||1),page=Number.isSafeInteger(rawPage)&&rawPage>0&&rawPage<=100000?rawPage:1;
  const [keyword,setKeyword]=useState(activeKeyword),[tag,setTag]=useState(activeTag);
  useEffect(()=>{setKeyword(activeKeyword);setTag(activeTag);},[activeKeyword,activeTag]);
  const parameters=new URLSearchParams({keyword:activeKeyword,limit:'20',offset:String((page-1)*20)});if(activeTag)parameters.set('tag',activeTag);
  const resource=useLiveResource<Collection>(`/api/activities?${parameters}`);
  function apply(nextPage=1) {const filters=new URLSearchParams();if(keyword.trim())filters.set('q',keyword.trim());if(tag)filters.set('tag',tag);if(nextPage>1)filters.set('page',String(nextPage));const hash=`#/activities${filters.size?'?'+filters:''}`;if(window.location.hash===hash)resource.retry();else window.location.hash=hash;}
  return <><div className="page-heading"><div><p className="eyebrow">报名校园活动</p><h1>综素活动</h1><p className="subheading">查看活动安排、认定说明与报名名额。时间均为北京时间。发布请使用左侧“发布任务”。</p></div></div>
    <form className="filters" onSubmit={e=>{e.preventDefault();apply();}}><label className="search-field"><span>搜索活动</span><input aria-label="搜索活动" maxLength={200} placeholder="搜索活动标题、内容或组织方" value={keyword} onChange={e=>setKeyword(e.target.value)}/></label><label><span>认定标签</span><select aria-label="认定标签筛选" value={tag} onChange={e=>setTag(e.target.value)}><option value="">全部标签</option>{Object.entries(recognitionTags).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><button className="button">查询</button>{(activeKeyword||activeTag)&&<a className="reset-button" href="#/activities">清除筛选</a>}</form>
    <div className="section-heading"><h2>活动安排</h2><span>{resource.data?`共 ${resource.data.total} 场活动`:'二课分 · 美育分 · 形策二分'}</span></div><Feedback {...resource}/>
    {resource.data&&(resource.data.items.length?<><div className="task-grid">{resource.data.items.map(activity=><ActivityCard key={activity.id} activity={activity}/>)}</div>{(resource.data.total||0)>20&&<div className="pagination"><button className="button secondary" disabled={page===1} onClick={()=>apply(page-1)}>上一页</button><span>第 {page} 页</span><button className="button secondary" disabled={page*20>=(resource.data.total||0)} onClick={()=>apply(page+1)}>下一页</button></div>}</>:<div className="state"><strong>{activeKeyword||activeTag?'没有匹配的活动':'暂时没有开放或即将举行的活动'}</strong><p>已结束或取消的活动仍可在个人记录中查看。</p>{(activeKeyword||activeTag)&&<a className="button secondary" href="#/activities">查看全部活动</a>}</div>)}
    <p className="muted">认定标签和说明由活动方公布，报名成功不代表正式认定或学分到账。</p></>;
}

export function PublishActivityPage() {
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();const form=new FormData(event.currentTarget),payload:Record<string,unknown>={};
    const text=(key:string)=>String(form.get(key)||'').trim();
    for(const key of ['title','description','location','recognition_description','organization_name','information_source','contact','participation_requirements','registration_mode'])payload[key]=text(key);
    for(const key of ['opens_at','closes_at','starts_at','ends_at'])payload[key]=(text(key).length===16?text(key)+':00':text(key))+'+08:00';
    payload.capacity=Number(text('capacity'));payload.recognition_tags=form.getAll('recognition_tags');
    if(!(payload.recognition_tags as string[]).length){setError('请选择至少一个认定标签。');return;}
    const times=['opens_at','closes_at','starts_at','ends_at'].map(key=>Date.parse(payload[key] as string));
    if(!(times[0]<times[1]&&times[1]<=times[2]&&times[2]<times[3])){setError('时间须满足：报名开放 < 报名截止 ≤ 活动开始 < 活动结束。');return;}
    setBusy(true);setError('');
    try {const created=await request<Activity>('/api/activities',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});window.location.hash=`#/activities/${created.id}?published=1`;}
    catch(reason){setError(reason instanceof Error?reason.message:'发布失败');}finally{setBusy(false);}
  }
  return <><a className="back-link" href="#/tasks/new">← 重新选择发布种类</a><div className="page-heading"><div><h1>发布综素活动</h1><p className="subheading">所有登录用户均可发布。认定说明由发布者填写，学校正式认定尚未对接；发布后时间、名额与报名方式固定。</p></div></div>
    <form className="publish-form panel" onSubmit={submit}><div className="form-row"><label className="grow">活动标题 *<input name="title" required maxLength={100}/></label><label className="grow">组织方 *<input name="organization_name" required maxLength={200}/></label></div>
      <label>活动说明 *<textarea name="description" required rows={4} maxLength={4000}/></label><label>地点 *<input name="location" required maxLength={200}/></label><label>参与条件 *<textarea name="participation_requirements" required rows={2} maxLength={2000}/></label>
      <div className="form-section separated"><h2>时间与报名</h2><p>所有时间均为北京时间。</p></div><div className="form-row"><label className="grow">报名开放 *<input name="opens_at" required type="datetime-local"/></label><label className="grow">报名截止 *<input name="closes_at" required type="datetime-local"/></label></div><div className="form-row"><label className="grow">活动开始 *<input name="starts_at" required type="datetime-local"/></label><label className="grow">活动结束 *<input name="ends_at" required type="datetime-local"/></label></div>
      <div className="form-row"><label className="grow">名额 *<input name="capacity" type="number" min={1} max={100000} step={1} required/></label><label className="grow">报名方式 *<select name="registration_mode"><option value="direct">直接报名</option><option value="review">审核报名</option></select></label></div>
      <fieldset className="tag-choices"><legend>活动方公布的认定标签 *</legend>{Object.entries(recognitionTags).map(([value,label])=><label key={value}><input type="checkbox" name="recognition_tags" value={value}/>{label}</label>)}</fieldset>
      <label>认定说明 *<textarea name="recognition_description" required rows={3} maxLength={2000} placeholder="填写活动方公布的要求。本站报名不自动增加学分。"/></label><label>信息来源 *<input name="information_source" required maxLength={500} placeholder="例如：主办方公告、社团通知"/></label><label>联系渠道 *<input name="contact" required maxLength={500}/></label>
      {error&&<div className="form-error" role="alert">{error} 填写内容已保留。</div>}<div className="form-actions"><a className="button secondary" href="#/activities">返回活动</a><button className="button" disabled={busy}>{busy?'正在发布…':'确认发布活动'}</button></div></form></>;
}

function Result({registration}:{registration:Registration}) {
  return <div className={`registration-result result-${registration.status}`}><strong>{registrationStates[registration.status]}</strong>{registration.waitlist_position!==null&&<p>你的候补位置：第 {registration.waitlist_position} 位</p>}{registration.status==='pending'&&<p>申请已提交，等待负责人审核，当前不占名额。</p>}{registration.status==='registered'&&registration.events.some(e=>e.action==='promoted')&&<p>已从候补自动转正，你已获得名额。</p>}{registration.review_reason&&<p>{registration.status==='rejected'?'拒绝理由':'处理说明'}：{registration.review_reason}</p>}{registration.status==='not_selected'&&<p>活动已开始，本次申请未获得名额。</p>}</div>;
}
function History({items}:{items:Registration[]}) {return <details className="registration-history"><summary>历史申请与操作记录（{items.length} 次）</summary>{items.map(item=><div className="record" key={item.id}><div className="record-heading"><strong>{registrationStates[item.status]}</strong><span>{formatTime(item.created_at)}</span></div>{item.application_note&&<p>申请说明：{item.application_note}</p>}{item.events.map((event,index)=><p className="muted" key={index}>{formatTime(event.created_at)} · {eventNames[event.action]||event.action}{event.reason&&` · ${event.reason}`}</p>)}</div>)}</details>;}

function useActivityAction(onSuccess:()=>void) {
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  async function perform(url:string,body?:unknown) {
    if(busy)return;setBusy(true);setError('');setNotice('');
    try {await request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});setNotice('操作成功，正在更新最新结果。');onSuccess();}
    catch(reason){setError(reason instanceof Error?reason.message:'操作失败');onSuccess();}finally{setBusy(false);}
  }
  return {busy,error,notice,perform};
}

function ReviewRow({item,canReview,action}:{item:Registration;canReview:boolean;action:ReturnType<typeof useActivityAction>}) {
  const [error,setError]=useState('');
  function review(e:FormEvent<HTMLFormElement>) {e.preventDefault();const form=new FormData(e.currentTarget);const decision=(e.nativeEvent as SubmitEvent).submitter?.getAttribute('value')||'approve';const reason=String(form.get('reason')||'').trim();if(decision==='reject'&&!reason){setError('拒绝申请必须填写理由。');return;}setError('');void action.perform(`/api/registrations/${item.id}/review`,{decision,reason});}
  return <div className="record"><div className="record-heading"><strong>{item.display_name}</strong><span>{registrationStates[item.status]}{item.waitlist_position!==null&&` · 候补第 ${item.waitlist_position} 位`}</span></div>{item.application_note&&<p>申请说明：{item.application_note}</p>}{item.review_reason&&<p>处理说明：{item.review_reason}</p>}{item.status==='pending'&&canReview&&<form onSubmit={review}><label>审核理由（拒绝时必填）<textarea name="reason" rows={2} maxLength={2000}/></label>{error&&<p className="form-error" role="alert">{error}</p>}<div className="action-buttons"><button className="button secondary" value="reject" disabled={action.busy}>拒绝申请</button><button className="button" value="approve" disabled={action.busy}>通过申请</button></div></form>}</div>;
}

function RegistrationManager({activity,onChange}:{activity:Activity;onChange:()=>void}) {
  const roster=useLiveResource<Roster>(`/api/activities/${activity.id}/registrations`);
  useManagementFocus(!!roster.data);
  const action=useActivityAction(()=>{roster.retry();onChange();});
  function cancel(e:FormEvent<HTMLFormElement>){e.preventDefault();const form=new FormData(e.currentTarget);void action.perform(`/api/activities/${activity.id}/cancel`,{reason:String(form.get('reason')||'').trim()});}
  return <section className="detail-section" id="registration-management"><h2>负责人报名管理</h2><p className="muted">审核通过后才占名额；满额时审核通过者进入候补。只展示本活动的名单。</p><Feedback {...roster}/>{action.error&&<p className="form-error" role="alert">{action.error}</p>}{action.notice&&<p className="success-notice" role="status">{action.notice}</p>}
    {roster.data&&(roster.data.items.length?<>{['pending','registered','waitlisted','not_selected','rejected','cancelled','activity_cancelled'].map(status=>{const items=roster.data!.items.filter(i=>i.status===status).sort((a,b)=>status==='waitlisted'?(a.queue_sequence||0)-(b.queue_sequence||0):a.created_at.localeCompare(b.created_at));return items.length?<div className="workspace-section" key={status}><h3>{registrationStates[status]}（{items.length}）</h3>{items.map(item=><ReviewRow key={item.id} item={item} canReview={activity.can_review&&!roster.error} action={action}/>)}</div>:null;})}<details className="registration-history"><summary>活动操作历史</summary>{roster.data.events.map((event,index)=><p className="muted" key={index}>{formatTime(event.created_at)} · {eventNames[event.action]}{event.reason&&` · ${event.reason}`}</p>)}</details></>:<div className="state">暂无报名或申请</div>)}
    {activity.can_cancel_activity&&<form className="publish-form workspace-section" onSubmit={cancel}><h3>取消整场活动</h3><p className="muted">有效报名将显示“活动方取消”，保留历史。取消后无法恢复。</p><label>取消原因 *<textarea name="reason" required rows={2} maxLength={2000}/></label><button className="button secondary" disabled={action.busy||!!roster.error}>确认取消活动</button></form>}</section>;
}

export function ActivityDetailPage({id,user,published}:{id:string;user:User|null;published:boolean}) {
  const resource=useLiveResource<Activity>(`/api/activities/${encodeURIComponent(id)}`);
  const action=useActivityAction(resource.retry),activity=resource.data, registration=activity?.my_registration;
  function register(e?:FormEvent<HTMLFormElement>){e?.preventDefault();const form=e?new FormData(e.currentTarget):null;void action.perform(`/api/activities/${id}/registrations`,{application_note:String(form?.get('application_note')||'').trim()});}
  const seconds=activity?.status==='not_open'?Math.max(0,Math.ceil((Date.parse(activity.opens_at)-resource.serverNow)/1000)):0;
  return <><a className="back-link" href="#/activities">← 返回综素活动</a>{published&&<div className="success-notice">活动发布成功。</div>}<Feedback {...resource}/>
    {activity&&<article className="detail panel activity-detail"><div className="card-top"><Tags activity={activity}/><span className="status-dot">{activityStates[activity.status]}</span></div><h1>{activity.title}</h1><p className="detail-time">{activity.organization_name} · 北京时间</p>
      <dl className="detail-facts"><div><dt>活动时间</dt><dd>{formatTime(activity.starts_at)} — {formatTime(activity.ends_at)}</dd></div><div><dt>地点</dt><dd>{activity.location}</dd></div><div><dt>名额</dt><dd>已报名 {activity.registered_count} / {activity.capacity}<br/>剩余 {activity.remaining_capacity} 个</dd></div><div><dt>报名开放</dt><dd>{formatTime(activity.opens_at)}</dd></div><div><dt>报名截止</dt><dd>{formatTime(activity.closes_at)}</dd></div><div><dt>报名方式</dt><dd>{activity.registration_mode==='direct'?'直接报名':'审核报名'}</dd></div></dl>
      {activity.status==='not_open'&&<div className="info-notice" role="status">距离开放约 {Math.floor(seconds/3600)} 小时 {Math.floor(seconds%3600/60)} 分 {seconds%60} 秒。名额与结果由服务端判断。</div>}
      {activity.cancelled_at&&<div className="form-error">活动方已取消：{activity.cancellation_reason}</div>}
      <section className="detail-section"><h2>活动说明与参与条件</h2><p>{activity.description}</p><p>参与条件：{activity.participation_requirements}</p></section><section className="detail-section"><h2>活动方公布的认定说明</h2><p>{activity.recognition_description}</p><div className="info-notice">报名成功不自动增加学分。正式认定结果以学校或活动主管方公布为准。</div></section>
      <section className="detail-section"><h2>报名与取消规则</h2><p>{activity.registration_mode==='review'?'必填申请说明，待审核不占名额。审核通过时有空位则成功，满额则候补。候补顺序从审核通过并入队时计算。':'开放后有空位即成功，满额进入候补。候补按服务端入队顺序自动递补。'}</p><p>报名截止后不接受新申请；已有申请仍可审核、已有候补仍可递补，直到活动开始。活动开始前可取消本人申请或报名；截止前可重新申请，重新审核或排队。</p></section>
      <section className="detail-section"><h2>{activity.is_owner?'活动管理':'我的报名结果'}</h2>{action.error&&<p className="form-error" role="alert">{action.error}</p>}{action.notice&&<p className="success-notice" role="status">{action.notice}</p>}
        {activity.is_owner?<p className="muted">你是负责人，不能报名自己的活动。</p>:!user?<LoginRequired/>:<>{registration&&<Result registration={registration}/>} {registration?.can_cancel&&<button className="button secondary" disabled={action.busy||!!resource.error} onClick={()=>void action.perform(`/api/registrations/${registration.id}/cancel`)}>取消报名</button>}
          {activity.can_register&&(activity.registration_mode==='review'?<form className="publish-form workspace-section" onSubmit={register}><label>申请说明 *<textarea name="application_note" required rows={3} maxLength={2000} placeholder="说明你符合的参与条件与报名原因"/></label><button className="button" disabled={action.busy||!!resource.error}>提交申请</button></form>:<button className="button" disabled={action.busy||!!resource.error} onClick={()=>register()}>{activity.status==='full'?'加入候补':'报名'}</button>)}
          {!registration&&!activity.can_register&&<p className="muted">{activity.status==='not_open'?'尚未开放报名':activity.status==='cancelled'?'活动已取消':'报名已经结束'}</p>}</>}
      </section>{activity.is_owner&&<RegistrationManager activity={activity} onChange={resource.retry}/>}
      <section className="detail-section"><h2>信息来源与联系渠道</h2><p>信息来源：{activity.information_source}</p><p>联系渠道：{activity.contact}</p></section><p className="muted">页面可见时每 15 秒更新名额和结果。活动编号：{activity.id}</p>
    </article>}</>;
}

export function MySpacePage({user,path,query}:{user:User;path:string;query:URLSearchParams}) {
  const volunteer=query.get('type')==='volunteer';
  return <><div className="my-tabs space-tabs"><a className={path==='/mine'?'selected':''} href="#/mine">普通任务</a><a className={path==='/mine/registrations'?'selected':''} href="#/mine/registrations">我的报名</a><a className={path==='/mine/volunteer-records'?'selected':''} href="#/mine/volunteer-records">我的志愿记录</a><a className={path==='/mine/discoveries'?'selected':''} href="#/mine/discoveries">我的发现</a><a className={path==='/mine/activities'?'selected':''} href="#/mine/activities">我发布的活动</a></div>
    {(path==='/mine/registrations'||path==='/mine/activities')&&<div className="content-type-tabs"><a className={!volunteer?'selected':''} href={`#${path}`}>综素活动</a><a className={volunteer?'selected':''} href={`#${path}?type=volunteer`}>志愿服务</a></div>}
    {path==='/mine/discoveries'?<DiscoveriesPage mine query={query}/>:path==='/mine'?<MyTasksPage user={user}/>:path==='/mine/volunteer-records'?<VolunteerPersonalPage kind="records"/>:path==='/mine/registrations'?volunteer?<VolunteerPersonalPage kind="registrations"/>:<MyRegistrationsPage/>:volunteer?<VolunteerPersonalPage kind="activities"/>:<MyActivitiesPage/>}</>;
}
function MyRegistrationsPage() {
  const resource=useLiveResource<Collection>('/api/me/registrations');
  return <><div className="page-heading"><div><h1>我的报名</h1><p className="subheading">每场活动展示最新结果，旧申请和操作记录保留。</p></div></div><Feedback {...resource}/>{resource.data&&(resource.data.items.length?<div className="my-task-list">{resource.data.items.map(activity=><section className="panel" key={activity.id}><a href={`#/activities/${activity.id}`}><h2>{activity.title} ↗</h2><p className="muted">{formatTime(activity.starts_at)} · {activity.location}</p></a>{activity.my_registration&&<Result registration={activity.my_registration}/>}<History items={activity.registration_history||[]}/></section>)}</div>:<div className="state"><strong>暂时没有报名记录</strong><a className="button secondary" href="#/activities">浏览综素活动</a></div>)}</>;
}
function MyActivitiesPage() {
  const resource=useLiveResource<Collection>('/api/me/activities');
  return <><div className="page-heading"><div><h1>我发布的活动</h1><p className="subheading">包括已结束与已取消的活动，进入详情查看报名管理。发布请使用左侧“发布任务”。</p></div></div><Feedback {...resource}/>{resource.data&&(resource.data.items.length?<div className="task-grid">{resource.data.items.map(activity=><ActivityCard key={activity.id} activity={activity}/>)}</div>:<div className="state"><strong>暂时没有发布活动</strong></div>)}</>;
}
