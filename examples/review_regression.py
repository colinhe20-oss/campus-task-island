"""Recheck sparse drafts, role planning and modification impacts with a real model."""
import argparse
import copy
import json
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from campus.app import create_app
from campus.assistance import AssistanceBuffer
from campus.guide import model_backend
from campus.schemas import GuideInput
from .improvement_cases import AT,draft
from .improvement_eval import save


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-model',required=True,action='store_true')
    parser.add_argument('--directory',type=Path,default=Path('.runtime/evals/review-fix'))
    args=parser.parse_args();args.directory.mkdir(parents=True,exist_ok=True)
    report=dict(database_path=str(args.directory/('review-'+uuid4().hex[:12]+'.sqlite3')),rows=[])
    app=create_app(report['database_path'],business_clock=lambda:AT,enable_semantics=False)
    captured=[]
    class Capture:
        def __init__(self):self.backend=model_backend();self.model=self.backend.model
        def chat_stream(self,*a,**kw):
            value=self.backend.chat_stream(*a,**kw)
            captured.append(dict(tool_calls=value.get('tool_calls',[]),usage=value.get('usage',{})))
            return value
        def close(self):self.backend.close()
    with TestClient(app):
        guide=app.state.guide_service;guide.backend_factory=Capture;auth=app.state.auth_service
        for name in ('sparse','roles','changed_time'):
            _,user=auth.register('review.'+uuid4().hex[:12],'评估复测同学','Review-Test-Only-2030')
            cid=uuid4().hex
            with guide.service.database.connect() as c:c.execute('INSERT INTO guide_conversations VALUES (?,?,?,?)',(cid,user.id,'[]',AT.isoformat()))
            fields=draft()
            if name=='sparse':fields={k:fields[k] for k in ('title','description')}
            if name=='changed_time':fields['ends_at']='2030-01-05T15:00:00+08:00'
            buffer=AssistanceBuffer(guide.assistance,cid,user.id);buffer.plan('volunteer',fields,target_volunteers=None if name=='sparse' else 20)
            with guide.service.database.connect() as c:buffer.save(c)
            before=copy.deepcopy(buffer.read()['plan']['fields']);first=len(captured);started=time.monotonic()
            body=GuideInput(message='请评估当前志愿活动草稿，提出有依据的岗位与人数建议、待确认条件及修改影响。不要改草稿字段或发布。',
                            purpose='activity_review',conversation_id=cid,expected_assistance_version=1)
            run_id=guide.start(body,user)['run_id']
            while True:
                run=guide.runs.read(run_id,user.id)
                if run['status'] not in ('running','cancelling'):break
                time.sleep(.2)
            current=guide.assistance.read(cid,user.id)
            review=current['plan'].get('review')
            row=dict(case=name,run_id=run_id,status=run['status'],seconds=round(time.monotonic()-started,2),metrics=run['metrics'],
                passed=run['status']=='succeeded' and bool(review) and current['plan']['fields']==before and not run['metrics'].get('tool_errors'),
                error=run.get('error'),tool_events=[e for e in run['events'] if e['kind']=='tool_finished'],
                review=review,calls=captured[first:])
            report['rows'].append(row);save(args.directory/'report.json',report)
            print(json.dumps({k:row[k] for k in ('case','status','passed','seconds','metrics')},ensure_ascii=False),flush=True)
    report['passed']=all(r['passed'] for r in report['rows']);save(args.directory/'report.json',report)
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
