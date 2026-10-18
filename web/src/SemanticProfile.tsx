import {useEffect,useState} from 'react';
import {request} from './api';
type Data={status:string;facts:{tag:string;polarity:string;necessity:string;evidence:string}[];unknown:string[];exclusions:string[];labels:Record<string,string>;profile_version:number;error:string|null};
export function SemanticProfile({disabled,onChanged}:{disabled:boolean;onChanged:()=>void}){
 const [data,setData]=useState<Data|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 async function load(){try{setData(await request<Data>('/api/guide/semantics/preferences'));}catch(e){setError(e instanceof Error?e.message:'标签读取失败');}}
 useEffect(()=>{void load();const timer=setInterval(()=>void load(),10000);return()=>clearInterval(timer);},[]);
 async function correct(tag:string,suppressed:boolean){if(!data)return;setBusy(true);setError('');try{await request('/api/guide/semantics/preferences/correction',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:data.profile_version,tag,suppressed})});await load();onChanged();}catch(e){setError(e instanceof Error?e.message:'标签修改失败');}finally{setBusy(false);}}
 return <section className="semantic-profile" aria-label="参与偏好语义标签"><h4>偏好的语义归纳</h4><p className="guide-intro">{data?.status==='ready'?'已根据原文整理标签；技能属于本人自述。':'语义整理尚未完成，当前使用关键词匹配。'}</p>
 {data?.facts.map((f,i)=><div className="semantic-fact" key={i}><strong>{data.labels[f.tag]||f.tag} · {f.polarity==='negative'?'明确不具备':f.polarity==='unknown'?'尚不确定':'原文支持'}{data.exclusions.includes(f.tag)?' · 已停用':''}</strong><p>依据：“{f.evidence}”</p><button disabled={disabled||busy} className="text-button" onClick={()=>void correct(f.tag,!data.exclusions.includes(f.tag))}>{data.exclusions.includes(f.tag)?'恢复这个标签':'这个归纳不准确，停用'}</button></div>)}
 {!!data?.unknown.length&&<p>待核对表达：{data.unknown.join('、')}</p>}{error&&<p role="alert" className="form-error">{error}</p>}</section>;
}
