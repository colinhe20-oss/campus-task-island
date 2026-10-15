"""只读首页摘要，所有待办来自同一数据库快照。"""
from datetime import datetime
from .todos import personal_state
from .notifications import NotificationService

class HomeService:
    def __init__(self,tasks,activities,volunteers):
        self.tasks=tasks;self.database=tasks.database;self.activities=activities;self.volunteers=volunteers

    def summary(self,user_id):
        items=[];boundaries=[]
        def add(kind,identifier,title,action,label,count,stamp,priority):
            route={'task':'tasks','activity':'activities','volunteer':'volunteers'}[kind]
            items.append(dict(content_type=kind,resource_id=identifier,title=title,action=action,action_label=label,count=count,created_at=stamp,priority=priority,href=f'#/{route}/{identifier}'+('?manage=1' if kind!='task' else '')))
        with self.database.connect() as c:
            c.execute('BEGIN')
            personal=personal_state(self.tasks,user_id,connection=c)
            for item in personal.todos:
                task=c.execute('SELECT created_at,deadline FROM tasks WHERE id=?',(item.task_id,)).fetchone()
                stamp=task['created_at']
                if item.action=='review_applications':
                    stamp=c.execute("SELECT MIN(created_at) FROM applications WHERE task_id=? AND status='pending'",(item.task_id,)).fetchone()[0] or stamp
                elif item.action=='review_results':
                    stamp=c.execute("SELECT MIN(created_at) FROM submissions WHERE task_id=? AND status='submitted'",(item.task_id,)).fetchone()[0] or stamp
                elif item.action=='review_stage':
                    stamp=c.execute("SELECT MIN(created_at) FROM stage_submissions WHERE task_id=? AND status='submitted'",(item.task_id,)).fetchone()[0] or stamp
                if item.action=='review_change':
                    stamp=c.execute("SELECT created_at FROM task_changes WHERE task_id=? AND status='pending'",(item.task_id,)).fetchone()[0]
                elif item.action=='extend_deadline':stamp=task['deadline'] or stamp
                elif item.action=='confirm_settlement':
                    stamp=c.execute('SELECT COALESCE((SELECT MAX(reviewed_at) FROM submissions WHERE task_id=?),(SELECT MAX(reviewed_at) FROM stage_submissions WHERE task_id=?),?)',(item.task_id,item.task_id,stamp)).fetchone()[0]
                add('task',item.task_id,item.title,item.action,item.action_label,1,stamp,0 if item.action=='confirm_settlement' else 0 if item.action.startswith('review_') and item.action!='review_applications' else 1 if item.action=='review_applications' else 2)
            for row in c.execute('SELECT * FROM tasks WHERE publisher_id=? OR assignee_id=?',(user_id,user_id)):
                task=self.tasks.read_row(row)
                if task.next_boundary:boundaries.append(task.next_boundary)
            now=self.activities.now()
            for a in c.execute('SELECT * FROM activities WHERE owner_id=? AND cancelled_at IS NULL',(user_id,)).fetchall():
                start=datetime.fromisoformat(a['starts_at'])
                if start>now:
                    boundaries.append(start)
                    row=c.execute("SELECT COUNT(*),MIN(created_at) FROM activity_registrations WHERE activity_id=? AND status='pending'",(a['id'],)).fetchone()
                    if row[0]:add('activity',a['id'],a['title'],'review_registrations','审核活动报名',row[0],row[1],1)
            vnow=self.volunteers.now()
            for row in c.execute('SELECT j.*,a.title,a.owner_id,a.cancelled_at FROM volunteer_jobs j JOIN volunteer_activities a ON a.id=j.activity_id WHERE a.owner_id=?',(user_id,)).fetchall():
                j=dict(row);a=dict(c.execute('SELECT * FROM volunteer_activities WHERE id=?',(j['activity_id'],)).fetchone())
                for key in ('starts_at','ends_at'):
                    boundary=datetime.fromisoformat(j[key])
                    if boundary>vnow and not a['cancelled_at']:boundaries.append(boundary)
                regs=[dict(r) for r in c.execute('SELECT * FROM volunteer_registrations WHERE job_id=?',(j['id'],))]
                pending=[r for r in regs if r['status']=='pending']
                if pending and not a['cancelled_at'] and vnow<datetime.fromisoformat(j['starts_at']):
                    add('volunteer',a['id'],a['title']+' · '+j['name'],'review_registrations','审核岗位申请',len(pending),min(r['created_at'] for r in pending),1)
                missing=[];hours=[]
                for r in regs:
                    if not self.volunteers._qualified(r,a,j,vnow):continue
                    record=c.execute('SELECT * FROM volunteer_participation WHERE registration_id=?',(r['id'],)).fetchone()
                    if record is None:missing.append(r)
                    elif record['confirmed_minutes'] is None and (vnow>=datetime.fromisoformat(j['ends_at']) or a['cancelled_at']):hours.append(dict(record))
                if missing:add('volunteer',a['id'],a['title']+' · '+j['name'],'record_participation','登记岗位参与',len(missing),j['starts_at'],0)
                if hours:add('volunteer',a['id'],a['title']+' · '+j['name'],'verify_hours','核验活动方确认小时',len(hours),min(r['updated_at'] for r in hours),0)
            items.sort(key=lambda i:(i['priority'],datetime.fromisoformat(i['created_at']),i['content_type'],i['resource_id'],i['title'],i['action']))
            return dict(todos=items[:5],todo_count=len(items),completed_count=personal.completed_count,unread_count=NotificationService.unread(c,user_id),server_time=now.isoformat(),next_boundary=min(boundaries).isoformat() if boundaries else None)
