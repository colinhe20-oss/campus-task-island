import {useEffect,useState,useRef} from 'react';
import {request} from './api';

type Timed = {server_time:string;next_boundary:string|null};

// performance.now 只计算流逝时间，浏览器的系统日期不会改变报名窗口判断。
export function useLiveResource<T extends Timed>(url:string|null) {
  const [data,setData]=useState<T|null>(null), [error,setError]=useState(''), [loading,setLoading]=useState(true);
  const [revision,setRevision]=useState(0), [serverNow,setServerNow]=useState(0);
  useEffect(()=>{setData(null);setError('');setLoading(true);},[url]);
  useEffect(()=>{
    if(!url){setData(null);setLoading(false);return;}
    let disposed=false, requestNumber=0, controller:AbortController|undefined;
    let poll:ReturnType<typeof setTimeout>, boundary:ReturnType<typeof setTimeout>, tick:ReturnType<typeof setInterval>;
    const clearTimers=()=>{clearTimeout(poll);clearTimeout(boundary);clearInterval(tick);};
    async function load() {
      clearTimers();controller?.abort();controller=new AbortController();const number=++requestNumber;
      try {
        const value=await request<T>(url!,{signal:controller.signal});
        if(disposed||number!==requestNumber)return;
        setData(value);setError('');
        const epoch=Date.parse(value.server_time), received=performance.now();
        setServerNow(epoch);
        if(document.visibilityState==='visible') {
          tick=setInterval(()=>setServerNow(epoch+performance.now()-received),1000);
          poll=setTimeout(()=>void load(),15000);
          if(value.next_boundary) {
            const delay=Date.parse(value.next_boundary)-epoch;
            if(delay>0&&delay<=15000) boundary=setTimeout(()=>void load(),Math.max(100,delay+80));
          }
        }
      }catch(reason){
        if(disposed||number!==requestNumber||(reason instanceof Error&&reason.name==='AbortError'))return;
        setError(reason instanceof Error?reason.message:'请求失败');
        if(document.visibilityState==='visible')poll=setTimeout(()=>void load(),15000);
      }finally{if(!disposed&&number===requestNumber)setLoading(false);}
    }
    const visibility=()=>{if(document.visibilityState==='visible')void load();else clearTimers();};
    document.addEventListener('visibilitychange',visibility);
    const changed=()=>void load();window.addEventListener('campus:changed',changed);void load();
    return ()=>{disposed=true;controller?.abort();clearTimers();document.removeEventListener('visibilitychange',visibility);window.removeEventListener('campus:changed',changed);};
  },[url,revision]);
  return {data,error,loading,serverNow,retry:()=>setRevision(v=>v+1)};
}

export function LiveFeedback({loading,error,retry,label='活动'}:{loading:boolean;error:string;retry:()=>void;label?:string}) {
  return <>{loading&&<p className="state" role="status">正在加载{label}…</p>}{error&&<div className="form-error" role="alert">{error} 当前结果可能已变化。<button className="text-button" onClick={retry}>重新加载</button></div>}</>;
}


export function useManagementFocus(ready:boolean){const focused=useRef(false);useEffect(()=>{if(!ready||focused.current)return;focused.current=true;const query=window.location.hash.split('?')[1]||'';if(new URLSearchParams(query).get('manage')==='1')document.getElementById('registration-management')?.scrollIntoView({behavior:'smooth'});},[ready]);}
