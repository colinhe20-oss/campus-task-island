import {useState,type FormEvent} from 'react';
import {request,formatTime,formatMoney,yuanToFen,type Task} from './api';
import {useResource} from './hooks';

type Difference={stage_title?:string;field:string;before:unknown;after:unknown};
type Agreement={deadline:string;description:string;completion_criteria:string;reward_type:string;reward_amount_fen:number|null;reward:string|null;stages:unknown[]};
type ChangeStage={id:string;title:string;version:number;status:string;deadline:string;completion_criteria:string};
export type ChangeState={server_time:string;next_boundary:string|null;terms_version:number;agreement:Agreement;stages:ChangeStage[];items:{id:string;requester_id:string;terms_version:number;collaboration_version:number|null;kind:string;reason:string;status:string;version:number;review_reason:string;created_at:string;differences:Difference[]}[]};
const labels:Record<string,string>={deadline:'整体截止时间',description:'工作范围',completion_criteria:'整项完成标准',reward_type:'回报类型',reward_amount_fen:'固定报酬',cancellation_settlement_fen:'取消结算金额',reward:'回报说明',initial_stages:'首次阶段安排',collaboration_action:'协作状态'};
const local=(s:string|null)=>s?new Date(Date.parse(s)+8*3600000).toISOString().slice(0,16):'';
function value(field:string,v:unknown):string{
  if(v===null||v===undefined||v==='')return '无';
  if(field.endsWith('deadline'))return formatTime(String(v));
  if(field==='reward_amount_fen')return formatMoney(Number(v));
  if(field==='cancellation_settlement_fen')return formatMoney(Number(v))+(Number(v)===0?'（无需结算）':'');
  if(field==='reward_type')return ({mutual:'无偿互助',paid:'有偿任务',legacy:'历史回报未分类'} as Record<string,string>)[String(v)]||String(v);
  if(field==='collaboration_action')return ({published:'待接取',in_progress:'协作中',pending_review:'待验收',paused:'协作暂停',cancel:'已取消',pause:'暂停协作',resume:'恢复协作'} as Record<string,string>)[String(v)]||String(v);
  if(Array.isArray(v))return v.map((s,i)=>{const row=s as Record<string,string>;return `${i+1}. ${row.title} · ${row.responsible_role==='publisher'?'发布者':'接取者'}负责 · ${formatTime(row.deadline)}\n${row.completion_criteria}`;}).join('\n');
  return String(v);
}
export function Diff({differences}:{differences:Difference[]}){
  return <div className="change-differences">{differences.map(d=><div className="record" key={d.field}><strong>{d.stage_title?d.stage_title+' · ':''}{labels[d.field]||(d.field.endsWith('deadline')?'阶段截止时间':'阶段完成要求')}</strong><div className="form-row"><div className="grow"><small>变更前</small><p style={{whiteSpace:'pre-wrap'}}>{value(d.field,d.before)}</p></div><div className="grow"><small>拟变更为</small><p style={{whiteSpace:'pre-wrap'}}>{value(d.field,d.after)}</p></div></div></div>)}</div>;
}

export function AgreementLink({taskId,version}:{taskId:string;version:number|null}){
  const [open,setOpen]=useState(false);
  const resource=useResource<{fields:Agreement}>(open&&version?`/api/tasks/${taskId}/agreements/${version}`:null);
  if(!version)return <p className="muted">历史成果未记录约定版本。</p>;
  return <div><button className="text-button" onClick={()=>setOpen(v=>!v)}>查看提交时约定 · 版本 {version}</button>{open&&<div className="record">{resource.loading&&<p>正在读取约定…</p>}{resource.error&&<p role="alert">{resource.error}<button onClick={resource.retry}>重试</button></p>}{resource.data&&<><p>截止：{formatTime(resource.data.fields.deadline)}</p><p>{resource.data.fields.description}</p><p>完成标准：{resource.data.fields.completion_criteria}</p><p>{value('reward_type',resource.data.fields.reward_type)} · {value('reward_amount_fen',resource.data.fields.reward_amount_fen)} · {resource.data.fields.reward}</p>{resource.data.fields.stages.length>0&&<pre style={{whiteSpace:'pre-wrap'}}>{value('initial_stages',resource.data.fields.stages)}</pre>}</>}</div>}</div>;
}

export function ChangeForm({task,state,busy,submit}:{task:Task;state:ChangeState;busy:boolean;submit:(body:unknown)=>Promise<void>}){
  const [base,setBase]=useState<ChangeState|null>(null),[selected,setSelected]=useState<Record<string,boolean>>({});
  const [preview,setPreview]=useState<{body:unknown;diff:Difference[]}|null>(null),[error,setError]=useState('');
  const source=base||state;
  const needsRebuild=!!base&&(base.terms_version!==state.terms_version||base.stages.some(s=>state.stages.find(latest=>latest.id===s.id)?.version!==s.version));
  const toggle=(key:string)=>{setBase(v=>v||state);setSelected(v=>({...v,[key]:!v[key]}));setPreview(null);};
  function prepare(e:FormEvent<HTMLFormElement>){
    e.preventDefault();setError('');const data=new FormData(e.currentTarget);const changes:Record<string,unknown>={},diff:Difference[]=[];
    const add=(key:string,before:unknown,after:unknown)=>{changes[key]=after;if(before!==after)diff.push({field:key,before,after});};
    try{
      if(selected.deadline)add('deadline',source.agreement.deadline,String(data.get('deadline'))+':00+08:00');
      for(const key of ['description','completion_criteria'] as const)if(selected[key])add(key,source.agreement[key],String(data.get(key)).trim());
      if(selected.reward){
        const reward_type=String(data.get('reward_type'));const reward_amount_fen=reward_type==='paid'?yuanToFen(String(data.get('amount'))):null;
        const reward=String(data.get('reward')||'').trim()||null;if(reward_type==='paid'&&!reward)throw new Error('有偿任务必须填写回报说明。');changes.reward={reward_type,reward_amount_fen,reward};
        for(const [field,after] of Object.entries(changes.reward as object)){const before=source.agreement[field as keyof Agreement];if(before!==after)diff.push({field,before,after});}
      }
      const stages=[];
      for(const s of source.stages){const update:Record<string,unknown>={id:s.id,version:s.version};
        for(const key of ['deadline','completion_criteria'] as const)if(selected[s.id+'.'+key]){
          const after=String(data.get(s.id+'.'+key)).trim()+(key==='deadline'?':00+08:00':'');update[key]=after;diff.push({field:`stages.${s.id}.${key}`,stage_title:s.title,before:s[key],after});
        }
        if(Object.keys(update).length>2)stages.push(update);
      }
      if(stages.length)changes.stages=stages;
      if(!diff.length)throw new Error('请选择需要修改的内容，并填写不同的新约定。');
      const body={version:source.terms_version,reason:String(data.get('reason')).trim(),changes};setPreview({body,diff});
    }catch(err){setError((err as Error).message);}
  }
  const pendingReview=task.status==='pending_review'||state.stages.some(s=>s.status==='submitted');
  return <form className="publish-form workspace-section" onSubmit={prepare} onInput={()=>{setBase(v=>v||state);setPreview(null);}}>
    <h3>提出约定变更</h3><p>双方确认后才生效。整体截止时间不会自动调整阶段时间。</p>
    {pendingReview&&<p className="info-notice">有成果待验收：修改工作范围或完成标准前，请先在协作面板退回补充。时间和回报仍可协商。</p>}
    {needsRebuild&&<p role="alert">约定或阶段执行状态已更新，输入仍保留。<button type="button" onClick={()=>{setBase(state);setPreview(null);}}>核对后以最新版本重建预览</button></p>}
    <label><input type="checkbox" checked={!!selected.deadline} onChange={()=>toggle('deadline')}/>修改整体截止时间</label>
    {selected.deadline&&<label>新整体截止（北京时间）<input name="deadline" type="datetime-local" defaultValue={local(source.agreement.deadline)} required/></label>}
    {(['description','completion_criteria'] as const).map(key=><div key={key}><label><input type="checkbox" disabled={pendingReview&&!selected[key]} checked={!!selected[key]} onChange={()=>toggle(key)}/>修改{labels[key]}</label>{selected[key]&&<label>新的{labels[key]}<textarea name={key} defaultValue={source.agreement[key]} required maxLength={key==='description'?4000:2000}/></label>}</div>)}
    <label><input type="checkbox" checked={!!selected.reward} onChange={()=>toggle('reward')}/>修改回报约定</label>
    {selected.reward&&<fieldset><legend>完整回报配置</legend><label>回报类型<select name="reward_type" defaultValue={source.agreement.reward_type==='paid'?'paid':'mutual'}><option value="mutual">无偿互助</option><option value="paid">有偿任务</option></select></label><label>金额（元，有偿时必填）<input name="amount" inputMode="decimal" defaultValue={source.agreement.reward_amount_fen===null?'':(BigInt(source.agreement.reward_amount_fen)/100n).toString()+'.'+(BigInt(source.agreement.reward_amount_fen)%100n).toString().padStart(2,'0')}/></label><label>回报说明（有偿时必填）<textarea name="reward" defaultValue={source.agreement.reward||''} maxLength={500}/></label></fieldset>}
    {source.stages.filter(s=>s.status!=='confirmed').map(s=><fieldset key={s.id}><legend>{s.title} · 执行版本 {s.version}</legend>{(['deadline','completion_criteria'] as const).map(key=><div key={key}><label><input type="checkbox" disabled={key==='completion_criteria'&&s.status==='submitted'&&!selected[s.id+'.'+key]} checked={!!selected[s.id+'.'+key]} onChange={()=>toggle(s.id+'.'+key)}/>修改{key==='deadline'?'阶段截止时间':'阶段完成要求'}</label>{selected[s.id+'.'+key]&&(key==='deadline'?<input type="datetime-local" name={s.id+'.'+key} defaultValue={local(s.deadline)} required/>:<textarea name={s.id+'.'+key} defaultValue={s.completion_criteria} required maxLength={1000}/>)}</div>)}</fieldset>)}
    <label>变更原因 *<textarea name="reason" required maxLength={2000}/></label>
    {error&&<p role="alert" className="form-error">{error}</p>}
    <button className="button secondary" disabled={busy}>核对前后差异</button>
    {preview&&<div className="workspace-section"><h4>提交前确认 · 基础版本 {source.terms_version}</h4><Diff differences={preview.diff}/><p>确认前继续执行原约定；提交后等待对方处理。</p><button type="button" className="button" disabled={busy||needsRebuild} onClick={()=>void submit(preview.body)}>提交变更申请</button></div>}
  </form>;
}
