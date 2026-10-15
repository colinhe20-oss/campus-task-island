from fastapi import APIRouter,Depends,Query
from pydantic import BaseModel,ConfigDict,Field
from .schemas import UserRead

class ReadAllInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    through_id:int=Field(ge=0,strict=True)

def home_router(home,messages,current_user):
    router=APIRouter(tags=['首页与消息'])
    @router.get('/api/me/home')
    def summary(user:UserRead=Depends(current_user)):return home.summary(user.id)
    @router.get('/api/me/messages')
    def listing(unread_only:bool=False,limit:int=Query(20,ge=1,le=50),before_id:int|None=Query(None,ge=1),user:UserRead=Depends(current_user)):
        return messages.list(user.id,unread_only,limit,before_id)
    @router.get('/api/me/messages/unread-count')
    def count(user:UserRead=Depends(current_user)):return messages.count(user.id)
    @router.post('/api/me/messages/read-all')
    def read_all(body:ReadAllInput,user:UserRead=Depends(current_user)):return messages.read(user.id,through_id=body.through_id)
    @router.post('/api/me/messages/{identifier}/read')
    def read(identifier:int,user:UserRead=Depends(current_user)):return messages.read(user.id,identifier=identifier)
    return router
