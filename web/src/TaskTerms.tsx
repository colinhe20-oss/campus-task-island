import {useState,type FormEvent} from 'react';
import {request,formatTime,formatMoney,yuanToFen,type Task,type User} from './api';
import {useLiveResource,LiveFeedback} from './live';
import {ChangeForm,Diff, type ChangeState} from './changes';

type Settlement={server_time:string;next_boundary:string|null;available:boolean;amount_fen:number;basis:string;no_payment_required:boolean;my_role:'payer'|'payee';payer_confirmed:number;payee_confirmed:number;both_confirmed:boolean;version:number;history:{id:string;role:string;reason:string;before_state:string;after_state:string;created_at:string}[]};
const extensionNames:Record<string,string>={pending:'待对方确认',approved:'已通过',rejected:'已拒绝',cancelled:'已撤销',closed:'任务结束关闭',stale:'已失效'};
const requestNames:Record<string,string>={pause:'暂停协作',resume:'恢复协作',cancel:'协商取消'};
const localDate=(s:string)=>new Date(Date.parse(s)+8*3600*1000).toISOString().slice(0,16);

export function TaskTermsPanel({task,user,onChange}:{task:Task;user:User;onChange:()=>void}){
  const extensions=useLiveResource<ChangeState>(`/api/tasks/${task.id}/changes`);
  const settlement=useLiveResource<Settlement>(task.reward_type==='paid'?`/api/tasks/${task.id}/settlement`:null);
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
  const [reason,setReason]=useState(''),[baseline,setBaseline]=useState<number>();
  const [reviewReasons,setReviewReasons]=useState<Record<string,string>>({});
  const [settlementReason,setSettlementReason]=useState('');
  const [pauseReason,setPauseReason]=useState(''),[cancelReason,setCancelReason]=useState(''),[extendDeadline,setExtendDeadline]=useState(false),[extensionDate,setExtensionDate]=useState(''),[cancelAmount,setCancelAmount]=useState('');
  const owner=task.publisher_id===user.id;
  const canPropose=['in_progress','pending_review','paused'].includes(task.status);
  const pending=extensions.data?.items.find(x=>x.status==='pending');
  async function act(url:string,body:unknown,after?:()=>void){
    setBusy(true);setError('');setNotice('');
    try{await request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});setNotice('操作成功，记录已保存。');after?.();extensions.retry();settlement.retry();onChange();}
    catch(e){setError((e as Error).message);extensions.retry();settlement.retry();onChange();}
    finally{setBusy(false);}
  }
  function submit(e:FormEvent<HTMLFormElement>){
    e.preventDefault();const form=e.currentTarget;const deadline=String(new FormData(form).get('deadline')||'');if(!reason.trim()){setError('请填写延期原因。');return;}
    void act(`/api/tasks/${task.id}/${task.status==='published'?'deadline':'changes'}`,{deadline:deadline+':00+08:00',reason:reason.trim(),version:baseline??task.terms_version},()=>{form.reset();setReason('');setBaseline(undefined);});
  }
  function submitControl(e:FormEvent<HTMLFormElement>,action:'pause'|'resume'|'cancel'){
    e.preventDefault();let amount:number|undefined;
    const reason=action==='cancel'?cancelReason:pauseReason;
    if(action==='cancel'&&task.reward_type==='paid'){
      try{const raw=cancelAmount.trim();if(!/^(0|[1-9]\d*)(\.\d{1,2})?$/.test(raw))throw new Error('请输入有效金额，最多两位小数。');const [whole,fraction='']=raw.split('.');const fen=BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0'));if(fen>BigInt(task.reward_amount_fen||0))throw new Error('取消结算金额不能高于原报酬。');amount=Number(fen);}catch(err){setError((err as Error).message);return;}
    }
    if(action==='pause'&&extendDeadline&&!extensionDate){setError('选择延长截止时间时，请填写新时间。');return;}
    void act(`/api/tasks/${task.id}/collaboration-requests`,{action,version:task.terms_version,collaboration_version:task.collaboration_version,reason:reason.trim(),extend_deadline:action==='pause'&&extendDeadline,...(action==='pause'&&extendDeadline?{deadline:extensionDate+':00+08:00'}:{}),...(amount===undefined?{}:{cancellation_settlement_fen:amount})},()=>{setPauseReason('');setCancelReason('');setExtensionDate('');setCancelAmount('');setExtendDeadline(false);});
  }
  return <section className="detail-section"><h2>任务约定与记录</h2>
    <p>整体截止：{formatTime(task.deadline)} · 约定版本 {task.terms_version}{task.is_expired?' · 已截止':task.is_overdue?' · 已逾期':''}</p>
    {task.is_overdue&&<p className="info-notice">任务已逾期，仍可提交和验收，也可提出约定变更申请。</p>}
    {task.status==='paused'&&<p className="info-notice">协作已暂停：{task.pause_reason||'双方确认暂停'}。暂停不会自动延长整体截止时间；恢复后按当前截止时间判断是否逾期。</p>}
    <p className="muted">确认前继续执行当前约定。整体延期不改变阶段截止时间。所有操作时间按北京时间展示。</p>
    <LiveFeedback {...extensions} label="变更记录"/>
    {error&&<div role="alert" className="form-error">{error} 你填写的内容已保留。{baseline!==undefined&&baseline!==task.terms_version&&<button className="text-button" onClick={()=>setBaseline(task.terms_version)}>核对最新约定后使用版本 {task.terms_version}</button>}</div>}
    {notice&&<p role="status" className="success-notice">{notice}</p>}
    {(owner&&task.status==='published')&&<form className="publish-form workspace-section" onSubmit={submit}>
      <h3>{task.status==='published'?'延长截止时间':'申请整体延期'}</h3>
      <label>新截止时间（北京时间）*<input type="datetime-local" name="deadline" required min={task.deadline?localDate(task.deadline):undefined} onInput={()=>setBaseline(v=>v??task.terms_version)}/></label>
      <label>延期原因 *<textarea required maxLength={2000} value={reason} onChange={e=>{setReason(e.target.value);setBaseline(v=>v??task.terms_version);}}/></label>
      <button className="button" disabled={busy}>{busy?'正在处理…':task.status==='published'?'确认延长并开放接取':'提交延期申请'}</button>
    </form>}
    {!pending&&task.assignee_id&&['in_progress','pending_review','paused'].includes(task.status)&&<div className="workspace-section"><h3>协作管理</h3>
      {task.status==='pending_review'&&<p className="info-notice">成果正在等待验收。请先由验收方通过或退回补充，不能用取消绕过成果与验收记录。</p>}
      <form className="publish-form" onSubmit={e=>submitControl(e,task.status==='paused'?'resume':'pause')}><h4>{task.status==='paused'?'申请恢复协作':'申请暂停协作'}</h4><label>申请原因 *<textarea required maxLength={2000} value={pauseReason} onChange={e=>setPauseReason(e.target.value)}/></label>
        {task.status!=='paused'&&<><label className="condition-confirm"><input type="checkbox" checked={extendDeadline} onChange={e=>setExtendDeadline(e.target.checked)}/>同时申请延长整体截止时间</label>{extendDeadline&&<><label>新的整体截止时间（北京时间）*<input required type="datetime-local" value={extensionDate} min={task.deadline?localDate(task.deadline):undefined} onChange={e=>setExtensionDate(e.target.value)}/></label><p className="muted">只有对方批准且批准时仍晚于服务端当前时间才生效；阶段截止时间不会自动调整。</p></>}</>}
        <button className="button secondary" disabled={busy}>{busy?'正在提交…':task.status==='paused'?'申请恢复协作':'申请暂停协作'}</button></form>
      {task.status!=='pending_review'&&task.paused_from_status!=='pending_review'&&<form className="publish-form" onSubmit={e=>submitControl(e,'cancel')}><h4>申请协商取消</h4><p className="muted">由对方确认后任务进入已取消状态，协作历史继续保留。</p><label>取消原因 *<textarea required maxLength={2000} value={cancelReason} onChange={e=>setCancelReason(e.target.value)}/></label>{task.reward_type==='paid'&&<label>双方协商的取消结算金额（元）*<input required inputMode="decimal" value={cancelAmount} onChange={e=>setCancelAmount(e.target.value)} placeholder={`0 至 ${formatMoney(task.reward_amount_fen)}`}/><small>零元表示双方约定无需结算；正金额由付款方和收款方分别确认。</small></label>}<button className="button danger" disabled={busy}>{busy?'正在提交…':'申请协商取消'}</button></form>}
    </div>}
    {canPropose&&!pending&&extensions.data&&<ChangeForm task={task} state={extensions.data} busy={busy} submit={body=>act(`/api/tasks/${task.id}/changes`,body)}/>}
    {extensions.data?.items.map(x=><div className="record" key={x.id}>
      <div className="record-heading"><strong>{x.kind==='agreement'?'约定变更申请':requestNames[x.kind]||'协作申请'} · {x.requester_id===user.id?'本人提出':'对方提出'}</strong><span>{extensionNames[x.status]}</span></div>
      <p>基础约定版本 {x.terms_version} · {formatTime(x.created_at)}</p><Diff differences={x.differences}/><p>{x.reason}</p>{x.review_reason&&<p>处理说明：{x.review_reason}</p>}
      {x.status==='pending'&&canPropose&&(x.requester_id===user.id?<button className="button secondary" disabled={busy} onClick={()=>void act(`/api/task-changes/${x.id}/cancel`,{version:x.version})}>撤销申请</button>:<>
        <label>处理说明（拒绝时必填）<textarea maxLength={2000} value={reviewReasons[x.id]||''} onChange={e=>setReviewReasons(v=>({...v,[x.id]:e.target.value}))}/></label>
        <div className="action-buttons"><button className="button secondary" disabled={busy} onClick={()=>{if(!reviewReasons[x.id]?.trim()){setError('拒绝申请必须填写原因。');return;}void act(`/api/task-changes/${x.id}/review`,{version:x.version,decision:'reject',reason:reviewReasons[x.id].trim()});}}>拒绝</button><button className="button" disabled={busy} onClick={()=>void act(`/api/task-changes/${x.id}/review`,{version:x.version,decision:'approve',reason:reviewReasons[x.id]||''})}>同意并生效</button></div>
      </>)}
    </div>)}
    {task.reward_type==='legacy'&&<p className="muted">历史回报未分类，原回报文字保留，双方可在完成前通过变更申请补齐回报分类。</p>}
    {task.reward_type==='paid'&&<div className="workspace-section"><h3>双方线下结算确认 · {formatMoney(task.reward_amount_fen)}</h3><p className="muted">此处记录固定报酬全额的双方声明，不代表平台验证真实转账。</p>
      <LiveFeedback {...settlement} label="结算记录"/>
      {settlement.data&&<><p>{settlement.data.basis}：{formatMoney(settlement.data.amount_fen)}</p>{task.status==='cancelled'&&task.cancellation_settlement_reason&&<p>协商取消说明：{task.cancellation_settlement_reason}</p>}{settlement.data.no_payment_required?<p className="success-notice">双方已约定无需结算。</p>:<><p>付款方：{settlement.data.payer_confirmed?'已确认付款':'尚未确认'} · 收款方：{settlement.data.payee_confirmed?'已确认收款':'尚未确认'}</p><p>{settlement.data.both_confirmed?'双方已确认结算':'尚未双方确认结算'}</p></>}
        {!settlement.data.available||settlement.data.no_payment_required?<p>{settlement.data.no_payment_required?'取消结算为零，无需付款或收款确认。':'验收完成或取消结算金额确定后开放结算确认。'}</p>:<>
          <label>结算说明（撤销时必填）<textarea maxLength={2000} value={settlementReason} onChange={e=>setSettlementReason(e.target.value)}/></label>
          <button className="button" disabled={busy} onClick={()=>{const confirmed=Boolean(settlement.data![settlement.data!.my_role==='payer'?'payer_confirmed':'payee_confirmed']);if(confirmed&&!settlementReason.trim()){setError('撤销确认必须填写原因。');return;}void act(`/api/tasks/${task.id}/settlement/confirmation`,{version:settlement.data!.version,confirmed:!confirmed,reason:settlementReason.trim()},()=>setSettlementReason(''));}}>{settlement.data[settlement.data.my_role==='payer'?'payer_confirmed':'payee_confirmed']?'撤销本人的结算确认':settlement.data.my_role==='payer'?'确认本人已付款':'确认本人已收款'}</button>
        </>}
        {settlement.data.history.length>0&&<details><summary>结算确认历史</summary>{settlement.data.history.map(h=>{const before=JSON.parse(h.before_state),after=JSON.parse(h.after_state),field=h.role+'_confirmed';return <div className="record" key={h.id}><p>{h.role==='payer'?'付款方':'收款方'}：{before[field]?'已确认':'未确认'} → {after[field]?'已确认':'未确认'} · {formatTime(h.created_at)}</p>{h.reason&&<p>{h.reason}</p>}</div>;})}</details>}
      </>}
    </div>}
  </section>;
}
