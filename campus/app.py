"""本地原型 API，启动后访问 /docs。"""
from .home import HomeService
from .notifications import NotificationService
from .home_api import home_router
from contextlib import asynccontextmanager
import asyncio
import json
from pathlib import Path
from typing import Annotated

from fastapi import Body, Depends, FastAPI, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .db import Database, configured_db_path
from .schemas import MAX_TASK_OFFSET, TASK_CREATE_EXAMPLE, Category, TaskCreate, TaskList, TaskRead
from .service import TaskNotFound, TaskService
from .schemas import DeadlineInput, ExtensionReviewInput, VersionInput, SettlementInput, CollaborationRequestInput
from .auth import AuthService, SESSION_SECONDS
from .accounts import AccountService
from .errors import AppError
from .guide import GuideService
from .stages import StageService
from .activities import ActivityService
from .activity_api import activity_router
from .volunteers import VolunteerService
from .volunteer_api import volunteer_router
from .discoveries import DiscoveryService
from .discovery_api import discovery_router,ImageUploadLimit
from .schemas import StagePlanInput, StagePanelRead, StageActionInput, StageSubmitInput, StageReviewInput
from .todos import personal_state
from .schemas import PersonalState, GuideInput, GuideReply, DraftActionInput, GuideConversationRead
from .schemas import (UserRead, LoginInput, ClaimInput, ApplicationInput, ApplicationRead,
                      SubmissionInput, SubmissionRead, ReviewInput, WorkspaceRead, MyTasks, TaskStatus,
                      RegisterInput)


def create_app(db_path: str | Path | None = None, *, guide_backend_factory=None, activity_clock=None, volunteer_clock=None, discovery_clock=None, task_clock=None) -> FastAPI:
    service = TaskService(Database(db_path if db_path is not None else configured_db_path()),task_clock)
    auth = AuthService(service.database)
    stages = StageService(service)
    activities = ActivityService(service.database, activity_clock)
    volunteers = VolunteerService(service.database, volunteer_clock)
    discoveries = DiscoveryService(service.database, discovery_clock)
    messages=NotificationService(service.database)
    home=HomeService(service,activities,volunteers)
    accounts=AccountService(service.database)
    guide = GuideService(service,guide_backend_factory,activities=activities,
        volunteers=volunteers,discoveries=discoveries,home=home)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.initialize()
        auth.provision_demo_accounts()
        discoveries.cleanup_images()
        guide.runs.recover()
        try:
            yield
        finally:
            await asyncio.to_thread(guide.shutdown)

    application = FastAPI(title="校园任务岛 API", version="0.1.0", lifespan=lifespan,
                          description="发布任务请选择 POST /api/tasks，在 Request body 中提交 JSON。"
                                      "GET /api/tasks 用于查询，只有关键词、分类和分页参数。"
                                      "发布、申请、提交和验收需要先登录；已有本地测试账号。",
                          swagger_ui_parameters={"defaultModelsExpandDepth": -1},
                          openapi_tags=[
                              {"name": "任务发布", "description": "创建新任务：提交 JSON 请求体。"},
                              {"name": "任务查询", "description": "搜索任务或查看详情：填写查询参数或任务 ID。"},
                              {"name": "服务状态", "description": "检查服务是否运行。"},
                          ])
    application.state.task_service = service
    application.state.auth_service = auth
    application.state.guide_service = guide
    application.state.stage_service = stages
    application.state.activity_service = activities
    application.state.volunteer_service = volunteers
    application.state.discovery_service = discoveries
    application.state.notification_service=messages
    application.state.home_service=home
    application.state.account_service=accounts
    application.add_middleware(ImageUploadLimit)

    @application.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code,content={'detail':str(exc)})

    @application.middleware('http')
    async def check_origin(request: Request, call_next):
        origin = request.headers.get('origin')
        allowed = {str(request.base_url).rstrip('/'),'http://127.0.0.1:5173','http://localhost:5173'}
        if request.method not in {'GET','HEAD','OPTIONS'} and origin and origin not in allowed:
            return JSONResponse(status_code=403,content={'detail':'请求来源不允许'})
        return await call_next(request)

    def current_user(request: Request) -> UserRead:
        return auth.current_user(request.cookies.get('campus_session'))

    application.include_router(activity_router(activities, auth, current_user))
    application.include_router(volunteer_router(volunteers, auth, current_user))
    application.include_router(discovery_router(discoveries, auth, current_user))
    application.include_router(home_router(home,messages,current_user))

    @application.post('/api/auth/login', response_model=UserRead, tags=['用户'],summary='登录测试账号')
    def login(body: LoginInput, request: Request, response: Response):
        token,user = auth.login(body.username,body.password)
        auth.logout(request.cookies.get('campus_session'))
        response.set_cookie('campus_session',token,max_age=SESSION_SECONDS,httponly=True,samesite='strict',secure=request.url.scheme=='https')
        return user

    @application.post('/api/auth/register',response_model=UserRead,status_code=201,tags=['用户'],summary='注册普通账号并登录')
    def register(body: RegisterInput,request: Request,response: Response):
        token,user=auth.register(body.username,body.display_name,body.password)
        auth.logout(request.cookies.get('campus_session'))
        response.set_cookie('campus_session',token,max_age=SESSION_SECONDS,httponly=True,samesite='strict',secure=request.url.scheme=='https')
        return user

    @application.get('/api/auth/me',response_model=UserRead,tags=['用户'],summary='当前登录用户')
    def me(user: UserRead = Depends(current_user)):
        return user

    @application.get('/api/me/account',tags=['用户'],summary='读取本人账号资料')
    def my_account(user: UserRead = Depends(current_user)):
        return accounts.read(user.id)

    @application.post('/api/auth/logout',tags=['用户'],summary='退出登录')
    def logout(request: Request,response: Response):
        auth.logout(request.cookies.get('campus_session'))
        response.delete_cookie('campus_session')
        return {'ok':True}

    @application.get("/api/health", tags=["服务状态"], summary="检查服务状态")
    def health():
        return {"status": "ok"}

    @application.post("/api/tasks", response_model=TaskRead, status_code=201, tags=["任务发布"],
                      summary="发布任务（提交 JSON）",
                      description="点击 Try it out，编辑 Request body，再点击 Execute。"
                                  "地点 location 和截止时间 deadline 必填，deadline 必须带时区且晚于服务端当前时间。reward_type 必须明确为 mutual 或 paid，有偿任务需整数分金额和回报说明。"
                                  "成功返回 201 和任务 ID。")
    def create_task(body: Annotated[TaskCreate, Body(openapi_examples={
        "photography": {"summary": "摄影任务（可直接提交）", "value": TASK_CREATE_EXAMPLE},
    })], user: UserRead = Depends(current_user)):
        return service.create_task(body,user.id)

    @application.get("/api/tasks", response_model=TaskList, tags=["任务查询"],
                     summary="查询任务列表（填写筛选条件）",
                     description="此接口用于查询已有任务，不接收发布 JSON。keyword 可填写摄影或留空；"
                                 "大厅默认隐藏已完成、已下架及已截止未接取任务；expired_only=true 查看已截止未接取任务；category 可按需选择，limit 和 offset 用于分页。")
    def list_tasks(keyword: str = Query(default="", max_length=200, description="搜索关键词，例如摄影；留空查询未完成任务"),
                   category: Category | None = Query(default=None, description="分类筛选，可不选；creative 表示创作协作"),
                   limit: int = Query(default=20, ge=1, le=50, description="每页最多返回多少条，默认 20"),
                   offset: int = Query(default=0, ge=0, le=MAX_TASK_OFFSET, description="跳过多少条，第一页填 0"),
                   status: TaskStatus | None = None, expired_only: bool = False):
        return service.search_tasks(keyword, category, limit, offset,status,exclude_completed=status is None,expired_only=expired_only)

    @application.get("/api/tasks/{task_id}", response_model=TaskRead, tags=["任务查询"], summary="查看任务详情")
    def get_task(task_id: str):
        return service.get_task(task_id)

    @application.get('/api/tasks/{task_id}/copy-source',response_model=TaskRead,tags=['协作'],summary='读取本人已取消任务的可复制约定')
    def copy_source(task_id: str,user: UserRead=Depends(current_user)):
        return service.copy_source(task_id,user.id)


    from .schemas import ChangeInput

    @application.get('/api/tasks/{task_id}/changes',tags=['任务约定'])
    def changes(task_id: str,user: UserRead=Depends(current_user)):
        return service.terms.changes.read(task_id,user.id)

    @application.post('/api/tasks/{task_id}/changes',tags=['任务约定'])
    def propose_change(task_id: str,body: ChangeInput,user: UserRead=Depends(current_user)):
        return service.terms.changes.propose(task_id,user.id,body)

    @application.post('/api/tasks/{task_id}/collaboration-requests',tags=['协作'],summary='提出暂停、恢复或协商取消申请')
    def collaboration_request(task_id: str,body: CollaborationRequestInput,user: UserRead=Depends(current_user)):
        return service.terms.changes.propose_control(task_id,user.id,body)

    @application.post('/api/task-changes/{identifier}/review',tags=['任务约定'])
    def review_change(identifier: str,body: ExtensionReviewInput,user: UserRead=Depends(current_user)):
        return service.terms.changes.decide(identifier,user.id,body)

    @application.post('/api/task-changes/{identifier}/cancel',tags=['任务约定'])
    def cancel_change(identifier: str,body: VersionInput,user: UserRead=Depends(current_user)):
        return service.terms.changes.decide(identifier,user.id,cancel=True,version=body.version)

    @application.get('/api/tasks/{task_id}/agreements/{version}',tags=['任务约定'])
    def agreement(task_id: str,version: int,user: UserRead=Depends(current_user)):
        return service.terms.changes.history(task_id,user.id,version)

    @application.post('/api/tasks/{task_id}/deadline',response_model=TaskRead,tags=['任务约定'])
    def extend_deadline(task_id: str,body: DeadlineInput,user: UserRead=Depends(current_user)):
        return service.terms.extend_unassigned(task_id,user.id,body)

    @application.get('/api/tasks/{task_id}/extensions',tags=['任务约定'])
    def extensions(task_id: str,user: UserRead=Depends(current_user)):
        return service.terms.extensions(task_id,user.id)

    @application.post('/api/tasks/{task_id}/extensions',tags=['任务约定'])
    def propose_extension(task_id: str,body: DeadlineInput,user: UserRead=Depends(current_user)):
        return service.terms.propose(task_id,user.id,body)

    @application.post('/api/task-extensions/{identifier}/review',tags=['任务约定'])
    def review_extension(identifier: str,body: ExtensionReviewInput,user: UserRead=Depends(current_user)):
        return service.terms.decide(identifier,user.id,body)

    @application.post('/api/task-extensions/{identifier}/cancel',tags=['任务约定'])
    def cancel_extension(identifier: str,body: VersionInput,user: UserRead=Depends(current_user)):
        return service.terms.decide(identifier,user.id,cancel=True,version=body.version)

    @application.get('/api/tasks/{task_id}/settlement',tags=['任务约定'])
    def settlement(task_id: str,user: UserRead=Depends(current_user)):
        return service.terms.settlement(task_id,user.id)

    @application.post('/api/tasks/{task_id}/settlement/confirmation',tags=['任务约定'])
    def confirm_settlement(task_id: str,body: SettlementInput,user: UserRead=Depends(current_user)):
        return service.terms.confirm(task_id,user.id,body)

    @application.get('/api/me/tasks',response_model=MyTasks,tags=['协作'],summary='我的发布、接取和申请')
    def my_tasks(user: UserRead = Depends(current_user)):
        return service.my_tasks(user.id)

    @application.get('/api/guide/todos',response_model=PersonalState,tags=['引航员'],summary='当前用户的待办和等待事项')
    def guide_todos(user: UserRead = Depends(current_user)):
        return personal_state(service,user.id)

    @application.post('/api/guide/chat',response_model=GuideReply,tags=['引航员'],summary='与引航员对话，查询任务或整理发布草稿')
    def guide_chat(body: GuideInput,user: UserRead = Depends(current_user)):
        return guide.chat(body,user)

    @application.post('/api/guide/runs',status_code=202,tags=['引航员'],summary='启动可流式观察和取消的运行')
    def start_run(body: GuideInput,user: UserRead = Depends(current_user)):
        return guide.start(body,user)

    @application.get('/api/guide/runs',tags=['引航员'],summary='本人最近20次运行摘要')
    def recent_runs(user: UserRead = Depends(current_user)):
        return {'items':guide.runs.recent(user.id)}

    @application.get('/api/guide/runs/{run_id}',tags=['引航员'],summary='本人运行详情与事件')
    def get_run(run_id: str,user: UserRead = Depends(current_user)):
        return guide.runs.read(run_id,user.id)

    @application.post('/api/guide/runs/{run_id}/cancel',tags=['引航员'],summary='取消未提交的运行；返回 cancelling 后等待终态')
    def cancel_run(run_id: str,user: UserRead = Depends(current_user)):
        return guide.cancel_run(run_id,user)

    @application.get('/api/guide/runs/{run_id}/events',tags=['引航员'],summary='SSE 实时事件；支持 Last-Event-ID 重连')
    async def run_events(run_id: str,request: Request,user: UserRead = Depends(current_user)):
        await asyncio.to_thread(guide.runs.read,run_id,user.id)
        try:
            cursor = max(0,int(request.headers.get('last-event-id','0')))
        except ValueError:
            raise AppError('Last-Event-ID 必须是非负整数',400)
        async def events():
            nonlocal cursor
            while not await request.is_disconnected():
                item = await asyncio.to_thread(guide.runs.read,run_id,user.id)
                for event in item['events']:
                    if event['seq']>cursor:
                        cursor=event['seq']
                        yield f"id: {cursor}\nevent: progress\ndata: {json.dumps(event,ensure_ascii=False)}\n\n"
                if item['status'] in {'succeeded','failed','cancelled','interrupted'}:
                    item.pop('events')
                    yield f"event: terminal\ndata: {json.dumps(item,ensure_ascii=False)}\n\n"
                    return
                yield ': heartbeat\n\n'
                await asyncio.sleep(0.15)
        return StreamingResponse(events(),media_type='text/event-stream',
                                 headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

    @application.get('/api/guide/conversations/{conversation_id}',response_model=GuideConversationRead,tags=['引航员'],summary='恢复本人的对话与任务草稿')
    def guide_conversation(conversation_id: str,user: UserRead = Depends(current_user)):
        return guide.conversation(conversation_id,user)

    @application.post('/api/guide/drafts/{conversation_id}/publish',response_model=GuideReply,tags=['引航员'],summary='确认发布当前版本草稿')
    def publish_draft(conversation_id: str,body: DraftActionInput,user: UserRead = Depends(current_user)):
        return guide.confirm(conversation_id,body.version,user)

    @application.post('/api/guide/drafts/{conversation_id}/cancel',response_model=GuideReply,tags=['引航员'],summary='取消尚未发布的草稿')
    def cancel_draft(conversation_id: str,body: DraftActionInput,user: UserRead = Depends(current_user)):
        return guide.confirm(conversation_id,body.version,user,cancel=True)

    @application.get('/api/tasks/{task_id}/workspace',response_model=WorkspaceRead,tags=['协作'],summary='查看本人可见的申请和成果')
    def workspace(task_id: str,user: UserRead = Depends(current_user)):
        return service.workspace(task_id,user.id)

    @application.get('/api/tasks/{task_id}/stages',response_model=StagePanelRead,tags=['阶段协作'],summary='读取共享阶段安排与本人可见的成果')
    def stage_panel(task_id: str,user: UserRead = Depends(current_user)):
        return stages.read(task_id,user.id)

    @application.post('/api/tasks/{task_id}/stages',response_model=StagePanelRead,tags=['阶段协作'],summary='发布者确认或替换尚未执行的阶段安排')
    def stage_plan(task_id: str,body: StagePlanInput,user: UserRead = Depends(current_user)):
        return stages.set_plan(task_id,user.id,body)

    @application.post('/api/tasks/{task_id}/stages/{stage_id}/start',response_model=StagePanelRead,tags=['阶段协作'],summary='负责人开始或继续当前阶段')
    def stage_start(task_id: str,stage_id: str,body: StageActionInput,user: UserRead = Depends(current_user)):
        return stages.start(task_id,stage_id,user.id,body.version)

    @application.post('/api/tasks/{task_id}/stages/{stage_id}/submissions',response_model=StagePanelRead,tags=['阶段协作'],summary='负责人提交当前阶段成果说明')
    def stage_submit(task_id: str,stage_id: str,body: StageSubmitInput,user: UserRead = Depends(current_user)):
        return stages.submit(task_id,stage_id,user.id,body)

    @application.post('/api/tasks/{task_id}/stages/{stage_id}/review',response_model=StagePanelRead,tags=['阶段协作'],summary='对方确认阶段或退回补充')
    def stage_review(task_id: str,stage_id: str,body: StageReviewInput,user: UserRead = Depends(current_user)):
        return stages.review(task_id,stage_id,user.id,body)

    @application.post('/api/tasks/{task_id}/withdraw',response_model=TaskRead,tags=['协作'],summary='发布者下架尚未接取的任务')
    def withdraw_task(task_id: str,user: UserRead = Depends(current_user)):
        return service.withdraw(task_id,user.id)

    @application.post('/api/tasks/{task_id}/applications',response_model=ApplicationRead,status_code=201,tags=['协作'],summary='申请接取')
    def apply(task_id: str,body: ApplicationInput,user: UserRead = Depends(current_user)):
        return service.apply(task_id,user.id,**body.model_dump())

    @application.post('/api/applications/{application_id}/withdraw',response_model=ApplicationRead,status_code=200,tags=['协作'],summary='申请者撤回待处理申请')
    def withdraw_application(application_id: str,user: UserRead=Depends(current_user)):
        return service.withdraw_application(application_id,user.id)

    @application.post('/api/tasks/{task_id}/claim',response_model=TaskRead,tags=['协作'],summary='确认条件并直接接取')
    def claim_task(task_id: str, body: ClaimInput, user: UserRead = Depends(current_user)):
        return service.claim(task_id,user.id,**body.model_dump())

    @application.post('/api/applications/{application_id}/accept',response_model=TaskRead,tags=['协作'],summary='发布者接受申请')
    def accept(application_id: str,user: UserRead = Depends(current_user)):
        return service.accept_application(application_id,user.id)

    @application.post('/api/tasks/{task_id}/submissions',response_model=SubmissionRead,status_code=201,tags=['协作'],summary='接取者提交成果')
    def submit(task_id: str,body: SubmissionInput,user: UserRead = Depends(current_user)):
        return service.submit(task_id,user.id,body.summary,body.collaboration_version)

    @application.post('/api/tasks/{task_id}/review',response_model=TaskRead,tags=['协作'],summary='发布者验收或退回补充')
    def review(task_id: str,body: ReviewInput,user: UserRead = Depends(current_user)):
        return service.review(task_id,user.id,body.decision,body.feedback,body.collaboration_version)

    web_dist = Path(__file__).resolve().parents[1] / "web" / "dist"
    if web_dist.is_dir():
        application.mount("/assets", StaticFiles(directory=web_dist / "assets", check_dir=False), name="assets")

        @application.get("/", include_in_schema=False)
        def frontend():
            return FileResponse(web_dist / "index.html")

    return application


app = create_app()
