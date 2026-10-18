import {useState} from 'react';
import './trace.css';

export type TraceEvent={seq:number;kind:string;step?:number;tool?:string;call_id?:string;success?:boolean;duration_ms?:number;at?:string;summary?:string};
export function RunTrace({events,status,names}:{events:TraceEvent[];status:string;names:Record<string,string>}){
  const [view,setView]=useState<'time'|'round'>('time');
  const [filter,setFilter]=useState('');
  const [chosen,setChosen]=useState<number>();
  const first=events.find(e=>e.at)?.at;
  const origin=first?Date.parse(first):0;
  const rows=events.filter(e=>e.kind==='model_started'||e.kind==='tool_started').map(start=>{
    const tool=start.kind==='tool_started';
    const finish=events.find(e=>e.seq>start.seq&&e.kind===(tool?'tool_finished':'model_finished')&&
      (tool&&start.call_id?e.call_id===start.call_id:e.step===start.step&&e.tool===start.tool));
    const offset=start.at?Math.max(0,Date.parse(start.at)-origin):start.seq*20;
    const duration=finish?.duration_ms??0;
    return {start,finish,offset,duration,label:tool?(names[start.tool!]||start.tool!):'模型响应',
      state:finish?(finish.success===false?'失败':'完成'):['running','cancelling'].includes(status)?'执行中':status==='succeeded'?'完成':'已中止'};
  });
  const total=Math.max(1,...rows.map(r=>r.offset+r.duration));
  const visible=rows.filter(r=>(r.label+' '+r.start.tool).toLowerCase().includes(filter.toLowerCase()));
  const selected=rows.find(r=>r.start.seq===chosen);
  const rounds=[...new Set(rows.map(r=>r.start.step||0))];
  return <section className="trace" aria-label="工具调用轨迹">
    <div className="trace-head"><strong>调用轨迹</strong><span>{rounds.length} 轮 · {rows.filter(r=>r.start.tool).length} 次工具调用</span>
      <button type="button" aria-pressed={view==='time'} onClick={()=>setView('time')}>时长</button><button type="button" aria-pressed={view==='round'} onClick={()=>setView('round')}>轮次</button>
      <input aria-label="搜索调用轨迹" placeholder="搜索工具…" value={filter} onChange={e=>setFilter(e.target.value)}/></div>
    {!rows.length?<p className="trace-empty">发送问题后显示模型与工具的真实调用过程。</p>:<>
    <div className="trace-chart" role="img" aria-label="模型与工具调用时间轴，紫色为模型，橙色为工具，红色为失败">
      {['model','tool'].map((lane,i)=><div className="trace-lane" key={lane}><span>{i?'工具':'模型'}</span><div>{visible.filter(r=>Boolean(r.start.tool)===Boolean(i)).map(r=>{
        const peers=rows.filter(x=>x.start.step===r.start.step&&Boolean(x.start.tool)===Boolean(i));
        const slot=peers.findIndex(x=>x.start.seq===r.start.seq);
        const roundWidth=95/Math.max(1,rounds.length);
        const left=view==='time'?r.offset/total*95:rounds.indexOf(r.start.step||0)*roundWidth+slot*roundWidth/Math.max(1,peers.length);
        const width=view==='time'?Math.max(1,r.duration/total*95):Math.max(.5,roundWidth*.85/Math.max(1,peers.length));
        return <button key={r.start.seq} className={`${lane} ${r.state==='失败'?'error':''} ${r.state==='执行中'?'active':''}`} style={{left:`${left}%`,width:`${width}%`}} title={`第${r.start.step}轮 ${r.label} ${r.state} ${r.duration} ms`} aria-label={`${r.label} ${r.state}`} onClick={()=>setChosen(r.start.seq)}/>;
      })}</div></div>)}
      <div className="trace-axis"><span>0</span><span>{view==='time'?`${(total/1000).toFixed(2)} 秒`:`${rounds.length} 轮`}</span></div>
    </div>
    <div className="trace-rows">{visible.map(r=><button type="button" className={`trace-row ${r.state==='失败'?'error':''}`} key={r.start.seq} onClick={()=>setChosen(chosen===r.start.seq?undefined:r.start.seq)}>
      <span className={r.start.tool?'trace-tool':'trace-model'}>{r.start.tool?'工具':'模型'}</span><small>第 {r.start.step} 轮</small><strong>{r.label}</strong><span>{r.state}</span><small>{r.finish?`${r.duration} ms`:'—'}</small>
      <span className="trace-summary">{r.finish?.summary||(r.finish?'响应完成':r.start.summary||r.state)}</span>
    </button>)}</div>
    {selected&&<div className="trace-selected"><strong>{selected.label}</strong><p>{selected.start.summary||'模型根据当前对话选择下一步操作'}</p><p>{selected.finish?.summary||selected.state}</p><small>开始：{selected.start.at?new Date(selected.start.at).toLocaleTimeString('zh-CN'):'—'} · 耗时 {selected.duration} ms</small></div>}
    </>}
    <p className="trace-foot">模型响应与工具执行使用真实运行事件；不展示模型内部推理。</p>
  </section>;
}
