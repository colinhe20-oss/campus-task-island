import {useEffect,useRef,useState} from 'react';
import {request} from './api';

export function useResource<T>(url:string|null,retainOnRefresh=false) {
  const [data,setData]=useState<T|null>(null);
  const [loading,setLoading]=useState(Boolean(url));
  const [error,setError]=useState('');
  const previousUrl=useRef<string|null>(null);
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    if(!retainOnRefresh||previousUrl.current!==url)setData(null);
    previousUrl.current=url;setError('');setLoading(Boolean(url));
    if(!url) return ()=>controller.abort();
    request<T>(url,{signal:controller.signal}).then(value=>{if(!controller.signal.aborted)setData(value);})
      .catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:'加载失败');})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[url,attempt,retainOnRefresh]);
  return {data,loading,error,retry:()=>setAttempt(n=>n+1)};
}
