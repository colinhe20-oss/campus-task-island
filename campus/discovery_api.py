from fastapi import APIRouter,Depends,File,HTTPException,Query,Request,UploadFile
from fastapi.responses import FileResponse,JSONResponse
from .discovery_schemas import DiscoveryCategory,DiscoveryStatus,DiscoveryCreate,DiscoveryEdit,DiscoveryStateInput,DiscoveryWithdraw,DiscoveryCommentInput
from .discoveries import MAX_IMAGE_BYTES
from .schemas import UserRead
from .errors import AppError


class ImageUploadLimit:
    """在 multipart 解码前限制上传请求总量，包括没有 Content-Length 的请求。"""
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['path']!='/api/discovery-images' or scope['method']!='POST':
            return await self.app(scope,receive,send)
        limit=MAX_IMAGE_BYTES+65536
        headers=dict(scope.get('headers',[]))
        try:length=int(headers.get(b'content-length',b'0'))
        except ValueError:length=0
        if length>limit:
            return await JSONResponse({'detail':'图片上传请求过大，单张不能超过5 MiB'},status_code=413)(scope,receive,send)
        received=0
        async def bounded_receive():
            nonlocal received
            message=await receive()
            if message['type']=='http.request':
                received+=len(message.get('body',b''))
                if received>limit:raise HTTPException(413,'图片上传请求过大，单张不能超过5 MiB')
            return message
        await self.app(scope,bounded_receive,send)


def discovery_router(service,auth,current_user):
    router=APIRouter(tags=['校园发现'])
    def optional_user(request):
        token=request.cookies.get('campus_session')
        if token:
            try:return auth.current_user(token)
            except AppError as exc:
                if exc.status_code!=401:raise
        return None

    @router.get('/api/discoveries')
    def search(keyword:str=Query('',max_length=200),category:DiscoveryCategory|None=None,status:DiscoveryStatus|None=None,
               limit:int=Query(20,ge=1,le=50),offset:int=Query(0,ge=0,le=2000000)):
        return service.search(keyword.strip(),category,status,limit,offset)

    @router.post('/api/discoveries',status_code=201)
    def create(body:DiscoveryCreate,user:UserRead=Depends(current_user)):
        return service.create(body,user.id)

    @router.get('/api/discoveries/{identifier}')
    def detail(identifier:str,request:Request):
        user=optional_user(request)
        return service.detail(identifier,user.id if user else None)

    @router.patch('/api/discoveries/{identifier}')
    def edit(identifier:str,body:DiscoveryEdit,user:UserRead=Depends(current_user)):
        return service.edit(identifier,user.id,body)

    @router.post('/api/discoveries/{identifier}/status')
    def state(identifier:str,body:DiscoveryStateInput,user:UserRead=Depends(current_user)):
        return service.state(identifier,user.id,body)

    @router.post('/api/discoveries/{identifier}/withdraw')
    def withdraw(identifier:str,body:DiscoveryWithdraw,user:UserRead=Depends(current_user)):
        return service.state(identifier,user.id,body,withdraw=True)

    @router.get('/api/discoveries/{identifier}/comments')
    def comments(identifier:str,request:Request,limit:int=Query(20,ge=1,le=50),offset:int=Query(0,ge=0,le=2000000)):
        user=optional_user(request)
        return service.comments(identifier,user.id if user else None,limit,offset)

    @router.post('/api/discoveries/{identifier}/comments',status_code=201)
    def comment(identifier:str,body:DiscoveryCommentInput,user:UserRead=Depends(current_user)):
        return service.comment(identifier,user.id,body)

    @router.post('/api/discovery-comments/{identifier}/withdraw')
    def withdraw_comment(identifier:str,user:UserRead=Depends(current_user)):
        return service.withdraw_comment(identifier,user.id)

    @router.post('/api/discovery-images',status_code=201)
    def upload(file:UploadFile=File(...),user:UserRead=Depends(current_user)):
        try:return service.upload(file.file.read(MAX_IMAGE_BYTES+1),user.id)
        finally:file.file.close()

    @router.get('/api/discovery-images/{identifier}')
    def image(identifier:str,request:Request):
        user=optional_user(request)
        return FileResponse(service.image_path(identifier,user.id if user else None),media_type='image/jpeg',
                            headers={'Cache-Control':'no-store','Vary':'Cookie','X-Content-Type-Options':'nosniff'})

    @router.get('/api/me/discoveries')
    def mine(limit:int=Query(20,ge=1,le=50),offset:int=Query(0,ge=0,le=2000000),user:UserRead=Depends(current_user)):
        return service.search(limit=limit,offset=offset,user_id=user.id,mine=True)

    @router.get('/api/discoveries/{identifier}/versions')
    def versions(identifier:str,user:UserRead=Depends(current_user)):
        return service.versions(identifier,user.id)

    return router
