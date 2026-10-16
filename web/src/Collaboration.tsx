import {AgreementLink} from './changes';
import {useEffect,useState,type FormEvent} from 'react';
import {applicationLabels,type ApplicationRequirements,request,statusNames,formatTime,type User,type Task,type Workspace,type MyTasks} from './api';
import {useResource} from './hooks';
import {StagesPanel} from './Stages';
import {newClientId} from './ids';

export function useAuth() {
  const [user,setUser]=useState<User|null>(null);
  const [loading,setLoading]=useState(true);
  useEffect(()=>{
    const controller=new AbortController();
    request<User>('/api/auth/me',{signal:controller.signal}).then(value=>{if(!controller.signal.aborted)setUser(value);})
      .catch(()=>{}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[]);
  return {user,setUser,loading};
}

export function LoginRequired() {
  return <div className="state"><strong>登录后继续协作</strong><p>登录后可以参与任务协作、报名活动和查看个人记录。</p><a className="button" href={`#/login?next=${encodeURIComponent(window.location.hash.slice(1)||'/home')}`}>前往登录</a></div>;
}

export function LoginPage({onLogin,next}:{onLogin:(user:User)=>void;next:string}) {
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();const form=new FormData(event.currentTarget);setBusy(true);setError('');
    try {
      const user=await request<User>('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:String(form.get('username')||'').trim(),password:form.get('password')})});
      onLogin(user);window.location.hash=/^\/(home|messages|tasks|activities|volunteers|discoveries|mine|guide)(\/|\?|$)/.test(next)?next:'/home';
    }catch(reason){setError(reason instanceof Error?reason.message:'登录失败');}finally{setBusy(false);}
  }
  return <><div className="page-heading"><div><p className="eyebrow">开启一次校园协作</p><h1>登录</h1><p className="subheading">登录后继续查看个人记录、参与活动或使用引航员。</p></div></div>
    <form className="panel publish-form login-form" onSubmit={submit}><label>账号<input name="username" required maxLength={80} autoComplete="username" placeholder="例如：publisher"/></label>
      <label>密码<input name="password" type="password" required maxLength={200} autoComplete="current-password"/></label>
      {error&&<div className="form-error" role="alert">{error}</div>}<button className="button" disabled={busy}>{busy?'正在登录…':'登录'}</button>
      <p className="muted">还没有账号？<a className="result-link" href="#/register">注册普通账号</a></p></form></>;
}

function useAction(onSuccess:()=>void,onFailure?:()=>void) {
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function perform(url:string,payload?:unknown) {
    setBusy(true);setError('');
    try {await request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:payload===undefined?undefined:JSON.stringify(payload)});onSuccess();return true;}
    catch(reason){setError(reason instanceof Error?reason.message:'操作失败');onFailure?.();return false;}
    finally{setBusy(false);}
  }
  return {busy,error,setError,perform};
}

export function CollaborationPanel({task,user,onChange}:{task:Task;user:User|null;onChange:()=>void}) {
  const workspace=useResource<Workspace>(user?`/api/tasks/${task.id}/workspace`:null,true);
  const [notice,setNotice]=useState('');
  const [requestId,setRequestId]=useState(newClientId);
  const action=useAction(()=>{setNotice('操作成功，协作进度已更新。');workspace.retry();onChange();},()=>{workspace.retry();onChange();});
  const owner=user?.id===task.publisher_id;
  const assignee=user?.id===task.assignee_id;
  const myAttempts=workspace.data?.applications.filter(a=>a.applicant_id===user?.id)||[];
  const myApplication=myAttempts.find(a=>a.status==='pending'||a.status==='accepted');
  const latestAttempt=myAttempts[0];
  function apply(event:FormEvent<HTMLFormElement>) {event.preventDefault();const form=new FormData(event.currentTarget);
    for(const [key,label] of Object.entries(applicationLabels)) {
      if(task.application_requirements[key as keyof ApplicationRequirements]==='required'&&!String(form.get(key)||'').trim()){action.setError(`请填写${label}`);return;}
    }
    void action.perform(`/api/tasks/${task.id}/${task.acceptance_mode==='direct'?'claim':'applications'}`,{...Object.fromEntries(Object.keys(applicationLabels).map(key=>[key,String(form.get(key)||'').trim()])),...(task.acceptance_mode==='direct'?{confirmed:form.get('confirmed')==='on'}:{request_id:requestId})}).then(ok=>{if(ok)setRequestId(newClientId());});}
  function submit(event:FormEvent<HTMLFormElement>) {event.preventDefault();const form=new FormData(event.currentTarget);
    void action.perform(`/api/tasks/${task.id}/submissions`,{summary:String(form.get('summary')||'').trim(),collaboration_version:task.collaboration_version});}
  function review(event:FormEvent<HTMLFormElement>) {event.preventDefault();const form=new FormData(event.currentTarget);
    const decision=(event.nativeEvent as SubmitEvent).submitter?.getAttribute('value')||'accept';
    const feedback=String(form.get('feedback')||'').trim();
    if(decision==='request_changes'&&!feedback){action.setError('请说明需要补充或修改的内容。');return;}
    void action.perform(`/api/tasks/${task.id}/review`,{decision,feedback,collaboration_version:task.collaboration_version});}
  return <section className="collaboration"><h2>任务协作</h2>
    {!['withdrawn','cancelled','paused'].includes(task.status)&&<div className="progress-steps">{['published','in_progress','pending_review','completed'].map((value,index)=><span className={task.status===value?'current':''} key={value}>{index+1} · {statusNames[value]}</span>)}</div>}
    <p className="collaboration-person">发布者：{task.publisher_name||'未登记'}　·　接取者：{task.assignee_name||'尚未确定'}</p>
    {!user?<LoginRequired/>:<>
      {notice&&<p className="success-notice" role="status">{notice}</p>}
      {workspace.loading&&<p role="status">正在加载协作记录…</p>}
      {workspace.error&&<div className="form-error" role="alert">{workspace.error}<button className="text-button" onClick={workspace.retry}>重新加载</button></div>}
      {action.error&&<div className="form-error" role="alert">{action.error}</div>}
      {workspace.data&&<>
        {task.status==='withdrawn'&&<div className="info-notice">任务已下架，不再接受申请。任务和历史申请记录仍然保留。</div>}
        {task.status==='cancelled'&&<div className="info-notice">此任务已协商取消，不计入已完成协作。阶段、成果、验收、变更与结算历史仍保留。{task.cancel_reason&&<p>取消原因：{task.cancel_reason}</p>}{owner&&<a className="button secondary" href={`#/tasks/new?type=ordinary&copy=${encodeURIComponent(task.id)}`}>复制为新任务</a>}</div>}
        {task.status==='paused'&&<div className="info-notice">协作已暂停：{task.pause_reason||'双方确认暂停'}。阶段执行、成果提交和验收暂时冻结；截止时间不会自动延长。</div>}
        {owner&&task.status==='published'&&!task.assignee_id&&<div className="workspace-section"><h3>管理任务</h3><p className="muted">下架后从大厅移除，尚未确认的申请将关闭。</p><button className="button secondary" disabled={action.busy} onClick={()=>void action.perform(`/api/tasks/${task.id}/withdraw`)}>{action.busy?'正在处理…':'下架任务'}</button></div>}
        {owner&&<div className="workspace-section"><h3>{task.acceptance_mode==='direct'?'接取记录':'接取申请'}</h3>
          {!workspace.data.applications.length&&<p className="muted">{task.acceptance_mode==='direct'?'尚无接取记录。':'还没有同学申请。'}</p>}
          {workspace.data.applications.map(application=><div className="record" key={application.id}><div className="record-heading"><strong>{application.applicant_name}</strong><span>{application.status==='pending'?'待确认':application.status==='accepted'?'已接受':'已关闭'}</span></div>
            {Object.entries(applicationLabels).map(([key,label])=>task.application_requirements[key as keyof ApplicationRequirements]!=='disabled'&&<p key={key}><strong>{label}：</strong>{application[key as keyof ApplicationRequirements]||'未填写'}</p>)}{application.status==='withdrawn'&&<p className="muted">申请者已撤回 · {formatTime(application.withdrawn_at||application.created_at)}</p>}{task.acceptance_mode==='approval'&&application.status==='pending'&&<button className="button" disabled={action.busy||!task.can_accept_application} onClick={()=>void action.perform(`/api/applications/${application.id}/accept`)}>接受 {application.applicant_name} 的申请</button>}</div>)}
        </div>}
        {!owner&&!assignee&&task.status==='published'&&!task.is_expired&&(myApplication?<div className="info-notice">你已提交申请，等待发布者确认。<button className="button secondary" disabled={action.busy} onClick={()=>void action.perform(`/api/applications/${myApplication.id}/withdraw`)}>撤回这次申请</button></div>:<form className="publish-form workspace-section" onSubmit={apply}>
          <h3>{task.acceptance_mode==='direct'?'直接接取':latestAttempt?'重新提交申请':'申请接取'}</h3>{latestAttempt&&['withdrawn','rejected'].includes(latestAttempt.status)&&<p className="muted">上次申请{latestAttempt.status==='withdrawn'?'已撤回':'已结束'}，重新提交会保留历史并生成新申请。</p>}{Object.entries(applicationLabels).map(([key,label])=>task.application_requirements[key as keyof ApplicationRequirements]!=='disabled'&&<label key={key}>{label}{task.application_requirements[key as keyof ApplicationRequirements]==='required'?' *':'（选填）'}<textarea name={key} required={task.application_requirements[key as keyof ApplicationRequirements]==='required'} maxLength={2000} rows={3}/></label>)}{task.acceptance_mode==='direct'&&<label className="condition-confirm"><input type="checkbox" name="confirmed" required/>我已阅读并确认任务条件</label>}<button className="button" disabled={action.busy}>{action.busy?'正在提交…':task.acceptance_mode==='direct'?'确认接取':latestAttempt?'重新提交申请':'提交接取申请'}</button></form>)}
        {task.is_expired&&<p className="info-notice">任务已截止，等待发布者延长。原申请记录保留，暂不能申请、直接接取或接受申请。</p>}
        {latestAttempt?.status==='rejected'&&task.status!=='published'&&<div className="info-notice">此申请已结束，原申请记录仍保留。</div>}
        {(workspace.data.uses_stages||((owner||assignee)&&['published','in_progress'].includes(task.status)))&&<StagesPanel task={task} user={user} onChange={()=>{workspace.retry();onChange();}}/>}
        {!workspace.data.uses_stages&&owner&&task.status==='in_progress'&&<div className="info-notice">等待 {task.assignee_name} 完成任务并提交成果。</div>}
        {!workspace.data.uses_stages&&assignee&&task.status==='in_progress'&&<form className="publish-form workspace-section" onSubmit={submit}><h3>提交成果</h3>
          <label>成果说明<textarea name="summary" required maxLength={4000} rows={4} placeholder="说明完成了什么，以及与完成标准的对应情况。"/></label>
          <button className="button" disabled={action.busy}>{action.busy?'正在提交…':'提交成果，等待验收'}</button></form>}
        {!workspace.data.uses_stages&&assignee&&task.status==='pending_review'&&<div className="info-notice">成果已提交，等待发布者验收。</div>}
        {(owner||assignee)&&workspace.data.submissions.length>0&&<div className="workspace-section"><h3>成果与验收记录</h3>
          {workspace.data.submissions.map(submission=><div className="record" key={submission.id}><div className="record-heading"><strong>{submission.status==='submitted'?'待验收成果':submission.status==='accepted'?'已通过验收':'需补充成果'}</strong><span>{formatTime(submission.created_at)}</span></div>
            <p>{submission.summary}</p><AgreementLink taskId={task.id} version={submission.terms_version}/>
            {submission.feedback&&<div className="review-feedback"><strong>发布者意见</strong><p>{submission.feedback}</p></div>}</div>)}
        </div>}
        {!workspace.data.uses_stages&&owner&&task.status==='pending_review'&&<form className="publish-form workspace-section" onSubmit={review}><h3>验收成果</h3><label>验收意见<textarea name="feedback" rows={3} maxLength={2000} placeholder="确认完成时可留空；退回补充时请说明需要修改的内容。"/></label>
          <div className="action-buttons"><button className="button secondary" value="request_changes" disabled={action.busy}>退回补充</button><button className="button" value="accept" disabled={action.busy}>确认完成</button></div></form>}
        {task.status==='completed'&&<div className="success-notice">✓ 任务已完成，成果和验收记录已保存。</div>}
        {!owner&&!assignee&&!myApplication&&task.status!=='published'&&task.status!=='withdrawn'&&<div className="info-notice">这条任务已有人接取，可以返回大厅寻找其他任务。</div>}
      </>}
    </>}
  </section>;
}

export function MyTasksPage({user}:{user:User}) {
  const resource=useResource<MyTasks>('/api/me/tasks');
  const [tab,setTab]=useState<'published'|'assigned'|'applied'>('published');
  const labels={published:'我的发布',assigned:'我的接取',applied:'我的申请'};
  return <><div className="page-heading"><div><p className="eyebrow">把协作进度放在一起</p><h1>我的任务</h1><p className="subheading">{user.display_name}，查看你的发布、接取与申请。</p></div></div>
    <div className="my-tabs">{Object.entries(labels).map(([key,label])=><button className={tab===key?'selected':''} key={key} onClick={()=>setTab(key as typeof tab)}>{label}{resource.data&&` (${resource.data[key as typeof tab].length})`}</button>)}</div>
    {tab==='applied'&&<p className="muted">这里只显示等待确认的申请，接取成功后请到“我的接取”查看。</p>}
    {resource.loading&&<div className="state" role="status">正在加载任务…</div>}
    {resource.error&&<div className="state" role="alert">{resource.error}<button className="button secondary" onClick={resource.retry}>重新加载</button></div>}
    {resource.data&&(resource.data[tab].length?<div className="my-task-list">{resource.data[tab].map(task=><a className="panel my-task" key={task.id} href={`#/tasks/${task.id}`}><div><h2>{task.title}</h2><p>{task.publisher_name} 发布 · 接取者 {task.assignee_name||'待确定'}</p></div><span className="badge">{statusNames[task.status]}{task.is_expired?' · 已截止':task.is_overdue?' · 逾期':''}</span></a>)}</div>:<div className="state"><strong>暂时没有{labels[tab].slice(2)}的任务</strong><a className="button secondary" href="#/tasks">去任务大厅看看</a></div>)}
    {tab==='applied'&&resource.data&&!!resource.data.application_history?.length&&<details className="workspace-section"><summary>已撤回或已结束的申请（{resource.data.application_history.length}）</summary><div className="my-task-list">{resource.data.application_history.map(task=><a className="panel my-task" key={task.id} href={`#/tasks/${task.id}`}><div><h2>{task.title}</h2><p>打开详情查看申请状态和重新申请入口。</p></div><span className="badge">历史申请</span></a>)}</div></details>}
  </>;
}
