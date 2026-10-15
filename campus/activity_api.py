"""活动 API：公共活动信息与登录用户的私有报名资料分离。"""
from fastapi import APIRouter, Depends, Query, Request
from .activity_schemas import ActivityCreate, ActivityCancel, RecognitionTag, RegistrationInput, RegistrationReview
from .schemas import UserRead
from .errors import AppError


def activity_router(service, auth, current_user):
    router = APIRouter(tags=['综素活动'])

    @router.get('/api/activities')
    def search(keyword: str = Query('', max_length=200), tag: RecognitionTag | None = None,
               limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=2000000)):
        return service.search(keyword.strip(), tag, limit, offset)

    @router.post('/api/activities', status_code=201)
    def create(body: ActivityCreate, user: UserRead = Depends(current_user)):
        return service.create(body, user.id)

    @router.get('/api/activities/{activity_id}')
    def detail(activity_id: str, request: Request):
        token = request.cookies.get('campus_session')
        user = None
        if token:
            try:
                user = auth.current_user(token)
            except AppError as exc:
                if exc.status_code != 401:
                    raise
        return service.detail(activity_id, user.id if user else None)

    @router.post('/api/activities/{activity_id}/registrations', status_code=201)
    def register(activity_id: str, body: RegistrationInput, user: UserRead = Depends(current_user)):
        return service.register(activity_id, user.id, body.application_note)

    @router.post('/api/registrations/{registration_id}/review')
    def review(registration_id: str, body: RegistrationReview, user: UserRead = Depends(current_user)):
        return service.review(registration_id, user.id, body)

    @router.post('/api/registrations/{registration_id}/cancel')
    def cancel_registration(registration_id: str, user: UserRead = Depends(current_user)):
        return service.cancel_registration(registration_id, user.id)

    @router.post('/api/activities/{activity_id}/cancel')
    def cancel_activity(activity_id: str, body: ActivityCancel, user: UserRead = Depends(current_user)):
        return service.cancel_activity(activity_id, user.id, body.reason)

    @router.get('/api/activities/{activity_id}/registrations')
    def roster(activity_id: str, user: UserRead = Depends(current_user)):
        return service.roster(activity_id, user.id)

    @router.get('/api/me/registrations')
    def my_registrations(user: UserRead = Depends(current_user)):
        return service.my_registrations(user.id)

    @router.get('/api/me/activities')
    def my_activities(user: UserRead = Depends(current_user)):
        return service.my_activities(user.id)

    return router
