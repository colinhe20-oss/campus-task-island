import {useEffect, useRef, useState, type FormEvent} from 'react';
import {rewardNames,formatMoney,acceptanceNames,applicationLabels,requirementNames,type ApplicationRequirements,request, statusNames, categories, formatTime, type Task, type User, type Category} from './api';
import {useResource} from './hooks';
import './guide.css';

type Todo = {task_id:string; title:string; role:string; task_status:string; action:string; action_label:string; href:string};
type PersonalState = {published:Task[]; assigned:Task[]; applied:Task[]; todos:Todo[]; waiting:Todo[]; completed_count:number};
type Draft = {conversation_id:string; version:number; status:'draft'|'published'|'cancelled';
  fields:{title:string|null;category:Category|null;description:string|null;completion_criteria:string|null;location:string|null;deadline:string|null;reward:string|null;reward_type:'mutual'|'paid'|null;reward_amount_fen:number|null;acceptance_mode:keyof typeof acceptanceNames;application_requirements:ApplicationRequirements};
  missing_fields:string[];ready:boolean;published_task_id:string|null;href:string|null};
type Reference = {content_type?:'ordinary'|'activity'|'volunteer'|'discovery';resource_id?:string;task_id?:string|null;title:string;href:string};
type Reply = {conversation_id:string; answer:string; references:Reference[]; tools_used:{name:string;success:boolean}[]; mode:string;draft:Draft|null};
type Conversation = {conversation_id:string;messages:{role:'user'|'assistant';content:string}[];draft:Draft|null};
type RunRecord = {id:string; status:string; started_at:string;duration_ms:number|null;model:string|null;error:string|null;
  metrics:{model_calls?:number;tool_calls?:number;tool_errors?:number;total_tokens?:number;usage_complete:boolean};result?:Reply;
  events?:{seq:number;kind:string;step?:number;tool?:string;success?:boolean;duration_ms?:number}[]};
type Message = {role:'user'|'assistant'; text:string; reply?:Reply};
const toolNames:Record<string,string> = {get_my_tasks:'查询我的任务',get_my_overview:'查询跨板块待办',get_task_detail:'查看任务详情',search_tasks:'搜索普通任务',search_activities:'搜索综素活动',get_activity_detail:'查看活动详情',get_my_activity_registrations:'查询我的活动报名',search_volunteer_jobs:'搜索志愿岗位',get_volunteer_detail:'查看志愿岗位详情',get_my_volunteer_registrations:'查询我的志愿报名',get_my_volunteer_records:'查询志愿服务记录',search_discoveries:'搜索校园发现',get_discovery_detail:'查看发现详情',get_task_draft:'读取发布草稿',update_task_draft:'整理发布草稿',confirm_publish_task:'确认发布任务',cancel_task_draft:'取消草稿',propose_task_stages:'整理阶段建议'};
const fieldNames:Record<string,string> = {title:'标题',category:'分类',description:'需求说明',completion_criteria:'完成标准',location:'地点',deadline:'截止时间（需晚于当前时间）',reward_type:'回报类型',reward_amount_fen:'固定报酬金额',reward:'回报说明'};

export function GuidePage({user}:{user:User}) {
  const state = useResource<PersonalState>('/api/guide/todos');
  const runs = useResource<{items:RunRecord[]}>('/api/guide/runs');
  const [selectedRun,setSelectedRun] = useState<RunRecord|null>(null);
  const [runId,setRunId] = useState<string>();
  const [progress,setProgress] = useState('正在启动…');
  const [partial,setPartial] = useState('');
  const stream = useRef<EventSource|null>(null);
  const [messages,setMessages] = useState<Message[]>([]);
  const [input,setInput] = useState('');
  const [conversation,setConversation] = useState<string>();
  const [draft,setDraft] = useState<Draft|null>(null);
  const [busy,setBusy] = useState(false);
  const [recovering,setRecovering] = useState(true);
  const [error,setError] = useState('');
  const controller = useRef<AbortController|null>(null);
  const chatEnd = useRef<HTMLDivElement>(null);
  const storageKey = `campus-guide-conversation:${user.id}`;
  const runStorageKey = `campus-guide-run:${user.id}`;
  function remember(id?:string){try{if(id)sessionStorage.setItem(storageKey,id);else sessionStorage.removeItem(storageKey);}catch{/* 对话仍可在当前页面使用。 */}}
  function rememberRun(id?:string,message?:string){try{if(id)sessionStorage.setItem(runStorageKey,JSON.stringify({id,message}));else sessionStorage.removeItem(runStorageKey);}catch{/* 仍可查看运行记录恢复结果。 */}}
  function watch(id:string,message:string,active:AbortController){
    return new Promise<void>((resolve,reject)=>{
      setRunId(id);setBusy(true);
      const source=new EventSource(`/api/guide/runs/${encodeURIComponent(id)}/events`);stream.current=source;
      active.signal.addEventListener('abort',()=>{source.close();resolve();},{once:true});
      source.addEventListener('progress',event=>{
        if(active.signal.aborted)return;
        const data=JSON.parse((event as MessageEvent).data);
        if(data.kind==='model_started'){setProgress(`第 ${data.step} 轮 · 正在思考`);setPartial('');}
        if(data.kind==='text_delta')setPartial(text=>(text+data.text).slice(0,8000));
        if(data.kind==='tool_started')setProgress(`第 ${data.step} 轮 · ${toolNames[data.tool]||data.tool}…`);
        if(data.kind==='tool_finished')setProgress(`${toolNames[data.tool]||data.tool}${data.success?'完成':'返回错误，正在调整'} (${data.duration_ms} ms)`);
      });
      source.addEventListener('terminal',async event=>{
        source.close();if(active.signal.aborted){resolve();return;}
        const run:RunRecord=JSON.parse((event as MessageEvent).data);
        rememberRun();setRunId(undefined);setPartial('');runs.retry();
        if(run.status==='succeeded'&&run.result){
          const reply=run.result;
          // 读取服务端已提交历史，避免“提交成功但页面尚未收终态”时刷新造成重复一轮。
          try{
            const value=await request<Conversation>(`/api/guide/conversations/${reply.conversation_id}`,{signal:active.signal});
            if(!active.signal.aborted){setMessages(value.messages.map((m,i)=>({role:m.role,text:m.content,reply:i===value.messages.length-1?reply:undefined})));
              setConversation(reply.conversation_id);remember(reply.conversation_id);setDraft(value.draft);setInput('');state.retry();}
            resolve();
          }catch(reason){if(!active.signal.aborted){remember(reply.conversation_id);reject(new Error(`回答已保存，读取对话失败，请刷新：${reason instanceof Error?reason.message:''}`));}else resolve();}
        }else{setInput(message);reject(new Error(run.error||'运行未完成，请重试'));}
      });
      source.onerror=()=>{
        if(active.signal.aborted)return;
        setProgress('连接中断，正在重连…');
        // EventSource 自动携带 Last-Event-ID 重连；鉴权失效等永久错误时退出等待。
        void request<RunRecord>(`/api/guide/runs/${id}`,{signal:active.signal}).catch(reason=>{
          if(!active.signal.aborted){source.close();setRunId(undefined);reject(new Error(`连接失败：${reason instanceof Error?reason.message:'请刷新恢复运行'}`));}
        });
      };
    });
  }
  useEffect(()=>{
    const active=new AbortController();
    controller.current=active;
    void (async()=>{
      let saved:string|null=null,savedRun:{id:string;message:string}|null=null;
      try{saved=sessionStorage.getItem(storageKey);const raw=sessionStorage.getItem(runStorageKey);if(raw)savedRun=JSON.parse(raw);}catch{/* 允许未启用会话存储的浏览器。 */}
      try{
        if(saved){const value=await request<Conversation>(`/api/guide/conversations/${encodeURIComponent(saved)}`,{signal:active.signal});
          if(!active.signal.aborted){setConversation(value.conversation_id);setDraft(value.draft);setMessages(value.messages.map(m=>({role:m.role,text:m.content})));}}
        if(!active.signal.aborted&&savedRun){setRecovering(false);setInput(savedRun.message);await watch(savedRun.id,savedRun.message,active);}
      }catch(reason){if(!active.signal.aborted)setError(`恢复运行或对话失败：${reason instanceof Error?reason.message:'请重试'}。可以查看下方运行记录。`);}
      finally{if(!active.signal.aborted){setRecovering(false);setBusy(false);}}
    })();
    return()=>{active.abort();stream.current?.close();};
  },[storageKey]);
  useEffect(()=>()=>{controller.current?.abort();stream.current?.close();},[]);
  useEffect(()=>{chatEnd.current?.scrollIntoView({block:'nearest'});},[messages,busy,partial]);
  async function send(text:string) {
    if(busy||recovering||!text.trim())return;
    const message=text.trim();
    setBusy(true);setError('');setProgress('正在启动…');setPartial('');setInput(message);
    const active=new AbortController();controller.current=active;
    try {
      const started=await request<{run_id:string}>('/api/guide/runs',{method:'POST',signal:active.signal,
        headers:{'Content-Type':'application/json'},body:JSON.stringify({message,conversation_id:conversation,draft_version:draft?.version})});
      if(active.signal.aborted)return;
      rememberRun(started.run_id,message);
      await watch(started.run_id,message,active);
    } catch(reason) {
      if(!active.signal.aborted){setInput(message);setError(reason instanceof Error?reason.message:'回答失败，请重试。');}
    } finally {if(!active.signal.aborted)setBusy(false);}
  }
  async function cancelRun(){
    if(!runId)return;
    try{const value=await request<RunRecord>(`/api/guide/runs/${runId}/cancel`,{method:'POST'});
      setProgress(value.status==='cancelling'?'正在停止模型请求，等待运行结束…':'本轮已提交，正在接收结果…');
    }catch(reason){setError(reason instanceof Error?reason.message:'取消失败，请重试');}
  }
  async function inspectRun(id:string){
    try{setSelectedRun(await request<RunRecord>(`/api/guide/runs/${id}`));}
    catch(reason){setError(reason instanceof Error?reason.message:'记录加载失败');}
  }
  async function draftAction(action:'publish'|'cancel') {
    if(busy||recovering||!draft)return;
    setBusy(true);setError('');
    const active=new AbortController();controller.current=active;
    try{
      const reply=await request<Reply>(`/api/guide/drafts/${draft.conversation_id}/${action}`,{method:'POST',signal:active.signal,
        headers:{'Content-Type':'application/json'},body:JSON.stringify({version:draft.version})});
      if(active.signal.aborted)return;
      setDraft(reply.draft);setMessages(previous=>[...previous,{role:'user',text:action==='publish'?'确认发布':'取消草稿'},{role:'assistant',text:reply.answer,reply}]);
      setInput('');state.retry();runs.retry();
    }catch(reason){if(!active.signal.aborted)setError(reason instanceof Error?reason.message:'操作失败，请重试。');}
    finally{if(!active.signal.aborted)setBusy(false);}
  }
  async function refreshDraft(){
    if(!conversation||busy||recovering)return;
    setBusy(true);setError('');
    const active=new AbortController();controller.current=active;
    try{
      const value=await request<Conversation>(`/api/guide/conversations/${conversation}`,{signal:active.signal});
      if(!active.signal.aborted){setDraft(value.draft);setMessages(value.messages.map(m=>({role:m.role,text:m.content})));}
    }catch(reason){if(!active.signal.aborted)setError(reason instanceof Error?reason.message:'草稿加载失败');}
    finally{if(!active.signal.aborted)setBusy(false);}
  }
  function submit(event:FormEvent){event.preventDefault();void send(input);}
  function reset(){setMessages([]);setConversation(undefined);setDraft(null);remember();setError('');setInput('');}
  function items(values:Todo[],empty:string){return values.length?<ul className="todo-list">{values.map(item=><li key={item.task_id}>
    <a href={item.href}><strong>{item.title}</strong><span>{item.action_label}</span><small>{statusNames[item.task_status]}</small></a>
  </li>)}</ul>:<p className="guide-empty">{empty}</p>;}
  return <>
    <div className="page-heading"><div><p className="eyebrow">下一步，有个方向</p><h1>引航员</h1><p className="subheading">查看个人待办，询问任务进展，发现适合你的校园协作。</p></div></div>
    <div className="guide-layout"><section className="panel guide-todos"><div className="section-heading"><h2>个人待办</h2><button className="text-button" onClick={state.retry}>刷新</button></div>
      {state.loading&&<p role="status">正在查询当前任务…</p>}
      {state.error&&<div className="form-error" role="alert">{state.error}<button className="text-button" onClick={state.retry}>重新加载</button></div>}
      {!state.loading&&state.data&&<><p className="guide-count">需要我行动 <b>{state.data.todos.length}</b> · 等待他人 <b>{state.data.waiting.length}</b></p>
        <h3>需要我行动</h3>{items(state.data.todos,'当前没有需要你处理的事项。')}
        <h3>等待他人</h3>{items(state.data.waiting,'当前没有等待中的事项。')}
        <p className="guide-completed">已完成 {state.data.completed_count} 条协作 · <a href="#/mine">查看我的任务</a></p></>}
    </section><section className="panel guide-chat"><div className="section-heading"><h2>与引航员聊聊</h2><button className="text-button" onClick={reset} disabled={busy||recovering}>新对话</button></div>
      <p className="guide-intro">描述你想发布的普通任务，引航员会整理草稿并补问信息，确认后发布。也可查询普通任务的个人待办与详情。</p>
      <p className="guide-intro">综素活动使用独立的报名与认定规则。目前请从左侧<a className="result-link" href="#/tasks/new">“发布任务”</a>选择“综素活动”进行发布，或前往<a className="result-link" href="#/activities">综素活动</a>查看和报名。</p>
      <p className="guide-intro">从<a href="#/home">岛屿首页</a>查看当前待办，或到<a href="#/messages">消息</a>查看参与反馈；已读不代表事项已完成。引航员不代读取或标记消息。</p>
      <p className="guide-intro">校园发现用于提醒、分享与情况补充，请到<a className="result-link" href="#/discoveries">校园发现</a>查看，或从“发布任务”选择“校园发现”。引航员不会代发布、评论或核实设施和安全情况。</p>
      <p className="guide-intro">志愿服务按岗位报名，参与与活动方确认小时分开展示。目前请到<a className="result-link" href="#/volunteers">志愿服务</a>查看岗位，或从统一发布入口选择“志愿服务”。引航员不会代报名或确认志愿小时。</p>
      <div className="guide-questions">{['帮我发布一个任务','我现在需要做什么？','帮我找摄影任务'].map(question=><button key={question} disabled={busy||recovering} onClick={()=>void send(question)}>{question}</button>)}</div>
      <div className="chat-log" role="log" aria-label="引航员对话" aria-live="polite">
        {recovering&&<p role="status">正在恢复上次对话与草稿…</p>}
        {!recovering&&!messages.length&&<p className="guide-empty">可以直接说“我想找同学拍社团活动照片”，再补充引航员询问的细节。</p>}
        {messages.map((message,index)=><article key={index} className={`chat-message ${message.role}`}><strong>{message.role==='user'?'我':'引航员'}</strong>
          {message.reply?.mode==='offline_demo'&&<small className="demo-notice">离线测试模型 · 仅验证调用链</small>}
          <p>{message.text}</p>{message.reply&&<>
          {message.reply.tools_used.length>0&&<div className="tool-activity">{message.reply.tools_used.map((tool,i)=><span key={i}>{tool.success?'✓':'!'} {toolNames[tool.name]||tool.name}</span>)}</div>}
          {message.reply.references.length>0&&<div className="guide-references">{message.reply.references.map(ref=><a key={`${ref.content_type||'ordinary'}:${ref.resource_id||ref.task_id}`} href={ref.href}>{ref.title} ↗</a>)}</div>}</>}
        </article>)}
        {busy&&<><p role="status" className="guide-thinking"><span className="spinner"/> {runId?progress:'正在处理…'}</p>
          {partial&&<article className="chat-message assistant streaming"><strong>引航员 · 回答中</strong><p>{partial}</p><small>本轮完成后保存结果</small></article>}
          {runId&&<button className="button secondary" type="button" onClick={()=>void cancelRun()}>取消本次回答</button>}</>}<div ref={chatEnd}/>
      </div>
      {draft&&<section className="guide-draft" aria-label="任务发布草稿"><div className="section-heading"><h3>{draft.status==='published'?'普通任务已发布':draft.status==='cancelled'?'草稿已取消':'普通任务发布草稿'}</h3><span>版本 {draft.version}</span></div>
        <dl><div><dt>标题 *</dt><dd>{draft.fields.title||'待补充'}</dd></div><div><dt>分类 *</dt><dd>{draft.fields.category?categories[draft.fields.category]:'待补充'}</dd></div>
          <div><dt>需求说明 *</dt><dd>{draft.fields.description||'待补充'}</dd></div><div><dt>完成标准 *</dt><dd>{draft.fields.completion_criteria||'待补充'}</dd></div>
          <div><dt>地点 *</dt><dd>{draft.fields.location||'待补充'}</dd></div><div><dt>截止时间 *</dt><dd>{draft.fields.deadline?formatTime(draft.fields.deadline):'待补充'}</dd></div><div><dt>回报类型</dt><dd>{draft.fields.reward_type?rewardNames[draft.fields.reward_type]:'待补充'}{draft.fields.reward_type==='paid'?' · '+formatMoney(draft.fields.reward_amount_fen):''}</dd></div><div><dt>回报说明</dt><dd>{draft.fields.reward||'暂未说明'}</dd></div><div><dt>接取方式</dt><dd>{acceptanceNames[draft.fields.acceptance_mode]}</dd></div>{Object.entries(applicationLabels).map(([key,label])=><div key={key}><dt>{label}</dt><dd>{requirementNames[draft.fields.application_requirements[key as keyof ApplicationRequirements]]}</dd></div>)}</dl>
        {draft.status==='draft'&&<><p className="guide-draft-hint">{draft.ready?'请核对以上内容，确认后才会出现在任务大厅。':`还需补充：${draft.missing_fields.map(name=>fieldNames[name]||name).join('、')}。请在下方继续说明。`}</p>
          <div className="draft-actions"><button className="text-button" disabled={busy||recovering} onClick={()=>void refreshDraft()}>读取最新草稿</button><button className="button secondary" disabled={busy||recovering} onClick={()=>void draftAction('cancel')}>取消草稿</button><button className="button" disabled={busy||recovering||!draft.ready} onClick={()=>void draftAction('publish')}>确认发布</button></div></>}
        {draft.status==='published'&&draft.href&&<a className="button" href={draft.href}>查看已发布任务 ↗</a>}
        {draft.status==='cancelled'&&<p className="guide-draft-hint">尚未创建任务。点击“新对话”可以开始另一份草稿。</p>}
      </section>}
      {error&&<div role="alert" className="form-error">{error}<small>输入内容已保留，可以重试；草稿有变化时请读取最新草稿。</small></div>}
      <form className="guide-input" onSubmit={submit}><label htmlFor="guide-message">你的问题</label><textarea id="guide-message" maxLength={2000} rows={3} value={input} onChange={event=>setInput(event.target.value)} placeholder="说明任务需求、补充细节，或输入“确认发布”" disabled={busy||recovering}/>
        <div><span>{input.length}/2000</span><button className="button" disabled={busy||recovering||!input.trim()}>{busy?'处理中…':'发送'}</button></div></form>
    </section></div>
    <section className="panel guide-runs" aria-label="引航员运行记录"><div className="section-heading"><h2>运行记录</h2><button className="text-button" onClick={runs.retry}>刷新记录</button></div>
      <p className="guide-intro">本人最近 20 次运行，记录模型轮数、工具调用、耗时和 token 用量。</p>
      {runs.loading&&<p role="status">正在加载记录…</p>}{runs.error&&<p role="alert">{runs.error}</p>}
      {runs.data?.items.length===0&&<p className="guide-empty">发送一个问题后，这里会出现运行记录。</p>}
      {!!runs.data?.items.length&&<div className="run-table-wrap"><table className="run-table"><thead><tr><th>时间 / 运行</th><th>状态</th><th>模型</th><th>模型 / 工具调用</th><th>耗时</th><th>Token</th></tr></thead><tbody>
        {runs.data.items.map(run=><tr key={run.id}><td><button className="text-button" onClick={()=>void inspectRun(run.id)}>{formatTime(run.started_at)} · {run.id.slice(0,8)}</button></td>
          <td>{({running:'运行中',cancelling:'取消中',succeeded:'成功',failed:'失败',cancelled:'已取消',interrupted:'被重启中断'} as Record<string,string>)[run.status]||run.status}</td>
          <td>{run.model||'规则操作'}</td><td>{run.metrics.model_calls||0} / {run.metrics.tool_calls||0}{!!run.metrics.tool_errors&&`（${run.metrics.tool_errors} 次工具错误）`}</td>
          <td>{run.duration_ms===null?'—':`${(run.duration_ms/1000).toFixed(1)} s`}</td><td>{run.metrics.total_tokens===undefined?'未返回':`${run.metrics.total_tokens}${run.metrics.usage_complete?'':'（不完整）'}`}</td></tr>)}
      </tbody></table></div>}
      {selectedRun&&<div className="run-detail"><div className="section-heading"><h3>运行 {selectedRun.id.slice(0,8)}</h3><button className="text-button" onClick={()=>setSelectedRun(null)}>收起</button></div>
        {selectedRun.error&&<p role="alert">{selectedRun.error}</p>}
        <ol>{selectedRun.events?.filter(e=>e.kind!=='text_delta').map(e=><li key={e.seq}>第 {e.step} 轮 · {e.tool?(toolNames[e.tool]||e.tool):'模型'} · {e.kind.endsWith('started')?'开始':`结束${e.success===false?'（错误）':''} · ${e.duration_ms||0} ms`}</li>)}</ol>
        {selectedRun.result&&<><p className="run-answer">{selectedRun.result.answer}</p>{selectedRun.result.references.map(ref=><a key={`${ref.content_type||'ordinary'}:${ref.resource_id||ref.task_id}`} href={ref.href}>{ref.title} ↗ </a>)}</>}
      </div>}
    </section>
  </>;
}
