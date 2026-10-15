import {useState,type FormEvent} from 'react';
import {request,type User} from './api';
import {useResource} from './hooks';
import {LoginRequired} from './Collaboration';

type Blocker={kind:string;title:string;href:string};
type AccountStatus={username:string;display_name:string;account_status:'active'|'closed';can_close:boolean;blockers:Blocker[]};

export function RegisterPage({onRegister}:{onRegister:(user:User)=>void}){
  const [error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [showPassword,setShowPassword]=useState(false);
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();const form=new FormData(event.currentTarget);
    const password=String(form.get('password')||''),confirmation=String(form.get('password_confirmation')||'');
    if(password!==confirmation){setError('两次输入的密码不一致。');return;}
    setBusy(true);setError('');
    try{
      const user=await request<User>('/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        username:String(form.get('username')||''),display_name:String(form.get('display_name')||''),password,
      })});
      onRegister(user);window.location.hash='/home';
    }catch(reason){setError(reason instanceof Error?reason.message:'注册失败，请重试。');}
    finally{setBusy(false);}
  }
  return <><a className="back-link" href="#/login">← 返回登录</a><div className="page-heading"><div><p className="eyebrow">加入校园协作</p><h1>创建普通账号</h1><p className="subheading">注册后即可发布和参与普通任务、综素活动、志愿服务与校园发现。</p></div></div>
    <form className="panel publish-form login-form" onSubmit={submit}>
      <label>账号名 *<input name="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9._-]{3,32}" autoComplete="username" placeholder="3–32 位字母、数字、点、下划线或连字符"/><small>账号名会统一转换为小写，注销后不能再次使用。</small></label>
      <label>昵称 *<input name="display_name" required minLength={1} maxLength={40} autoComplete="nickname" placeholder="其他同学看到的名称"/></label>
      <label>密码 *<input name="password" type={showPassword?'text':'password'} required minLength={6} maxLength={128} autoComplete="new-password"/><small>至少 6 个字符；系统不会保存明文密码。</small></label>
      <label>再次输入密码 *<input name="password_confirmation" type={showPassword?'text':'password'} required minLength={6} maxLength={128} autoComplete="new-password"/></label>
      <button type="button" className="button secondary password-visibility" aria-pressed={showPassword} onClick={()=>setShowPassword(value=>!value)}>{showPassword?'隐藏密码':'显示密码'}</button>
      <p className="muted">所有登录账号都可以发布综素活动和志愿服务；认定说明及小时为活动方记录，学校正式认定尚未对接。当前没有公开密码找回功能；忘记密码请联系服务主机管理员。</p>
      {error&&<div className="form-error" role="alert">{error}</div>}
      <div className="form-actions"><a className="button secondary" href="#/login">已有账号</a><button className="button" disabled={busy}>{busy?'正在创建…':'创建账号'}</button></div>
    </form>
  </>;
}

export function AccountPage({user,onClosed}:{user:User|null;onClosed:()=>void}){
  const resource=useResource<AccountStatus>(user?'/api/me/account':null,true);
  const [password,setPassword]=useState(''),[confirmed,setConfirmed]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false),[closed,setClosed]=useState(false);
  if(!user)return <LoginRequired/>;
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();setBusy(true);setError('');
    try{
      await request('/api/me/account/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password,confirmed})});
      setClosed(true);setTimeout(onClosed,1400);
    }catch(reason){setError(reason instanceof Error?reason.message:'注销失败，请重试。');resource.retry();}
    finally{setBusy(false);}
  }
  return <><div className="page-heading"><div><p className="eyebrow">账号资料与退出</p><h1>账号与隐私</h1><p className="subheading">查看本人账号状态，或在处理完未完成事项后注销账号。</p></div></div>
    {closed?<div className="success-notice" role="status">账号已注销，正在退出登录并返回登录页…</div>:<>
      <section className="panel account-panel"><h2>当前账号</h2><dl className="account-details"><div><dt>昵称</dt><dd>{resource.data?.display_name||user.display_name}</dd></div><div><dt>账号名</dt><dd>{resource.data?.username||user.username}</dd></div><div><dt>账号状态</dt><dd>正常</dd></div></dl>
        <p className="muted">注销会立即终止所有会话，匿名保留业务历史，且不能自助恢复。账号名不会释放给其他人。</p>
      </section>
      {resource.loading&&<div className="state" role="status">正在检查未完成事项…</div>}
      {resource.error&&<div className="state error-state" role="alert"><strong>暂时无法检查账号状态</strong><p>{resource.error}</p><button className="button secondary" onClick={resource.retry}>重新检查</button></div>}
      {resource.data&&<section className="panel account-panel"><h2>注销前检查</h2>
        {resource.data.blockers.length?<><p className="muted">请先处理以下事项。系统不会替你自动取消或结束业务：</p><ul className="account-blockers">{resource.data.blockers.map((item,index)=><li key={`${item.kind}:${item.href}:${index}`}><a href={item.href}>{item.title} ↗</a></li>)}</ul></>:<p>没有发现阻止注销的未完成业务。</p>}
        <form className="publish-form account-close-form" onSubmit={submit}>
          <label>输入当前密码以确认本人操作<input type="password" autoComplete="current-password" required maxLength={200} value={password} onChange={event=>setPassword(event.target.value)}/></label>
          <label className="condition-confirm"><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/>我理解账号注销后不能恢复，且历史记录会匿名保留</label>
          {error&&<div className="form-error" role="alert">{error} 请刷新检查清单后再试。</div>}
          <button className="button danger-button" disabled={busy||!resource.data.can_close||!confirmed}>{busy?'正在注销…':'注销本人账号'}</button>
        </form>
      </section>}
    </>}
  </>;
}
