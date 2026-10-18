import copy
import json
import unittest
import threading
import time
from datetime import timedelta
from unittest.mock import patch

import test_assistance as base
from backend.fake_backend import FakeBackend
from campus.assistance import AssistanceBuffer,Preferences,inspect_plan
from campus import planning
from campus.semantics import SemanticService,validated,profile_source,job_source,semantic_match,lexical_conflict


def facts(*values):
    return {'facts':[dict(tag=t,evidence=e,polarity=p,necessity=n) for t,e,p,n in values],'unknown':[]}


class PlanningSemanticTests(unittest.TestCase):
    setUp=base.AssistanceTests.setUp
    setUpBase=base.AssistanceTests.setUpBase
    login=base.AssistanceTests.login
    payload=base.AssistanceTests.payload
    chat=base.AssistanceTests.chat
    plan=base.AssistanceTests.plan

    def review(self,r,patch=None):
        buffer=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner)
        buffer.review({'proposals':[{'title':'完善活动说明','reason':'明确用户已给定的公益活动目标','evidence':[{'path':'fields.title','value':buffer.data['plan']['fields']['title']}],
           'fields':patch or {'description':'经用户核对的公益服务安排'}}],'questions':['集合点尚需确认'],'rechecks':['修改时段后请核对设备安排']})
        with self.service.database.connect() as c:buffer.save(c)
        return self.guide.assistance.read(r['conversation_id'],self.owner)

    def decision(self,a,decision='accept',fields=None):
        p=a['plan']['review']['proposals'][0]
        return self.client.post(f"/api/guide/assistance/{a['conversation_id']}/proposals/{p['id']}",json={'version':a['version'],'decision':decision,**({'fields':fields} if fields else {})})

    def test_headcount_is_only_blocking_when_explicit(self):
        r=self.plan();b=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner)
        self.assertTrue(b.read()['plan']['ready'])
        result=b.plan('volunteer',target_volunteers=20)
        self.assertFalse(result['plan']['ready'])
        self.assertIn('headcount_mismatch',[c['code'] for c in result['plan']['checks']])
        self.assertTrue(b.plan('volunteer',clear_target=True)['plan']['ready'])

    def test_time_change_reports_impacts_without_moving_jobs(self):
        r=self.plan();b=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner)
        original=copy.deepcopy(b.data['plan']['fields']['jobs'])
        result=b.plan('volunteer',{'ends_at':(self.now+timedelta(hours=3)).isoformat()})['plan']
        self.assertEqual(result['fields']['jobs'],original)
        self.assertIn('job_outside_activity',[x['code'] for x in result['impacts']])
        self.assertTrue(any(x['path']=='fields.ends_at' for x in result['changes']))

    def test_stable_job_ids_survive_rename_and_reorder(self):
        r=self.plan();b=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner)
        old=b.read()['plan'];jobs=copy.deepcopy(old['fields']['jobs']);jobs[0]['name']='全新岗位名称'
        result=b.plan('volunteer',{'jobs':jobs[::-1]},job_ids=old['job_ids'][::-1])['plan']
        self.assertEqual(result['job_ids'],old['job_ids'][::-1])
        self.assertTrue(any(x['path']=='jobs.'+old['job_ids'][0]+'.name' for x in result['changes']))
        self.assertTrue(any(x['path']=='job_order' for x in result['changes']))

    def test_review_does_not_change_fields_and_accept_can_edit(self):
        r=self.plan();a=self.review(r)
        self.assertEqual(a['plan']['fields'],r['assistance']['plan']['fields'])
        accepted=self.decision(a,fields={'description':'用户编辑后采纳的说明'})
        self.assertEqual(accepted.status_code,200,accepted.text)
        self.assertEqual(accepted.json()['plan']['fields']['description'],'用户编辑后采纳的说明')
        self.assertIsNone(accepted.json()['plan']['review'])
        self.assertTrue(accepted.json()['plan']['changes'])
        self.assertEqual(self.decision(a).status_code,409)

    def test_reject_keeps_fields_and_old_suggestions_expire(self):
        r=self.plan();a=self.review(r)
        rejected=self.decision(a,'reject');self.assertEqual(rejected.status_code,200,rejected.text)
        self.assertEqual(rejected.json()['plan']['fields'],a['plan']['fields'])
        self.assertEqual(rejected.json()['plan']['review']['proposals'][0]['status'],'rejected')
        a=self.review(r)
        b=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner);b.plan('volunteer',{'title':'用户更改了目标'})
        with self.service.database.connect() as c:b.save(c)
        self.assertEqual(self.decision(a).status_code,409)

    def test_review_rejects_invented_evidence_and_cross_user(self):
        r=self.plan();b=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner)
        with self.assertRaises(ValueError):b.review({'proposals':[{'title':'建议','reason':'原因','evidence':[{'path':'fields.title','value':'不存在的事实'}],'fields':{}}]})
        a=self.review(r);self.login('helper');self.assertEqual(self.decision(a).status_code,404)

    def test_review_path_only_uses_server_value_and_explicit_null_is_checked(self):
        r=self.plan();b=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner)
        proposal=dict(title='明确执行目标',reason='依据当前活动说明',evidence=[{'path':'fields.title'}],fields={'description':'建议补充执行分工'})
        result=b.review({'proposals':[proposal]})
        self.assertEqual(result['plan']['review']['proposals'][0]['evidence'][0]['value'],b.data['plan']['fields']['title'])
        self.assertEqual(result['plan']['fields'],r['assistance']['plan']['fields'])
        proposal['evidence'][0]['value']=None
        with self.assertRaises(planning.PlanReviewError):b.review({'proposals':[proposal]})
        with self.assertRaises(ValueError):planning.evidence_value(b.data['plan'],'fields.jobs.-1.name')

    def test_real_model_encoded_arguments_replay_without_retry_or_field_mutation(self):
        from pathlib import Path
        from tools.assistance import register_assistance_tools
        from tools.base import ToolRegistry
        from examples.improvement_cases import draft
        r=self.plan();b=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner)
        fields={k:v for k,v in draft().items() if k in ('title','description')}
        b.data['plan']['fields']=fields
        registry=ToolRegistry();register_assistance_tools(registry,b,self.guide.matching)
        broken=json.loads((Path(__file__).parent/'fixtures/review_encoded_arguments.json').read_text(encoding='utf-8'))
        with self.assertRaises(planning.PlanReviewError) as error:registry.get('review_activity_plan').invoke(broken)
        self.assertEqual(error.exception.public_diagnostic['code'],'plan_json_invalid')
        args=json.loads((Path(__file__).parent/'fixtures/review_encoded_valid_arguments.json').read_text(encoding='utf-8'))
        before=copy.deepcopy(args)
        result=json.loads(registry.get('review_activity_plan').invoke(args))
        self.assertEqual(args,before)
        self.assertEqual(result['plan']['fields'],fields)
        self.assertEqual(len(result['plan']['review']['proposals']),3)
        self.assertEqual(result['plan']['review']['proposals'][0]['evidence'][0]['value'],fields['description'])

    def test_review_schema_refreshes_after_draft_edit(self):
        from tools.base import ToolRegistry
        from tools.assistance import register_assistance_tools
        from jsonschema import Draft202012Validator,ValidationError
        r=self.plan();b=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner)
        registry=ToolRegistry();register_assistance_tools(registry,b,self.guide.matching)
        tool=registry.get('review_activity_plan')
        self.assertIn('fields.contact',tool.parameters['$defs']['Evidence']['properties']['path']['enum'])
        registry.get('update_volunteer_plan').invoke({'fields':{'contact':None}})
        registry.get('get_assistance').invoke({})
        self.assertNotIn('fields.contact',tool.parameters['$defs']['Evidence']['properties']['path']['enum'])
        Draft202012Validator.check_schema(tool.parameters)
        proposal=dict(title='人数建议',reason='依据活动目标',evidence=[{'path':'fields.title'}],fields={'target_volunteers':20})
        with self.assertRaises(ValidationError):tool.invoke({'proposals':[proposal]})

    def test_review_error_trace_explains_without_logging_argument_values(self):
        r=self.plan();before=self.guide.assistance.read(r['conversation_id'],self.owner)
        wrong=dict(title='完善说明',reason='依据活动目标',evidence=[{'path':'fields.title','value':'private-fault-value-123'}],fields={'description':'建议分工'})
        right=copy.deepcopy(wrong);right['evidence']=[{'path':'fields.title'}]
        self.guide.backend_factory=lambda:FakeBackend([
            {'tool_calls':[{'name':'review_activity_plan','arguments':{'proposals':[wrong]}}]},
            {'tool_calls':[{'name':'review_activity_plan','arguments':{'proposals':[right]}}]},
            {'content':'评估已记录，**请核对建议**。'}])
        response=self.client.post('/api/guide/chat',json={'message':'评估方案','purpose':'activity_review','conversation_id':r['conversation_id'],'expected_assistance_version':before['version']})
        self.assertEqual(response.status_code,200,response.text)
        run=self.guide.runs.read(response.json()['run_id'],self.owner)
        failed=next(e for e in run['events'] if e['kind']=='tool_finished' and not e['success'])
        self.assertEqual(failed['diagnostic']['code'],'plan_evidence_mismatch')
        self.assertIn('依据与当前草稿不一致',failed['summary'])
        self.assertNotIn('private-fault-value-123',json.dumps(run,ensure_ascii=False))
        self.assertEqual(response.json()['assistance']['plan']['fields'],before['plan']['fields'])

    def test_model_review_cancel_and_failure_do_not_commit(self):
        r=self.plan();before=self.guide.assistance.read(r['conversation_id'],self.owner)
        class Broken(FakeBackend):
            def chat(inner,*args,**kwargs):
                if inner.requests:raise TimeoutError()
                return super().chat(*args,**kwargs)
        self.guide.backend_factory=lambda:Broken([{'tool_calls':[{'name':'review_activity_plan','arguments':{'questions':['集合点在哪里？'],'proposals':[],'rechecks':[]}}]}])
        result=self.client.post('/api/guide/chat',json={'message':'请评估','conversation_id':r['conversation_id'],'purpose':'activity_review','expected_assistance_version':before['version']})
        self.assertEqual(result.status_code,504,result.text)
        self.assertEqual(self.guide.assistance.read(r['conversation_id'],self.owner)['version'],before['version'])

    def semantic_service(self,result):
        self.calls=[]
        outer=self
        class Model:
            model='test-semantic-model'
            def chat(self,*args,**kwargs):
                outer.calls.append(args)
                return {'tool_calls':[{'name':'submit_semantic_tags','arguments':result}],'usage':{'total_tokens':12}}
            def close(self):pass
        return SemanticService(self.service,Model,lambda:'test-config',self.guide.runs)

    def test_semantic_cache_one_call_per_changed_source_and_model(self):
        sem=self.semantic_service(facts(('video_shooting','拍过宣传片','positive','unspecified')))
        payload={'skills':['拍过宣传片'],'interests':[]}
        sem.ensure('profile',self.owner,self.owner,payload);sem.ensure('profile',self.owner,self.owner,payload)
        self.assertTrue(sem.process_one());self.assertFalse(sem.process_one());self.assertEqual(len(self.calls),1)
        self.assertEqual(sem.read('profile',self.owner,payload)['status'],'ready')
        self.assertEqual(sem.read('profile',self.owner,{'skills':['其他技能']})['status'],'pending')
        sem.identity=lambda:'different-model'
        self.assertEqual(sem.read('profile',self.owner,payload)['status'],'pending')

    def test_semantic_bad_quote_is_failure_and_no_cache(self):
        sem=self.semantic_service(facts(('photography','并不存在的原文','positive','unspecified')))
        payload={'skills':['会摄影'],'interests':[]};sem.ensure('profile',self.owner,self.owner,payload);sem.process_one()
        result=sem.read('profile',self.owner,payload)
        self.assertEqual(result['status'],'retry');self.assertFalse(result['facts'])
        self.assertFalse(sem.process_one())

    def candidate(self):
        return dict(content_type='volunteer',resource_id='x',job_id='y',title='公益宣传片拍摄',subtitle='影像岗',description='拍摄活动宣传片',requirements='需要会拍视频，必须自备相机',
           location='紫金港',starts_at=(self.now+timedelta(hours=1)).isoformat(),ends_at=(self.now+timedelta(hours=2)).isoformat(),opens_at=(self.now-timedelta(hours=1)).isoformat(),closes_at=(self.now+timedelta(minutes=30)).isoformat(),remaining_capacity=2,href='#/volunteers/x')

    def test_synonyms_match_with_evidence_unknown_equipment_is_not_satisfied(self):
        p=Preferences(skills=['拍过社团宣传片']);c=self.candidate()
        person=facts(('video_shooting','拍过社团宣传片','positive','unspecified'))
        job=facts(('video_shooting','会拍视频','positive','required'),('camera','必须自备相机','positive','required'))
        result=self.guide.matching.match(p,c,self.now,person,job)
        self.assertEqual(result['matching_method'],'semantic_tags');self.assertTrue(result['semantic_evidence'])
        self.assertTrue(any('相机' in x for x in result['checks']))
        self.assertIsNone(self.guide.matching.match(p,c,self.now))

    def test_explicit_negative_required_conflict_and_time_conflict(self):
        p=Preferences(skills=['拍过宣传片','没有相机']);c=self.candidate()
        self.assertTrue(lexical_conflict(p,c))
        person=facts(('video_shooting','拍过宣传片','positive','unspecified'),('camera','没有相机','negative','unspecified'))
        job=facts(('video_shooting','会拍视频','positive','required'),('camera','必须自备相机','positive','required'))
        self.assertIsNone(self.guide.matching.match(p,c,self.now,person,job))
        p=Preferences(skills=['会拍视频'],available_slots=[dict(starts_at=self.now+timedelta(hours=5),ends_at=self.now+timedelta(hours=6))])
        self.assertIsNone(self.guide.matching.match(p,c,self.now,person,job))

    def test_related_skills_and_location_alone_do_not_match(self):
        c=self.candidate();p=Preferences(skills=['会拍照'],locations=['紫金港'])
        self.assertIsNone(self.guide.matching.match(p,c,self.now,facts(('photography','会拍照','positive','unspecified')),facts(('video_shooting','会拍视频','positive','required'))))
        self.assertIsNone(self.guide.matching.match(Preferences(locations=['紫金港']),c,self.now))

    def test_user_can_suppress_and_restore_incorrect_semantic_tag(self):
        self.login('helper')
        profile=self.guide.assistance.save_preferences(self.helper,Preferences(skills=['拍过宣传片']).model_dump(mode='json'),0)
        result=self.client.post('/api/guide/semantics/preferences/correction',json={'version':profile['version'],'tag':'video_shooting','suppressed':True})
        self.assertEqual(result.status_code,200,result.text)
        self.assertIn('video_shooting',result.json()['fields']['semantic_exclusions'])
        self.assertEqual(self.client.post('/api/guide/semantics/preferences/correction',json={'version':profile['version'],'tag':'video_shooting'}).status_code,409)

    def test_remote_semantic_call_does_not_hold_database_transaction(self):
        outer=self
        class Model:
            def chat(self,*args,**kwargs):
                with outer.service.database.connect() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    conn.execute('UPDATE users SET display_name=display_name WHERE id=?',(outer.owner,))
                return {'content':json.dumps(facts(('photography','会摄影','positive','unspecified')))}
        sem=SemanticService(self.service,Model,lambda:'x')
        payload={'skills':['会摄影']};sem.ensure('profile',self.owner,self.owner,payload)
        self.assertTrue(sem.process_one());self.assertEqual(sem.read('profile',self.owner,payload)['status'],'ready')

    def test_review_cancellation_rolls_back_and_read_only_mode_rejects_updates(self):
        from campus.schemas import GuideInput
        r=self.plan();before=self.guide.assistance.read(r['conversation_id'],self.owner)
        b=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner);b.review_only=True
        with self.assertRaises(ValueError):b.plan('volunteer',{'title':'不能偷偷修改'})
        entered,release=threading.Event(),threading.Event()
        class Slow(FakeBackend):
            def chat(inner,*args,**kwargs):
                if inner.requests:entered.set();release.wait(5)
                return super().chat(*args,**kwargs)
        self.guide.backend_factory=lambda:Slow([{'tool_calls':[{'name':'review_activity_plan','arguments':{'proposals':[],'questions':['核对集合点'],'rechecks':[]}}]},{'content':'已生成待确认建议'}])
        run=self.guide.start(GuideInput(message='请评估',purpose='activity_review',conversation_id=r['conversation_id'],expected_assistance_version=before['version']),self.users['publisher'][1])
        try:
            self.assertTrue(entered.wait(3));self.guide.cancel_run(run['run_id'],self.users['publisher'][1])
        finally:release.set()
        for _ in range(150):
            if self.guide.runs.read(run['run_id'],self.owner)['status'] in ('cancelled','failed','succeeded'):break
            time.sleep(.01)
        self.assertEqual(self.guide.runs.read(run['run_id'],self.owner)['status'],'cancelled')
        self.assertEqual(self.guide.assistance.read(r['conversation_id'],self.owner)['version'],before['version'])

    def test_publication_preferences_cache_matching_and_notifications_integrate(self):
        from campus.volunteer_schemas import VolunteerCreate
        fields=self.payload();fields['jobs'][0].update(name='影像岗',description='拍摄宣传片',requirements='需要会拍视频')
        activity=self.vol.create(VolunteerCreate.model_validate(fields),self.owner)
        self.guide.assistance.save_preferences(self.helper,Preferences(skills=['拍过社团宣传片'],notifications_enabled=True,content_types=['volunteer']).model_dump(mode='json'),0)
        class Model:
            def chat(inner,messages,**kwargs):
                source=json.loads(messages[-1]['content'])
                data=facts(('video_shooting','拍过社团宣传片','positive','unspecified')) if source['kind']=='profile' else facts(('video_shooting','会拍视频','positive','required')) if '会拍视频' in json.dumps(source,ensure_ascii=False) else facts()
                return {'content':json.dumps(data,ensure_ascii=False)}
        sem=SemanticService(self.service,Model,lambda:'integration')
        self.guide.matching.semantics=sem;sem.sync_sources()
        while sem.process_one():pass
        self.guide.matching.reconcile()
        items=self.guide.matching.list(self.helper)['items'];self.assertEqual(len(items),1)
        self.assertEqual(items[0]['resource_id'],activity['id']);self.assertEqual(items[0]['matching_method'],'semantic_tags')
        self.guide.matching.reconcile()
        with self.service.database.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'",(self.helper,)).fetchone()[0],1)

    def test_revision_history_is_private_and_preserves_actual_edits(self):
        r=self.plan();b=AssistanceBuffer(self.guide.assistance,r['conversation_id'],self.owner);b.plan('volunteer',{'title':'第二版标题'})
        with self.service.database.connect() as c:b.save(c)
        url=f"/api/guide/assistance/{r['conversation_id']}/revisions"
        rows=self.client.get(url).json()['items'];self.assertEqual(len(rows),2)
        self.assertTrue(any(x['path']=='fields.title' and x['after']=='第二版标题' for x in rows[0]['changes']))
        self.login('helper');self.assertEqual(self.client.get(url).status_code,404)

    def test_general_skill_does_not_establish_proficiency_or_certificate(self):
        p=Preferences(skills=['会拍视频']);c=self.candidate()
        c['requirements']='必须熟练视频拍摄并具备培训证书'
        person=facts(('video_shooting','会拍视频','positive','unspecified'))
        job=facts(('video_shooting','视频拍摄','positive','required'))
        item=self.guide.matching.match(p,c,self.now,person,job)
        self.assertTrue(any('资格或熟练程度尚未确认' in x for x in item['checks']))

    def test_job_source_separates_whole_event_context_from_role_duties(self):
        c=self.candidate();c.update(subtitle='清洁岗',job_description='清理垃圾',activity_description='开展环保行动并拍摄宣传片')
        source=job_source(c)
        self.assertEqual(source['description'],'清理垃圾')
        self.assertEqual(source['title'],'清洁岗')
        self.assertIn('宣传片',source['activity_context'])

    def test_assessment_registry_contains_only_read_and_review(self):
        from campus.schemas import GuideInput
        r=self.plan();captured=[]
        class Model(FakeBackend):
            def chat(inner,messages,tools=None,**kwargs):
                captured.append({t['function']['name'] for t in tools})
                return super().chat(messages,tools=tools,**kwargs)
        self.guide.backend_factory=lambda:Model([{'tool_calls':[{'name':'review_activity_plan','arguments':{'proposals':[],'questions':['核对集合点'],'rechecks':[]}}]},{'content':'已记录评估'}])
        self.guide.chat(GuideInput(message='评估当前草稿',purpose='activity_review',conversation_id=r['conversation_id'],expected_assistance_version=r['assistance']['version']),self.users['publisher'][1])
        self.assertTrue(captured)
        self.assertTrue(all(names=={'get_assistance','review_activity_plan'} for names in captured))


if __name__=='__main__':unittest.main()
