from fastapi import APIRouter, Depends, Query, Request
from .activity_schemas import ActivityCancel, RegistrationInput, RegistrationReview
from .volunteer_schemas import VolunteerCreate, ParticipationInput, HoursInput
from .schemas import UserRead
from .errors import AppError


def volunteer_router(service,auth,current_user):
    router=APIRouter(tags=['志愿服务'])

    @router.get('/api/volunteers')
    def search(keyword:str=Query('',max_length=200),limit:int=Query(20,ge=1,le=50),offset:int=Query(0,ge=0,le=2000000)):
        return service.search(keyword.strip(),limit,offset)

    @router.post('/api/volunteers',status_code=201)
    def create(body:VolunteerCreate,user:UserRead=Depends(current_user)):
        return service.create(body,user.id)

    @router.get('/api/volunteers/{activity_id}')
    def detail(activity_id:str,request:Request):
        user=None
        if token:=request.cookies.get('campus_session'):
            try:
                user=auth.current_user(token)
            except AppError as exc:
                if exc.status_code!=401:raise
        return service.detail(activity_id,user.id if user else None)

    @router.post('/api/volunteer-jobs/{job_id}/registrations',status_code=201)
    def register(job_id:str,body:RegistrationInput,user:UserRead=Depends(current_user)):
        return service.register(job_id,user.id,body.application_note)

    @router.post('/api/volunteer-registrations/{registration_id}/review')
    def review(registration_id:str,body:RegistrationReview,user:UserRead=Depends(current_user)):
        return service.review(registration_id,user.id,body)

    @router.post('/api/volunteer-registrations/{registration_id}/cancel')
    def cancel_registration(registration_id:str,user:UserRead=Depends(current_user)):
        return service.cancel_registration(registration_id,user.id)

    @router.post('/api/volunteers/{activity_id}/cancel')
    def cancel_activity(activity_id:str,body:ActivityCancel,user:UserRead=Depends(current_user)):
        return service.cancel_activity(activity_id,user.id,body.reason)

    @router.get('/api/volunteers/{activity_id}/registrations')
    def roster(activity_id:str,user:UserRead=Depends(current_user)):
        return service.roster(activity_id,user.id)

    @router.post('/api/volunteer-registrations/{registration_id}/participation')
    def participation(registration_id:str,body:ParticipationInput,user:UserRead=Depends(current_user)):
        return service.update_record(registration_id,user.id,body)

    @router.post('/api/volunteer-registrations/{registration_id}/hours')
    def hours(registration_id:str,body:HoursInput,user:UserRead=Depends(current_user)):
        return service.update_record(registration_id,user.id,body)

    @router.get('/api/me/volunteer-registrations')
    def registrations(user:UserRead=Depends(current_user)):
        return service.mine(user.id,'registrations')

    @router.get('/api/me/volunteer-records')
    def records(user:UserRead=Depends(current_user)):
        return service.mine(user.id,'records')

    @router.get('/api/me/volunteers')
    def activities(user:UserRead=Depends(current_user)):
        return service.mine(user.id,'activities')

    return router
