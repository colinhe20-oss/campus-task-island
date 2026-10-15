export const rewardNames = {mutual:'无偿互助',paid:'有偿任务',legacy:'历史回报未分类'} as const;
export function yuanToFen(text:string):number {
  if(!/^(0|[1-9]\d*)(\.\d{1,2})?$/.test(text.trim()))throw new Error('金额请按元填写，最多两位小数。');
  const [whole,fraction='']=text.trim().split('.');const amount=BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0'));
  if(amount<=0n||amount>BigInt(Number.MAX_SAFE_INTEGER))throw new Error('金额必须为正数且在支持范围内。');
  return Number(amount);
}
export function formatMoney(fen:number|null|undefined):string {
  if(fen==null)return '金额待补充';const n=BigInt(fen);return `¥${n/100n}.${String(n%100n).padStart(2,'0')}`;
}
export function rewardText(task:{reward_type:'mutual'|'paid'|'legacy';reward_amount_fen?:number|null}) {
  return rewardNames[task.reward_type]+(task.reward_type==='paid'?' · '+formatMoney(task.reward_amount_fen):'');
}
export type RequirementLevel = 'disabled'|'optional'|'required';
export type ApplicationRequirements = {reason:RequirementLevel;experience:RequirementLevel;supplement:RequirementLevel};
export const applicationLabels = {reason:'申请理由',experience:'技能经验',supplement:'补充说明'} as const;
export const requirementNames = {disabled:'不启用',optional:'选填',required:'必填'} as const;
export const acceptanceNames = {approval:'申请后确认',direct:'直接接取'} as const;
export const categories = {
  learning: '学习与交流', creative: '创作协作', music: '音乐与兴趣', daily: '生活互助',
} as const;
export type Category = keyof typeof categories;
export type TaskInput = {
  title: string; category: Category; description: string; completion_criteria: string;
  location: string; deadline: string; reward?: string;reward_type:'mutual'|'paid';reward_amount_fen?:number|null;
  acceptance_mode: keyof typeof acceptanceNames; application_requirements: ApplicationRequirements;
};
export type Task = Omit<TaskInput, 'location' | 'deadline' | 'reward' | 'reward_type'> & {
  reward_type:'mutual'|'paid'|'legacy';reward_amount_fen:number|null;terms_version:number;collaboration_version:number;paused_from_status:string|null;pause_reason:string|null;cancelled_at:string|null;cancel_reason:string|null;cancellation_settlement_fen:number|null;cancellation_settlement_reason:string|null;is_expired:boolean;is_overdue:boolean;can_apply:boolean;can_claim:boolean;can_accept_application:boolean;server_time:string;next_boundary:string|null;
  id: string; status: string; created_at: string;
  location: string | null; deadline: string | null; reward: string | null;
  publisher_id: string | null; publisher_name: string | null;
  assignee_id: string | null; assignee_name: string | null;
};
export const statusNames: Record<string,string> = {published:'待接取',in_progress:'协作中',paused:'协作暂停',pending_review:'待验收',completed:'已完成',cancelled:'已取消',withdrawn:'已下架'};
export type User = {id:string; username:string; display_name:string; can_publish_activities:boolean;can_publish_volunteers:boolean};
export type Application = {id:string; task_id:string; applicant_id:string; applicant_name:string; reason:string; experience:string; supplement:string; status:string; created_at:string;withdrawn_at:string|null};
export type Submission = {terms_version:number|null;id:string; task_id:string; author_id:string; summary:string; status:string; feedback:string|null; created_at:string; reviewed_at:string|null};
export type Workspace = {applications:Application[]; submissions:Submission[];uses_stages:boolean};
export type StageFields = {title:string;completion_criteria:string;deadline:string;responsible_role:'publisher'|'assignee'};
export type StageSuggestion = {id:string;task_id:string;conversation_id:string;base_version:number;stages:StageFields[];model:string|null;applied_version:number|null};
export type Stage = StageFields & {id:string;position:number;version:number;status:string;responsible_id:string|null;responsible_name:string|null;reviewer_id:string|null;reviewer_name:string|null;
  submissions:(Submission & {stage_id:string;author_name:string;reviewer_id:string|null;reviewer_name:string|null})[]};
export type StagePanel = {task_id:string;plan_version:number;can_edit:boolean;can_propose_plan:boolean;edit_reason:string|null;stages:Stage[];suggestion:StageSuggestion|null;versions:{version:number;created_at:string;stages:StageFields[]}[]};
export type MyTasks = {published:Task[]; assigned:Task[]; applied:Task[];application_history?:Task[]};
export type TaskList = {server_time:string;next_boundary:string|null;items: Task[]; total: number; limit: number; offset: number};
const fieldNames: Record<string, string> = {
  discovered_at:'发现时间',content:'评论文字',image_ids:'配图',status:'当前状态',file:'图片文件',
  jobs:'岗位安排',name:'岗位名称',requirements:'岗位要求',estimated_minutes:'预计服务分钟数',estimated_hours_description:'预计小时说明',recognition_conditions:'小时认定条件',actual_minutes:'实际服务分钟数',confirmed_minutes:'确认分钟数',attendance:'参与情况',
  starts_at:'活动开始时间', ends_at:'活动结束时间', opens_at:'报名开放时间', closes_at:'报名截止时间', capacity:'名额', registration_mode:'报名方式', recognition_tags:'认定标签', recognition_description:'认定说明', organization_name:'组织方', information_source:'信息来源', contact:'联系渠道', participation_requirements:'参与条件', application_note:'申请说明',
  title: '任务标题', category: '任务分类', description: '需求说明',
  reward_type:'回报类型',reward_amount_fen:'报酬金额',
  completion_criteria: '完成标准', location: '地点', deadline: '截止时间', reward: '回报说明',
  acceptance_mode:'接取方式',application_requirements:'申请要求',experience:'技能经验',supplement:'补充说明',confirmed:'条件确认',reason:'申请理由',summary:'成果说明',feedback:'验收意见',username:'账号',password:'密码',stages:'阶段安排',responsible_role:'阶段负责人',expected_version:'安排版本',version:'状态版本',
};

export async function request<T>(url: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(url, options); }
  catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new Error('暂时无法连接服务，请稍后重试。');
  }
  let body: unknown;
  try { body = await response.json(); }
  catch { throw new Error('暂时无法读取数据，请稍后重试。'); }
  if (!response.ok) {
    const detail = (body as {detail?: unknown})?.detail;
    if (typeof detail === 'string') throw new Error(detail);
    if (response.status === 422 && Array.isArray(detail)) {
      const fields = [...new Set(detail.map((item: {loc?: string[]}) =>
        fieldNames[item.loc?.at(-1) ?? ''] ?? '表单内容'))];
      throw new Error(`请检查${fields.join('、')}，内容或格式不符合要求。`);
    }
    throw new Error('服务暂时无法完成请求，请稍后重试。');
  }
  if(options?.method&&!['GET','HEAD','OPTIONS'].includes(options.method.toUpperCase()))window.dispatchEvent(new Event('campus:changed'));
  return body as T;
}

export function formatTime(value: string | null): string {
  if (!value) return '暂未设置';
  return new Intl.DateTimeFormat('zh-CN', {timeZone: 'Asia/Shanghai', year: 'numeric',
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}).format(new Date(value));
}
