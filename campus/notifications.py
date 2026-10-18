"""持久站内消息。emit 必须使用业务操作已有的连接，绝不独立提交。"""
from datetime import datetime, timezone
import json
from .errors import AppError
from .clock import utc_now

STATEMENTS = [
    '''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipient_id TEXT NOT NULL REFERENCES users(id), event_key TEXT NOT NULL,
        content_type TEXT NOT NULL CHECK(content_type IN ('task','activity','volunteer','discovery')),
        resource_id TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
        created_at TEXT NOT NULL, read_at TEXT, UNIQUE(recipient_id,event_key))''',
    'CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_id,id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(recipient_id,id DESC) WHERE read_at IS NULL',
]
ROUTES={'task':'tasks','activity':'activities','volunteer':'volunteers','discovery':'discoveries'}

def emit(conn, recipient, event_key, kind, resource_id, title, summary='', created_at=None):
    if recipient is None:return
    account=conn.execute('SELECT account_status FROM users WHERE id=?',(recipient,)).fetchone()
    if account is None or account['account_status']!='active':return
    conn.execute('''INSERT INTO notifications(recipient_id,event_key,content_type,resource_id,title,summary,created_at)
        VALUES (?,?,?,?,?,?,?) ON CONFLICT(recipient_id,event_key) DO NOTHING''',
        (recipient,event_key,kind,resource_id,title,summary,created_at or utc_now().isoformat()))

def registration_event(conn,kind,activity_id,registration_id,action,event_key,stamp):
    if not registration_id:return
    prefix='activity' if kind=='activity' else 'volunteer'
    table='activities' if kind=='activity' else 'volunteer_activities'
    a=conn.execute(f'SELECT * FROM {table} WHERE id=?',(activity_id,)).fetchone()
    r=conn.execute(f'SELECT * FROM {prefix}_registrations WHERE id=?',(registration_id,)).fetchone()
    labels={'applied':'申请已提交，待审核','registered':'报名成功','waitlisted':'已进入候补','rejected':'报名申请未通过','promoted':'候补已转正','activity_cancelled':'活动方已取消活动','participation_updated':'参与记录已更新，小时需重新核验','hours_confirmed':'活动方确认小时已更新'}
    title=labels.get(action)
    if action=='participation_updated':
        version=conn.execute('SELECT before_fields FROM volunteer_record_versions WHERE registration_id=? ORDER BY version DESC LIMIT 1',(registration_id,)).fetchone()
        invalidated=version and json.loads(version[0]).get('confirmed_minutes') is not None
        title='参与记录已更正，原小时确认失效，需重新核验' if invalidated else '参与记录已更新'
    if action=='approved':title='审核通过，报名成功' if r['status']=='registered' else '审核通过，已进入候补'
    key=f'{kind}:{event_key}'
    if title:
        # 一场取消每人一条，保留已发生服务的志愿参与者同样收到提醒。
        if action=='activity_cancelled':key=f'{kind}:cancel:{activity_id}'
        emit(conn,r['user_id'],key,kind,activity_id,title,a['title'],stamp)
    if action in ('applied','cancelled'):
        emit(conn,a['owner_id'],key+':owner',kind,activity_id,'收到待审核申请' if action=='applied' else '参与者已取消申请或报名',a['title'],stamp)

class NotificationService:
    def __init__(self,database):self.database=database

    @staticmethod
    def unread(conn,user_id):
        return conn.execute('SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND read_at IS NULL',(user_id,)).fetchone()[0]

    def count(self,user_id):
        with self.database.connect() as c:
            return dict(unread_count=self.unread(c,user_id),server_time=utc_now().isoformat(),next_boundary=None)

    def list(self,user_id,unread_only=False,limit=20,before_id=None):
        with self.database.connect() as c:
            c.execute('BEGIN')
            maximum=c.execute('SELECT COALESCE(MAX(id),0) FROM notifications WHERE recipient_id=?',(user_id,)).fetchone()[0]
            clauses=['recipient_id=?'];args=[user_id]
            if unread_only:clauses.append('read_at IS NULL')
            if before_id is not None:clauses.append('id<?');args.append(before_id)
            rows=c.execute('SELECT * FROM notifications WHERE '+' AND '.join(clauses)+' ORDER BY id DESC LIMIT ?',(*args,limit+1)).fetchall()
            items=[]
            for row in rows[:limit]:
                item={k:row[k] for k in ('id','content_type','title','summary','created_at','read_at')}
                item['href']=f"#/{ROUTES[row['content_type']]}/{row['resource_id']}"
                items.append(item)
            return dict(items=items,next_cursor=items[-1]['id'] if len(rows)>limit else None,max_id=maximum,unread_count=self.unread(c,user_id),server_time=utc_now().isoformat(),next_boundary=None)

    def read(self,user_id,identifier=None,through_id=None):
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');stamp=utc_now().isoformat()
            if identifier is not None:
                row=c.execute('SELECT id FROM notifications WHERE id=? AND recipient_id=?',(identifier,user_id)).fetchone()
                if row is None:raise AppError('消息不存在',404)
                c.execute('UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=?',(stamp,identifier))
            else:c.execute('UPDATE notifications SET read_at=? WHERE recipient_id=? AND id<=? AND read_at IS NULL',(stamp,user_id,through_id))
            return dict(ok=True,unread_count=self.unread(c,user_id))
