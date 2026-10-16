import {Component,useEffect, useState, type FormEvent, type ReactNode} from 'react';
import {createRoot} from 'react-dom/client';
import {rewardNames,rewardText,yuanToFen,acceptanceNames,applicationLabels,requirementNames,type ApplicationRequirements, categories, statusNames, formatTime, request, type Category, type Task, type TaskInput, type TaskList, type User} from './api';
import {useResource} from './hooks';
import {useLiveResource} from './live';
import {TaskTermsPanel} from './TaskTerms';
import {useAuth, LoginPage, LoginRequired, CollaborationPanel} from './Collaboration';
import {ActivitiesPage, PublishActivityPage, ActivityDetailPage, MySpacePage} from './Activities';
import {PublishChoicePage} from './PublishChoice';
import {VolunteerListPage,VolunteerDetailPage,PublishVolunteerPage} from './Volunteers';
import {DiscoveriesPage,PublishDiscoveryPage,DiscoveryDetailPage} from './Discoveries';
import {HomePage,MessagesPage,MessageBadge} from './Home';
import {GuidePage} from './Guide';
import {clearAccountSessionCache} from './session';
import {AccountPage,RegisterPage} from './Accounts';
import './styles.css';
import './collaboration.css';

function useRoute() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const update = () => {setHash(window.location.hash); window.scrollTo(0, 0);};
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const url = new URL(hash.slice(1) || '/home', window.location.origin);
  return {path: url.pathname, query: url.searchParams};
}

function Feedback({loading, error, retry}: {loading: boolean; error: string; retry: () => void}) {
  if (loading) return <div className="state" role="status"><span className="spinner"/>正在加载任务…</div>;
  if (error) return <div className="state error-state" role="alert"><strong>暂时无法显示任务</strong><p>{error}</p><button className="button secondary" onClick={retry}>重新加载</button></div>;
  return null;
}

function TaskCard({task}: {task: Task}) {
  return <a className="task-card" href={`#/tasks/${task.id}`}>
    <div className="card-top"><span className={`badge ${task.category}`}>{categories[task.category]}</span><span className="status-dot">{statusNames[task.status]}{task.is_expired?' · 已截止':task.is_overdue?' · 逾期':''}</span></div>
    <h2>{task.title}</h2><p className="card-description">{task.description}</p>
    <div className="card-facts"><span>接取 <b>{acceptanceNames[task.acceptance_mode]}</b></span><span>地点 <b>{task.location || '暂未设置'}</b></span><span>回报 <b>{rewardText(task)}</b></span></div>
    <div className="card-footer"><span>{formatTime(task.created_at)} 发布</span><span className="card-link">查看详情 ↗</span></div>
  </a>;
}

function ListPage({query}: {query: URLSearchParams}) {
  const activeKeyword = query.get('q') || '';
  const expiredOnly=query.get('expired')==='1';
  const [expired,setExpired]=useState(expiredOnly);
  useEffect(()=>setExpired(expiredOnly),[expiredOnly]);
  const rawCategory = query.get('category') || '';
  const activeCategory = Object.hasOwn(categories, rawCategory) ? rawCategory : '';
  const rawPage = Number(query.get('page') || 1);
  const page = Number.isSafeInteger(rawPage) && rawPage >= 1 && rawPage <= 100000 ? rawPage : 1;
  const [keyword, setKeyword] = useState(activeKeyword);
  const [category, setCategory] = useState(activeCategory);
  useEffect(() => {setKeyword(activeKeyword); setCategory(activeCategory);}, [activeKeyword, activeCategory]);
  const parameters = new URLSearchParams({limit: '20', offset: String((page - 1) * 20)});
  if(expiredOnly)parameters.set('expired_only','true');
  if (activeKeyword) parameters.set('keyword', activeKeyword);
  if (activeCategory) parameters.set('category', activeCategory);
  const resource = useLiveResource<TaskList>(`/api/tasks?${parameters}`);
  function apply(nextPage = 1) {
    const filters = new URLSearchParams();
    if(expired)filters.set('expired','1');
    if (keyword.trim()) filters.set('q', keyword.trim());
    if (category) filters.set('category', category);
    if (nextPage > 1) filters.set('page', String(nextPage));
    const target = `#/tasks${filters.size ? '?' + filters.toString() : ''}`;
    if (window.location.hash === target) resource.retry();
    else window.location.hash = target;
  }
  function clear() {setExpired(false);setKeyword(''); setCategory(''); window.location.hash = '#/tasks'; resource.retry();}
  return <>
    <div className="page-heading"><div><p className="eyebrow">一起把小事做好</p><h1>普通任务大厅</h1><p className="subheading">发现校园里的需求，找到适合你的协作。</p></div></div>
    <form className="filters" onSubmit={event => {event.preventDefault(); apply();}}>
      <label className="search-field"><span>搜索任务</span><input aria-label="搜索任务" placeholder="搜索标题、需求或完成标准" maxLength={200} value={keyword} onChange={event => setKeyword(event.target.value)}/></label>
      <label><span>任务分类</span><select aria-label="任务分类筛选" value={category} onChange={event => setCategory(event.target.value)}><option value="">全部分类</option>{Object.entries(categories).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>截止筛选<select value={expired?'expired':'active'} onChange={e=>setExpired(e.target.value==='expired')}><option value="active">默认列表</option><option value="expired">已截止未接取</option></select></label>
      <button className="button" type="submit">查询</button>{(activeKeyword || activeCategory || expiredOnly) && <button className="reset-button" type="button" onClick={clear}>清除筛选</button>}
    </form>
    <div className="section-heading"><h2>{activeKeyword || activeCategory || expiredOnly ? '搜索结果' : '最新发布'}</h2><span>{resource.data ? `共 ${resource.data.total} 条任务` : '校园互助与协作'}</span></div>
    <Feedback {...resource}/>
    {!resource.loading && resource.data && (resource.data.items.length ? <>
      <div className="task-grid">{resource.data.items.map(task => <TaskCard key={task.id} task={task}/>)}</div>
      {resource.data.total > 20 && <div className="pagination"><button className="button secondary" disabled={page === 1} onClick={() => apply(page - 1)}>上一页</button><span>第 {page} 页</span><button className="button secondary" disabled={page * 20 >= resource.data.total} onClick={() => apply(page + 1)}>下一页</button></div>}
    </> : <div className="state"><strong>{activeKeyword || activeCategory || expiredOnly ? '没有找到匹配的任务' : '还没有任务'}</strong><p>{activeKeyword || activeCategory || expiredOnly ? '换一个关键词或分类，再试试看。' : '把你的第一个需求发布到任务岛。'}</p>{activeKeyword || activeCategory || expiredOnly ? <button className="button secondary" onClick={clear}>查看全部任务</button> : <a className="button" href="#/tasks/new">发布任务</a>}</div>)}
  </>;
}

function PublishPage({copyId}:{copyId?:string}) {
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [rewardType,setRewardType]=useState<'mutual'|'paid'>('mutual');
  const source=useResource<Task>(copyId?`/api/tasks/${encodeURIComponent(copyId)}`:null);
  useEffect(()=>{if(source.data)setRewardType(source.data.reward_type==='paid'?'paid':'mutual');},[source.data]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const text = (name: string) => String(values.get(name) || '').trim();
    const payload: TaskInput = {title: text('title'), category: text('category') as Category,
      description: text('description'), completion_criteria: text('completion_criteria'),location:text('location'),deadline:'',reward_type:rewardType,acceptance_mode:text('acceptance_mode') as TaskInput['acceptance_mode'],application_requirements:Object.fromEntries(Object.keys(applicationLabels).map(key=>[key,text('requirement_'+key)])) as ApplicationRequirements};
    if (!payload.title || !payload.description || !payload.completion_criteria || !payload.location || !text('deadline')) {setError('请填写任务标题、需求说明、完成标准、地点和截止时间。'); return;}
    if (text('reward')) payload.reward = text('reward');
    if(rewardType==='paid'){try{payload.reward_amount_fen=yuanToFen(text('reward_amount'));}catch(e){setError((e as Error).message);return;}if(!payload.reward){setError('有偿任务请填写回报说明。');return;}}
    const deadline = text('deadline');
    if (deadline) payload.deadline = `${deadline.length === 16 ? deadline + ':00' : deadline}+08:00`;
    setSubmitting(true); setError('');
    try {
      const created = await request<Task>('/api/tasks', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      window.location.hash = `#/tasks/${created.id}?published=1`;
    } catch (reason) {setError(reason instanceof Error ? reason.message : '发布失败，请重试。');}
    finally {setSubmitting(false);}
  }
  if(copyId&&source.loading)return <div className="state" role="status">正在读取原任务约定…</div>;
  if(copyId&&source.error)return <div className="state" role="alert">{source.error}<button className="button secondary" onClick={source.retry}>重新加载</button></div>;
  return <>
    <a className="back-link" href="#/tasks/new">← 重新选择发布种类</a>
    <div className="page-heading"><div><p className="eyebrow">让协作从清楚的需求开始</p><h1>发布普通任务</h1><p className="subheading">说明你需要什么，以及怎样算完成。</p></div></div>
    <form className="publish-form panel" onSubmit={submit}>
      <div className="form-section"><h2>任务内容</h2><p>带 * 的项目为必填项。</p></div>
      {source.data&&<p className="info-notice">已复制原任务的基本约定。截止时间、协作人员、申请、阶段、成果和结算记录不会复制。</p>}
      <div className="form-row"><label className="grow">任务标题 *<input name="title" required maxLength={100} defaultValue={source.data?.title||''} placeholder="例如：寻找同学协助拍摄社团活动照片"/></label><label>任务分类 *<select name="category" required defaultValue={source.data?.category||''}><option value="" disabled>请选择分类</option>{Object.entries(categories).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
      <label>需求说明 *<textarea name="description" required maxLength={4000} rows={5} defaultValue={source.data?.description||''} placeholder="介绍任务背景、具体工作和需要的帮助。"/></label>
      <label>完成标准 *<textarea name="completion_criteria" required maxLength={2000} rows={3} defaultValue={source.data?.completion_criteria||''} placeholder="例如：交付 10 张清晰照片，覆盖活动的主要环节。"/></label>
      <div className="form-section separated"><h2>任务安排</h2><p>地点与截止时间必须填写；有偿任务还需填写金额和回报说明。</p></div>
      <div className="form-row"><label className="grow">地点 *<input name="location" required maxLength={200} defaultValue={source.data?.location||''} placeholder="例如：学生活动中心"/></label><label className="grow">截止时间（北京时间）*<input name="deadline" required type="datetime-local"/></label></div>
      <div className="form-section separated"><h2>接取方式与填写要求</h2><p>接取方式和填写要求发布后不能修改。直接接取填写后立即加入，申请后确认需等待发布者选择。</p></div>
      <label>接取方式<select name="acceptance_mode" defaultValue={source.data?.acceptance_mode||'approval'}>{Object.entries(acceptanceNames).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
      <div className="form-row">{Object.entries(applicationLabels).map(([key,label])=><label className="grow" key={key}>{label}<select name={'requirement_'+key} defaultValue={source.data?.application_requirements[key as keyof ApplicationRequirements]||(key==='reason'?'required':'disabled')}>{Object.entries(requirementNames).map(([value,text])=><option key={value} value={value}>{text}</option>)}</select></label>)}</div>
      <label>回报类型<select value={rewardType} onChange={e=>setRewardType(e.target.value as 'mutual'|'paid')}><option value="mutual">无偿互助</option><option value="paid">有偿任务</option></select></label>
      {rewardType==='paid'&&<label>固定报酬（人民币元）*<input name="reward_amount" inputMode="decimal" required defaultValue={source.data?.reward_amount_fen?`${Math.floor(source.data.reward_amount_fen/100)}.${String(source.data.reward_amount_fen%100).padStart(2,'0')}`:''} placeholder="例如：50.00"/><small>验收完成后双方记录线下结算，发布后金额不可修改。</small></label>}
      <label>回报说明{rewardType==='paid'?' *':''}<input name="reward" required={rewardType==='paid'} maxLength={500} defaultValue={source.data?.reward||''} placeholder={rewardType==='paid'?'例如：验收完成后线下支付全额':'例如：互助说明；如需支付报酬请选择有偿任务'}/></label>
      {error && <div className="form-error" role="alert">{error} 你填写的内容已保留。</div>}
      <div className="form-actions"><a className="button secondary" href="#/tasks">返回大厅</a><button className="button" type="submit" disabled={submitting}>{submitting ? '正在发布…' : '确认发布'}</button></div>
    </form>
  </>;
}

function DetailPage({id, published, user}: {id: string; published: boolean; user:User|null}) {
  const resource = useLiveResource<Task>(`/api/tasks/${encodeURIComponent(id)}`);
  const raw=resource.data;
  // Older running servers may return task records before acceptance/reward rules
  // were added. Normalize those optional legacy fields before detail panels read them.
  const task=raw?{...raw,
    acceptance_mode:raw.acceptance_mode||'approval',
    application_requirements:Object.assign({reason:'required',experience:'disabled',supplement:'disabled'},raw.application_requirements||{}),
    reward_type:raw.reward_type||'legacy',
    reward_amount_fen:raw.reward_amount_fen??null,
    terms_version:raw.terms_version||1,
    collaboration_version:raw.collaboration_version||1,
  } as Task:null;
  return <>
    <a className="back-link" href="#/tasks">← 返回任务大厅</a>
    {published && <div className="success-notice" role="status">✓ 任务发布成功，已经出现在任务大厅。</div>}
    <Feedback {...resource}/>
    {task && task.id===id && <article className="detail panel">
      <div className="card-top"><span className={`badge ${task.category}`}>{categories[task.category]}</span><span className="status-dot">{statusNames[task.status]}{task.is_expired?' · 已截止':task.is_overdue?' · 逾期':''}</span></div>
      <h1>{task.title}</h1><p className="detail-time">{formatTime(task.created_at)} 发布 · 北京时间</p>
      <dl className="detail-facts"><div><dt>地点</dt><dd>{task.location || '暂未设置'}</dd></div><div><dt>截止时间</dt><dd>{formatTime(task.deadline)}</dd></div><div><dt>回报说明</dt><dd>{rewardText(task)}{task.reward?'：'+task.reward:''}</dd></div></dl>
      <section className="detail-section"><h2>需求说明</h2><p>{task.description}</p></section>
      <section className="detail-section"><h2>完成标准</h2><p>{task.completion_criteria}</p></section>
      <section className="detail-section"><h2>接取方式与要求</h2><p>{acceptanceNames[task.acceptance_mode]}{task.acceptance_mode==='direct'?'：确认条件后立即加入。':'：提交后等待发布者确认。'}</p>{Object.entries(applicationLabels).map(([key,label])=><p key={key}>{label}：{requirementNames[task.application_requirements[key as keyof ApplicationRequirements]]}</p>)}</section>
      {user&&(user.id===task.publisher_id||user.id===task.assignee_id)&&<TaskTermsPanel task={task} user={user} onChange={resource.retry}/>}
      <CollaborationPanel task={task} user={user} onChange={resource.retry}/>
      <div className="task-id">任务编号：{task.id}</div>
    </article>}
  </>;
}

class PageErrorBoundary extends Component<{children:ReactNode;resetKey:string},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidUpdate(previous:Readonly<{children:ReactNode;resetKey:string}>){
    if(this.state.failed&&previous.resetKey!==this.props.resetKey)this.setState({failed:false});
  }
  componentDidCatch(error:Error){console.error('页面渲染失败',error);}
  render(){return this.state.failed?<div className="state error-state" role="alert"><strong>这个页面暂时无法显示</strong><p>页面数据格式或组件发生异常。可以重新加载页面，或返回“我的空间”后重试。</p><button className="button secondary" onClick={()=>window.location.reload()}>重新加载</button> <a className="button secondary" href="#/mine">返回我的空间</a></div>:this.props.children;}
}

function App() {
  const route = useRoute();
  const auth=useAuth();
  const [logoutError,setLogoutError]=useState('');
  const [logoutBusy,setLogoutBusy]=useState(false);
  async function logout() {
    setLogoutBusy(true);setLogoutError('');
    try {await request('/api/auth/logout',{method:'POST'});if(auth.user)clearAccountSessionCache(auth.user.id);auth.setUser(null);window.location.hash='/home';}
    catch(reason){setLogoutError(reason instanceof Error?reason.message:'退出失败');}
    finally{setLogoutBusy(false);}
  }
  const detail = /^\/tasks\/([^/]+)$/.exec(route.path);
  const activityDetail = /^\/activities\/([^/]+)$/.exec(route.path);
  const volunteerDetail = /^\/volunteers\/([^/]+)$/.exec(route.path);
  const discoveryDetail = /^\/discoveries\/([^/]+)$/.exec(route.path);
  const mine = ['/mine','/mine/registrations','/mine/activities','/mine/volunteer-records','/mine/discoveries'].includes(route.path);
  const accountPage=route.path==='/mine/account';
  const publishing = route.path==='/tasks/new'||route.path==='/activities/new';
  let page;
  if (route.path === '/login') page=<LoginPage onLogin={auth.setUser} next={route.query.get('next')||'/home'}/>;
  else if (route.path === '/register') page=<RegisterPage onRegister={auth.setUser}/>;
  else if (auth.loading&&(route.path==='/tasks/new'||mine||accountPage||route.path==='/guide'||route.path==='/home'||route.path==='/messages'||route.path.startsWith('/activities')||route.path.startsWith('/volunteers')||route.path.startsWith('/discoveries'))) page=<div className="state" role="status">正在确认登录状态…</div>;
  else if (route.path === '/home'||route.path==='/') page=<HomePage key={auth.user?.id||'guest'} user={auth.user}/>;
  else if (route.path === '/messages') page=<MessagesPage key={auth.user?.id||'guest'} user={auth.user}/>;
  else if (accountPage) page=<AccountPage key={auth.user?.id||'guest'} user={auth.user}/>;
  else if (route.path === '/tasks/new') page = !auth.user?<LoginRequired/>:route.query.get('type')==='ordinary'?<PublishPage copyId={route.query.get('copy')||undefined}/>:route.query.get('type')==='activity'?<PublishActivityPage/>:route.query.get('type')==='volunteer'?<PublishVolunteerPage/>:route.query.get('type')==='discovery'?<PublishDiscoveryPage/>:<PublishChoicePage/>;
  else if (mine) page=auth.user?<MySpacePage key={auth.user.id} user={auth.user} path={route.path} query={route.query}/>:<LoginRequired/>;
  else if (route.path === '/discoveries') page=<DiscoveriesPage key={auth.user?.id||'guest'} query={route.query}/>;
  else if (discoveryDetail) page=<DiscoveryDetailPage key={discoveryDetail[1]+(auth.user?.id||'guest')} id={discoveryDetail[1]} user={auth.user} published={route.query.get('published')==='1'}/>;
  else if (route.path === '/volunteers') page=<VolunteerListPage key={auth.user?.id||'guest'} query={route.query}/>;
  else if (volunteerDetail) page=<VolunteerDetailPage key={volunteerDetail[1]+(auth.user?.id||'guest')} id={volunteerDetail[1]} user={auth.user} published={route.query.get('published')==='1'}/>;
  else if (route.path === '/activities') page=<ActivitiesPage key={auth.user?.id||'guest'} query={route.query} user={auth.user}/>;
  else if (route.path === '/activities/new') page=auth.user?<PublishActivityPage/>:<LoginRequired/>;
  else if (activityDetail) page=<ActivityDetailPage key={activityDetail[1]+(auth.user?.id||'guest')} id={activityDetail[1]} user={auth.user} published={route.query.get('published')==='1'}/>;
  else if (route.path === '/guide') page=auth.user?<GuidePage key={auth.user.id} user={auth.user}/>:<LoginRequired/>;
  else if (route.path === '/tasks') page = <ListPage query={route.query}/>;
  else if (detail) page = <DetailPage key={detail[1]+(auth.user?.id||'guest')} id={detail[1]} user={auth.user} published={route.query.get('published') === '1'}/>;
  else page = <div className="state"><strong>页面不存在</strong><a className="button secondary" href="#/tasks">返回任务大厅</a></div>;
  return <div className="app-shell"><aside className="sidebar"><a href="#/home" className="brand"><span className="brand-icon">岛</span><span>校园任务岛<small>CAMPUS TASK ISLAND</small></span></a>
    <p className="nav-caption">校园协作</p><nav><a className={route.path==='/home'||route.path==='/'?'active':''} href="#/home"><span>⌂</span> 岛屿首页</a><a className={route.path==='/tasks'||(detail&&route.path!=='/tasks/new')?'active':''} href="#/tasks"><span>▦</span> 普通任务</a>
      <a className={route.path.startsWith('/activities')&&!publishing?'active':''} href="#/activities"><span>◷</span> 综素活动</a>
      <a className={route.path.startsWith('/volunteers')?'active':''} href="#/volunteers"><span>♡</span> 志愿服务</a>
      <a className={route.path.startsWith('/discoveries')?'active':''} href="#/discoveries"><span>⌖</span> 校园发现</a>
      <a className={route.path==='/messages'?'active':''} href="#/messages"><span>◉</span> 消息{auth.user&&<MessageBadge key={auth.user.id}/>}</a>
      <a className={publishing?'active':''} href="#/tasks/new"><span>＋</span> 发布任务</a><a className={mine?'active':''} href="#/mine"><span>▤</span> 我的空间</a><a className={route.path==='/guide'?'active':''} href="#/guide"><span>✦</span> 引航员</a></nav>
    <div className="account-box">{auth.loading?<span>正在确认登录状态…</span>:auth.user?<><strong>{auth.user.display_name}</strong><small>{auth.user.username}</small><a className="text-button" href="#/mine/account">账号信息</a><button className="text-button" onClick={()=>void logout()} disabled={logoutBusy}>{logoutBusy?'正在退出…':'退出登录'}</button></>:<><span>登录后开始协作</span><a href={`#/login?next=${encodeURIComponent(window.location.hash.slice(1)||'/home')}`} className="button secondary">登录</a></>} {logoutError&&<p role="alert">{logoutError}</p>}</div>
    <div className="sidebar-note"><span className="small-island">✦</span><strong>一点帮助，一次协作。</strong><p>从校园里的小需求开始。</p></div><div className="sidebar-footer">校园任务岛 · 初版</div></aside><main className={`main-content${route.path==='/home'||route.path==='/'?' home-content':''}`}><PageErrorBoundary resetKey={route.path}>{page}</PageErrorBoundary></main></div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
