import {useEffect,useRef,useState,type FormEvent} from 'react';
import {request,formatTime,type StagePanel,type StageFields,type StageSuggestion,type Stage,type Task,type User} from './api';
import {useResource} from './hooks';
import './stages.css';
import {AgreementLink} from './changes';

const labels:Record<string,string>={not_started:'未开始',in_progress:'进行中',submitted:'已提交',changes_requested:'需补充',confirmed:'已确认'};
const toolNames:Record<string,string>={get_task_detail:'读取任务要求',propose_task_stages:'整理阶段建议'};
function localTime(value:string|null){return value?new Date(new Date(value).getTime()+8*3600000).toISOString().slice(0,16):'';}
function editable(fields:StageFields){return {...fields,deadline:localTime(fields.deadline)};}

export function StagesPanel({task,user,onChange}:{task:Task;user:User;onChange:()=>void}){
  const resource=useResource<StagePanel>(`/api/tasks/${task.id}/stages`);
  const [editing,setEditing]=useState(false),[fields,setFields]=useState<StageFields[]>([]);
  const [baseline,setBaseline]=useState(0),[sourceId,setSourceId]=useState<string>();
  const [termsBaseline,setTermsBaseline]=useState(task.terms_version);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [suggestion,setSuggestion]=useState<StageSuggestion|null>(null),[requirements,setRequirements]=useState('');
  const [aiBusy,setAiBusy]=useState(false),[runId,setRunId]=useState<string>(),[progress,setProgress]=useState('正在启动…');
  const stream=useRef<EventSource|null>(null),active=useRef<AbortController|null>(null);
  const runKey=`campus-stage-run:${user.id}:${task.id}`;
  useEffect(()=>{if(resource.data)setSuggestion(resource.data.suggestion);},[resource.data]);
  function rememberRun(id?:string){try{if(id)sessionStorage.setItem(runKey,id);else sessionStorage.removeItem(runKey);}catch{/* 可在引航员运行记录中查看结果。 */}}
  function watch(id:string,controller:AbortController){
    setRunId(id);setAiBusy(true);const source=new EventSource(`/api/guide/runs/${id}/events`);stream.current=source;
    source.addEventListener('progress',event=>{
      if(controller.signal.aborted)return;
      const data=JSON.parse((event as MessageEvent).data);
      if(data.kind==='model_started')setProgress(`第 ${data.step} 轮 · 分析任务与阶段`);
      if(data.kind==='tool_started')setProgress(toolNames[data.tool]||data.tool);
    });
    source.addEventListener('terminal',event=>{
      source.close();if(controller.signal.aborted)return;
      const run=JSON.parse((event as MessageEvent).data);rememberRun();setRunId(undefined);setAiBusy(false);
      if(run.status==='succeeded'&&run.result?.stage_suggestion){setSuggestion(run.result.stage_suggestion);setNotice('AI 建议已生成。可填入编辑区修改，确认安排后才生效。');resource.retry();}
      else setError(run.error||'未生成有效阶段建议，可以补充要求重试或手动设置。');
    });
    source.onerror=()=>{if(controller.signal.aborted)return;setProgress('连接中断，正在重连…');
      void request(`/api/guide/runs/${id}`,{signal:controller.signal}).catch(reason=>{
        if(!controller.signal.aborted){source.close();setAiBusy(false);setRunId(undefined);setError(`读取运行失败，请刷新恢复：${reason instanceof Error?reason.message:''}`);}});};
  }
  useEffect(()=>{
    const controller=new AbortController();active.current=controller;
    try{const saved=sessionStorage.getItem(runKey);if(saved)watch(saved,controller);}catch{/* 会话存储不可用时正常使用。 */}
    return()=>{controller.abort();active.current?.abort();stream.current?.close();};
  },[runKey]);
  async function suggest(){
    if(aiBusy||busy)return;setError('');setNotice('');setAiBusy(true);setProgress('正在启动…');
    const controller=new AbortController();active.current=controller;
    try{const started=await request<{run_id:string}>('/api/guide/runs',{method:'POST',signal:controller.signal,headers:{'Content-Type':'application/json'},
      body:JSON.stringify({purpose:'stage_plan',task_id:task.id,message:'请根据当前任务生成可确认的阶段安排。'+(requirements.trim()?`补充要求：${requirements.trim()}`:'按任务复杂程度安排必要阶段。')})});
      if(!controller.signal.aborted){rememberRun(started.run_id);watch(started.run_id,controller);}
    }catch(reason){if(!controller.signal.aborted){setAiBusy(false);setError(reason instanceof Error?reason.message:'AI 建议生成失败');}}
  }
  async function cancelAi(){if(!runId)return;
    try{await request(`/api/guide/runs/${runId}/cancel`,{method:'POST'});setProgress('正在取消，等待运行结束…');}
    catch(reason){setError(reason instanceof Error?reason.message:'取消失败');}}
  function newStage():StageFields{return {title:'',completion_criteria:'',deadline:localTime(task.deadline),responsible_role:'assignee'};}
  function editPlan(){if(!resource.data)return;setFields(resource.data.stages.length?resource.data.stages.map(editable):[newStage()]);setBaseline(resource.data.plan_version);setTermsBaseline(task.terms_version);setSourceId(undefined);setEditing(true);setError('');}
  function useSuggestion(){if(!suggestion)return;setFields(suggestion.stages.map(editable));setBaseline(suggestion.base_version);setTermsBaseline(task.terms_version);setSourceId(suggestion.id);setEditing(true);setError('');}
  function patch(index:number,key:keyof StageFields,value:string){setFields(previous=>previous.map((s,i)=>i===index?{...s,[key]:value}:s));}
  async function perform(url:string,body:unknown){setBusy(true);setError('');
    try{await request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});setEditing(false);setNotice(task.assignee_id&&url.endsWith('/changes')?'阶段安排申请已提交，对方确认前不生效。':'阶段安排或进度已更新。');resource.retry();onChange();}
    catch(reason){setError(reason instanceof Error?reason.message:'操作失败，请刷新后重试');}
    finally{setBusy(false);}}
  function save(event:FormEvent<HTMLFormElement>){event.preventDefault();
    const stages=fields.map(s=>({...s,deadline:s.deadline.length===16?s.deadline+':00+08:00':s.deadline+ '+08:00'}));
    if(task.assignee_id){const reason=String(new FormData(event.currentTarget).get('change_reason')||'').trim();
      void perform(`/api/tasks/${task.id}/changes`,{version:termsBaseline,reason,suggestion_id:sourceId,changes:{initial_stages:stages}});
    }else void perform(`/api/tasks/${task.id}/stages`,{expected_version:baseline,suggestion_id:sourceId,stages});
  }
  function submit(event:FormEvent<HTMLFormElement>,stage:Stage){event.preventDefault();const form=new FormData(event.currentTarget);
    void perform(`/api/tasks/${task.id}/stages/${stage.id}/submissions`,{version:stage.version,summary:String(form.get('summary')||'').trim()});}
  function review(event:FormEvent<HTMLFormElement>,stage:Stage){event.preventDefault();const form=new FormData(event.currentTarget);
    const decision=(event.nativeEvent as SubmitEvent).submitter?.getAttribute('value')||'accept',feedback=String(form.get('feedback')||'').trim();
    if(decision==='request_changes'&&!feedback){setError('退回补充时请填写修改意见。');return;}
    void perform(`/api/tasks/${task.id}/stages/${stage.id}/review`,{version:stage.version,decision,feedback});}
  const panel=resource.data,current=panel?.stages.find(s=>s.status!=='confirmed');
  const collaborator=user.id===task.publisher_id||user.id===task.assignee_id;
  const executing=!!task.assignee_id&&['in_progress','pending_review'].includes(task.status);
  return <section className="stage-panel workspace-section" aria-label="共享阶段面板"><div className="stage-heading"><h3>共享阶段面板</h3><button className="text-button" onClick={resource.retry}>刷新阶段</button></div>
    {task.status==='paused'&&<p className="info-notice">协作暂停中。阶段、成果与验收记录保留，执行操作在恢复前冻结。</p>}{task.status==='cancelled'&&<p className="info-notice">任务已取消。阶段及提交历史仅供查看。</p>}
    {resource.loading&&<p role="status">正在读取阶段安排…</p>}{resource.error&&<p className="form-error" role="alert">{resource.error}</p>}
    {error&&<div className="form-error" role="alert">{error}<small>内容已保留；若安排或状态发生变化，请刷新并核对最新版本。</small></div>}
    {notice&&<p className="success-notice" role="status">{notice}</p>}
    {panel&&<>
      {!!panel.stages.length&&<><p className="muted">安排版本 {panel.plan_version} · 已确认 {panel.stages.filter(s=>s.status==='confirmed').length}/{panel.stages.length} 阶段。按顺序执行，负责人提交，对方验收。</p>
        <progress className="stage-progress" aria-label="阶段完成进度" value={panel.stages.filter(s=>s.status==='confirmed').length} max={panel.stages.length}/></>}
      {!panel.stages.length&&<p className="muted">{panel.can_edit?'尚未设置阶段安排。发布者可手动拆分，或让 AI 提出建议。':user.id===task.publisher_id?'本任务继续使用整项成果提交与验收。':'尚未设置阶段安排，可以由发布者确认后开始分阶段协作。'}</p>}
      {panel.stages.map(stage=><article className={`stage-card ${stage.status}`} key={stage.id}>
        <div className="record-heading"><strong>{stage.position} · {stage.title}</strong><span className="stage-status">{labels[stage.status]}</span></div>
        <p className="stage-people">负责人：{stage.responsible_name||(stage.responsible_role==='publisher'?'发布者':'接取者待确定')} · 验收方：{stage.reviewer_name||'接取者待确定'}</p>
        <p className="muted">截止：{formatTime(stage.deadline)}{stage.status!=='confirmed'&&Date.parse(stage.deadline)<=Date.parse(task.server_time)?' · 阶段已逾期':''}</p><p className="stage-criteria">完成要求：{stage.completion_criteria}</p>
        {stage.id!==current?.id&&stage.status!=='confirmed'&&<p className="muted">前面的阶段确认后开放。</p>}
        {!executing&&task.status==='published'&&<p className="muted">正式接取后开始执行。</p>}
        {executing&&stage.id===current?.id&&user.id===stage.responsible_id&&<>
          {['not_started','changes_requested'].includes(stage.status)&&<button className="button" disabled={busy||aiBusy} onClick={()=>void perform(`/api/tasks/${task.id}/stages/${stage.id}/start`,{version:stage.version})}>{stage.status==='changes_requested'?'继续本阶段':'开始本阶段'}</button>}
          {stage.status==='in_progress'&&<form className="publish-form stage-form" onSubmit={e=>submit(e,stage)}><label>阶段成果说明<textarea name="summary" required maxLength={4000} rows={3} placeholder="说明本阶段完成了什么，以及如何满足完成要求。"/></label><button className="button" disabled={busy||aiBusy}>提交本阶段，等待确认</button></form>}
          {stage.status==='submitted'&&<p className="info-notice">已提交，等待 {stage.reviewer_name} 确认。</p>}
        </>}
        {executing&&stage.id===current?.id&&user.id===stage.reviewer_id&&stage.status==='submitted'&&<form className="publish-form stage-form" onSubmit={e=>review(e,stage)}><label>阶段验收意见<textarea name="feedback" maxLength={2000} rows={2} placeholder="确认时可留空；退回时请说明需要补充的内容。"/></label><div className="action-buttons"><button className="button secondary" value="request_changes" disabled={busy||aiBusy}>退回本阶段</button><button className="button" value="accept" disabled={busy||aiBusy}>确认本阶段</button></div></form>}
        {collaborator&&stage.submissions.length>0&&<details className="stage-history" open={stage.status==='submitted'||stage.status==='changes_requested'}><summary>提交与验收记录（{stage.submissions.length}）</summary>
          {stage.submissions.map(record=><div className="record" key={record.id}><div className="record-heading"><strong>{record.author_name} · {record.status==='submitted'?'待确认':record.status==='accepted'?'已确认':'需补充'}</strong><span>{formatTime(record.created_at)}</span></div><p>{record.summary}</p><AgreementLink taskId={task.id} version={record.terms_version}/>{record.feedback&&<div className="review-feedback"><strong>{record.reviewer_name} 的意见</strong><p>{record.feedback}</p></div>}</div>)}
        </details>}
      </article>)}
      {user.id===task.publisher_id&&!panel.can_edit&&task.status!=='completed'&&<p className="muted">{panel.edit_reason}</p>}
      {(panel.can_edit||panel.can_propose_plan)&&<div className="stage-plan-controls"><button className="button secondary" disabled={busy||aiBusy} onClick={editPlan}>{panel.stages.length?'编辑阶段安排':task.assignee_id?'提出首次阶段安排':'手动设置阶段'}</button>
        {panel.can_edit&&<>
        {!task.deadline&&<p className="muted">这条历史任务没有截止时间。请手动填写各阶段日期，或在下方说明希望的阶段截止时间后再生成 AI 建议。</p>}
        <label>希望 AI 考虑的安排（可选）<textarea rows={2} maxLength={1000} value={requirements} onChange={e=>setRequirements(e.target.value)} placeholder="例如：先由我确认需求，再由接取者制作和交付。" disabled={aiBusy||busy}/></label>
        <button className="button secondary" disabled={busy||aiBusy} onClick={()=>void suggest()}>AI 阶段建议</button></>}</div>}
      {aiBusy&&<div className="info-notice" role="status">{progress} {runId&&<button className="text-button" onClick={()=>void cancelAi()}>取消生成建议</button>}</div>}
      {suggestion&&suggestion.applied_version===null&&<section className="stage-suggestion" aria-label="AI 阶段建议"><h4>AI 建议 · {suggestion.base_version===panel.plan_version?'尚未确认':'已过期'}</h4><p className="muted">建议基于安排版本 {suggestion.base_version}。核对负责人、时间和完成要求后确认。</p>
        <ol>{suggestion.stages.map((s,i)=><li key={i}><strong>{s.title}</strong><p>{s.completion_criteria}</p><small>{s.responsible_role==='publisher'?'发布者':'接取者'}负责 · {formatTime(s.deadline)}</small></li>)}</ol>
        <button className="button secondary" disabled={busy||aiBusy||!panel.can_edit||suggestion.base_version!==panel.plan_version} onClick={useSuggestion}>将建议填入编辑区</button></section>}
      {editing&&<form className="publish-form stage-editor" aria-label="阶段安排编辑" onSubmit={save}><h4>确认阶段安排</h4><p className="muted">时间均为北京时间。接取后须对方确认才生效。已有阶段只能在任务约定区域修改时间和要求。最后一个阶段确认即完成整项任务。</p>
        {task.assignee_id&&<label>申请原因 *<textarea name="change_reason" required maxLength={2000}/></label>}
        {fields.map((field,index)=><fieldset key={index}><legend>阶段 {index+1}</legend><label>阶段名称 *<input required maxLength={80} value={field.title} onChange={e=>patch(index,'title',e.target.value)}/></label>
          <label>完成要求 *<textarea required maxLength={1000} rows={2} value={field.completion_criteria} onChange={e=>patch(index,'completion_criteria',e.target.value)}/></label>
          <div className="form-row"><label>负责人 *<select value={field.responsible_role} onChange={e=>patch(index,'responsible_role',e.target.value)}><option value="assignee">接取者</option><option value="publisher">发布者</option></select></label>
            <label className="grow">阶段截止时间 *<input required type="datetime-local" value={field.deadline} onChange={e=>patch(index,'deadline',e.target.value)}/></label></div>
          <div className="stage-order"><button type="button" className="text-button" disabled={index===0||busy} onClick={()=>setFields(prev=>{const next=[...prev];[next[index-1],next[index]]=[next[index],next[index-1]];return next;})}>上移</button>
            <button type="button" className="text-button" disabled={fields.length===1||busy} onClick={()=>setFields(prev=>prev.filter((_,i)=>i!==index))}>移除本阶段</button></div></fieldset>)}
        <div className="action-buttons"><button className="button secondary" type="button" disabled={fields.length>=8||busy||aiBusy} onClick={()=>setFields(prev=>[...prev,newStage()])}>添加阶段</button><button className="button secondary" type="button" disabled={busy} onClick={()=>setEditing(false)}>放弃编辑</button><button className="button" disabled={busy||aiBusy||!(panel.can_edit||panel.can_propose_plan)}>{busy?'正在保存…':task.assignee_id?'提交阶段安排申请':'确认阶段安排'}</button></div>
      </form>}
      {collaborator&&panel.versions.length>0&&<details className="stage-history"><summary>已确认的安排版本（{panel.versions.length}）</summary>{panel.versions.map(version=><div className="record" key={version.version}><strong>版本 {version.version} · {formatTime(version.created_at)}</strong><ol>{version.stages.map((s,i)=><li key={i}>{s.title} · {s.responsible_role==='publisher'?'发布者':'接取者'} · {formatTime(s.deadline)}<p>{s.completion_criteria}</p></li>)}</ol></div>)}</details>}
    </>}
  </section>;
}
