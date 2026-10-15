"""校园发现：版本化正文、作者自报状态与受控图片可见性。"""
import json
import warnings
from datetime import datetime,timedelta,timezone
from io import BytesIO
from uuid import uuid4
from PIL import Image,ImageOps,UnidentifiedImageError

from .activities import ActivityService
from .discovery_schemas import DiscoveryFields,STATES,TERMINAL
from .errors import AppError
from .notifications import emit

MAX_IMAGE_BYTES=5*1024*1024
MAX_IMAGE_PIXELS=20_000_000


class DiscoveryService:
    def __init__(self,database,clock=None):
        self.database=database
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.media_dir=database.path.parent/'discovery-media'

    now=ActivityService.now

    @staticmethod
    def _get(conn,identifier):
        row=conn.execute('SELECT * FROM discoveries WHERE id=?',(identifier,)).fetchone()
        if row is None:raise AppError('校园发现不存在',404)
        return dict(row)

    @staticmethod
    def _owner(d,user_id):
        if d['author_id']!=user_id:raise AppError('只有发布者可以修改或撤回这条发现',403)

    @staticmethod
    def _active(d):
        if d['withdrawn_at']:raise AppError('该发现已撤回，不能继续操作',409)

    @staticmethod
    def _version(d,version):
        if d['version']!=version:raise AppError('发现已被更新，请读取最新版本后再提交；填写内容可保留',409)

    def _fields(self,body,now):
        if body.discovered_at>now:raise AppError('发现时间不能晚于服务端当前时间',422)
        result=body.model_dump(mode='json',include=set(DiscoveryFields.model_fields))
        result['discovered_at']=body.discovered_at.astimezone(timezone.utc).isoformat()
        result['image_ids']=json.dumps(body.image_ids)
        return result

    @staticmethod
    def _snapshot(d):
        return {k:(json.loads(d[k]) if k=='image_ids' else d[k]) for k in ('title','description','category','location','discovered_at','information_source','image_ids','status','withdrawn_at','withdrawal_reason')}

    def _history(self,conn,d,actor,action,now,before=None,reason='',changed=()):
        conn.execute('INSERT INTO discovery_versions VALUES (?,?,?,?,?,?,?,?,?)',
                     (d['id'],d['version'],actor,action,reason,json.dumps(list(changed)),json.dumps(self._snapshot(before) if before else {},ensure_ascii=False),json.dumps(self._snapshot(d),ensure_ascii=False),now.isoformat()))

    def _images(self,conn,image_ids,user_id,*,discovery_id=None,comment_id=None,now):
        cutoff=(now-timedelta(hours=24)).isoformat()
        for identifier in image_ids:
            row=conn.execute('SELECT * FROM discovery_images WHERE id=?',(identifier,)).fetchone()
            if row is None or not (self.media_dir/(identifier+'.jpg')).is_file():raise AppError('图片不存在或已过期，请重新上传',422)
            if row['uploader_id']!=user_id:raise AppError('只能引用本人上传的图片',403)
            linked=row['attached_discovery_id'] or row['attached_comment_id']
            if linked and not ((discovery_id and row['attached_discovery_id']==discovery_id) or (comment_id and row['attached_comment_id']==comment_id)):
                raise AppError('图片已用于其他内容，请重新上传',422)
            if not linked and row['created_at']<=cutoff:raise AppError('暂存图片已过期，请重新上传',422)

    @staticmethod
    def _attach(conn,images,discovery_id=None,comment_id=None):
        for identifier in images:
            conn.execute('UPDATE discovery_images SET attached_discovery_id=?,attached_comment_id=? WHERE id=?',(discovery_id,comment_id,identifier))

    def _read(self,conn,d,user_id=None,detail=False):
        owner=d['author_id']==user_id
        if d['withdrawn_at'] and not owner:
            return {'id':d['id'],'withdrawn':True,'withdrawn_at':d['withdrawn_at'],'is_owner':False}
        result=dict(d)
        result['image_ids']=json.loads(d['image_ids'])
        result.update(withdrawn=bool(d['withdrawn_at']),is_owner=owner,
                      author_name=conn.execute('SELECT display_name FROM users WHERE id=?',(d['author_id'],)).fetchone()[0],
                      comment_count=conn.execute('SELECT COUNT(*) FROM discovery_comments WHERE discovery_id=? AND withdrawn_at IS NULL',(d['id'],)).fetchone()[0],
                      status_source='author_report',allowed_statuses=list(STATES[d['category']]))
        if detail:
            result['status_history']=[dict(r)|{'source':'author_report'} for r in conn.execute('SELECT h.previous_status,h.status,h.reason,h.created_at,u.display_name AS actor_name FROM discovery_status_history h JOIN users u ON u.id=h.actor_id WHERE discovery_id=? ORDER BY h.id',(d['id'],))]
            result['changes']=[dict(r)|{'changed_fields':json.loads(r['changed_fields'])} for r in conn.execute("SELECT v.version,v.action,v.changed_fields,v.created_at,u.display_name AS actor_name FROM discovery_versions v JOIN users u ON u.id=v.actor_id WHERE discovery_id=? ORDER BY version DESC",(d['id'],))]
        return result

    def create(self,body,user_id):
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');now=self.now();fields=self._fields(body,now)
            self._images(c,body.image_ids,user_id,now=now)
            fields.update(id=uuid4().hex,author_id=user_id,category=body.category,status=STATES[body.category][0],version=1,created_at=now.isoformat(),updated_at=now.isoformat())
            c.execute(f"INSERT INTO discoveries ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",tuple(fields.values()))
            self._attach(c,body.image_ids,discovery_id=fields['id'])
            d=self._get(c,fields['id']);self._history(c,d,user_id,'published',now,changed=DiscoveryFields.model_fields)
            c.execute('INSERT INTO discovery_status_history (discovery_id,actor_id,previous_status,status,reason,created_at) VALUES (?,?,NULL,?,?,?)',(d['id'],user_id,d['status'],'发布时初始状态',now.isoformat()))
            return self._read(c,d,user_id,True)

    def detail(self,identifier,user_id=None):
        with self.database.connect() as c:
            c.execute('BEGIN');result=self._read(c,self._get(c,identifier),user_id,True)
            return result|{'server_time':self.now().isoformat(),'next_boundary':None}

    def search(self,keyword='',category=None,status=None,limit=20,offset=0,user_id=None,mine=False):
        clauses=[];args=[]
        if mine:
            clauses.append('author_id=?');args.append(user_id)
        else:clauses.append('withdrawn_at IS NULL')
        if category:clauses.append('category=?');args.append(category)
        if status:clauses.append('status=?');args.append(status)
        elif not mine:
            clauses.append("status NOT IN ('resolved','invalid','expired')")
        # instr 是文字匹配，不将用户的 %/_ 当 SQL 通配符。
        if keyword:clauses.append('instr(lower(title||description||location||information_source),lower(?))>0');args.append(keyword)
        where=' AND '.join(clauses) or '1=1'
        with self.database.connect() as c:
            c.execute('BEGIN')
            total=c.execute('SELECT COUNT(*) FROM discoveries WHERE '+where,args).fetchone()[0]
            rows=c.execute('SELECT * FROM discoveries WHERE '+where+' ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
            return dict(items=[self._read(c,dict(r),user_id) for r in rows],total=total,limit=limit,offset=offset,server_time=self.now().isoformat(),next_boundary=None)

    def edit(self,identifier,user_id,body):
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');now=self.now();old=self._get(c,identifier)
            self._owner(old,user_id);self._active(old);self._version(old,body.version)
            fields=self._fields(body,now);self._images(c,body.image_ids,user_id,discovery_id=identifier,now=now)
            changed=[k for k,v in fields.items() if old[k]!=v]
            if not changed:return self._read(c,old,user_id,True)
            c.execute('UPDATE discoveries SET '+','.join(f'{k}=?' for k in fields)+',version=version+1,updated_at=? WHERE id=?',(*fields.values(),now.isoformat(),identifier))
            self._attach(c,body.image_ids,discovery_id=identifier)
            d=self._get(c,identifier);self._history(c,d,user_id,'edited',now,old,changed=changed)
            return self._read(c,d,user_id,True)

    def state(self,identifier,user_id,body,withdraw=False):
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');now=self.now();old=self._get(c,identifier)
            self._owner(old,user_id);self._active(old);self._version(old,body.version)
            if withdraw:
                c.execute('UPDATE discoveries SET withdrawn_at=?,withdrawal_reason=?,version=version+1,updated_at=? WHERE id=?',(now.isoformat(),body.reason,now.isoformat(),identifier))
            else:
                if body.status not in STATES[old['category']]:raise AppError('该状态不属于当前发现分类',422)
                if body.status==old['status']:raise AppError('状态没有变化，请选择新的状态',422)
                c.execute('UPDATE discoveries SET status=?,version=version+1,updated_at=? WHERE id=?',(body.status,now.isoformat(),identifier))
                c.execute('INSERT INTO discovery_status_history (discovery_id,actor_id,previous_status,status,reason,created_at) VALUES (?,?,?,?,?,?)',(identifier,user_id,old['status'],body.status,body.reason,now.isoformat()))
            d=self._get(c,identifier)
            self._history(c,d,user_id,'withdrawn' if withdraw else 'status_updated',now,old,body.reason,['withdrawn_at'] if withdraw else ['status'])
            return self._read(c,d,user_id,True)

    def versions(self,identifier,user_id):
        with self.database.connect() as c:
            c.execute('BEGIN');self._owner(self._get(c,identifier),user_id)
            return dict(items=[dict(r)|{k:json.loads(r[k]) for k in ('before_fields','after_fields','changed_fields')} for r in c.execute('SELECT * FROM discovery_versions WHERE discovery_id=? ORDER BY version DESC',(identifier,))])

    def _comment_read(self,c,r,user_id=None):
        if r['withdrawn_at']:
            return dict(id=r['id'],withdrawn=True,created_at=r['created_at'],withdrawn_at=r['withdrawn_at'])
        return dict(r)|{'image_ids':json.loads(r['image_ids']),'withdrawn':False,'is_owner':r['author_id']==user_id,
                        'author_name':c.execute('SELECT display_name FROM users WHERE id=?',(r['author_id'],)).fetchone()[0]}

    def comments(self,identifier,user_id=None,limit=20,offset=0):
        with self.database.connect() as c:
            c.execute('BEGIN');d=self._get(c,identifier)
            if d['withdrawn_at']:raise AppError('该发现已撤回，评论不再公开',410)
            rows=c.execute('SELECT * FROM discovery_comments WHERE discovery_id=? ORDER BY created_at,id LIMIT ? OFFSET ?',(identifier,limit,offset)).fetchall()
            total=c.execute('SELECT COUNT(*) FROM discovery_comments WHERE discovery_id=?',(identifier,)).fetchone()[0]
            return dict(items=[self._comment_read(c,dict(r),user_id) for r in rows],total=total,limit=limit,offset=offset,server_time=self.now().isoformat(),next_boundary=None)

    def comment(self,identifier,user_id,body):
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');now=self.now();self._active(self._get(c,identifier))
            self._images(c,body.image_ids,user_id,now=now)
            cid=uuid4().hex
            c.execute('INSERT INTO discovery_comments VALUES (?,?,?,?,?,?,NULL)',(cid,identifier,user_id,body.content,json.dumps(body.image_ids),now.isoformat()))
            self._attach(c,body.image_ids,comment_id=cid)
            parent=self._get(c,identifier)
            if parent['author_id']!=user_id:
                emit(c,parent['author_id'],'comment:'+cid,'discovery',identifier,'校园发现收到新评论','前往查看最新情况与评论。',now.isoformat())
            return self._comment_read(c,dict(c.execute('SELECT * FROM discovery_comments WHERE id=?',(cid,)).fetchone()),user_id)

    def withdraw_comment(self,comment_id,user_id):
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');now=self.now();r=c.execute('SELECT * FROM discovery_comments WHERE id=?',(comment_id,)).fetchone()
            if r is None:raise AppError('评论不存在',404)
            if r['author_id']!=user_id:raise AppError('只能撤回本人的评论',403)
            self._active(self._get(c,r['discovery_id']))
            if not r['withdrawn_at']:c.execute('UPDATE discovery_comments SET withdrawn_at=? WHERE id=?',(now.isoformat(),comment_id))
            return {'id':comment_id,'withdrawn':True}

    def cleanup_images(self):
        # 与引用图片共用数据库写锁，避免清理和发布同时使用同一暂存图片。
        self.media_dir.mkdir(parents=True,exist_ok=True)
        with self.database.connect() as c:
            c.execute('BEGIN IMMEDIATE');cutoff=(self.now()-timedelta(hours=24)).isoformat()
            for r in c.execute('SELECT id FROM discovery_images WHERE attached_discovery_id IS NULL AND attached_comment_id IS NULL AND created_at<=?',(cutoff,)).fetchall():
                (self.media_dir/(r['id']+'.jpg')).unlink(missing_ok=True)
                c.execute('DELETE FROM discovery_images WHERE id=?',(r['id'],))

    def upload(self,raw,user_id):
        if not raw or len(raw)>MAX_IMAGE_BYTES:raise AppError('图片不能为空且不能超过5 MiB',413)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as source:
                    if source.format not in ('JPEG','PNG','WEBP') or getattr(source,'n_frames',1)!=1:
                        raise AppError('只接受非动画的 JPEG、PNG、WebP 图片',422)
                    if source.width*source.height>MAX_IMAGE_PIXELS:raise AppError('图片不能超过2000万像素',422)
                    source.load()
                    oriented=ImageOps.exif_transpose(source)
                    image=oriented.convert('RGBA')
                    image.thumbnail((4096,4096))
                    normalized=Image.new('RGB',image.size,'white');normalized.paste(image,mask=image.getchannel('A'))
                    out=BytesIO();normalized.save(out,format='JPEG',quality=88)
        except AppError:raise
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombWarning,Image.DecompressionBombError):
            raise AppError('图片损坏或格式不受支持，请换一张图片',422) from None
        self.cleanup_images()
        identifier=uuid4().hex;path=self.media_dir/(identifier+'.jpg');temporary=path.with_suffix('.tmp')
        try:
            temporary.write_bytes(out.getvalue());temporary.replace(path)
            with self.database.connect() as c:
                c.execute('INSERT INTO discovery_images VALUES (?,?,?,?,?,?,NULL,NULL)',(identifier,user_id,self.now().isoformat(),normalized.width,normalized.height,len(out.getvalue())))
        except Exception:
            temporary.unlink(missing_ok=True);path.unlink(missing_ok=True);raise
        return dict(id=identifier,url=f'/api/discovery-images/{identifier}',width=normalized.width,height=normalized.height,size=len(out.getvalue()))

    def image_path(self,identifier,user_id=None):
        with self.database.connect() as c:
            c.execute('BEGIN');r=c.execute('SELECT * FROM discovery_images WHERE id=?',(identifier,)).fetchone()
            if r is None:raise AppError('图片不存在或不可访问',404)
            allowed=r['uploader_id']==user_id
            if not allowed and r['attached_discovery_id']:
                d=self._get(c,r['attached_discovery_id']);allowed=not d['withdrawn_at'] and identifier in json.loads(d['image_ids'])
            if not allowed and r['attached_comment_id']:
                comment=c.execute('SELECT * FROM discovery_comments WHERE id=?',(r['attached_comment_id'],)).fetchone()
                if comment:
                    d=self._get(c,comment['discovery_id']);allowed=not d['withdrawn_at'] and not comment['withdrawn_at'] and identifier in json.loads(comment['image_ids'])
            if not allowed:raise AppError('图片不存在或不可访问',404)
            if not (r['attached_discovery_id'] or r['attached_comment_id']) and r['created_at']<=(self.now()-timedelta(hours=24)).isoformat():
                raise AppError('图片已过期',404)
            path=self.media_dir/(identifier+'.jpg')
            if not path.is_file():raise AppError('图片不存在',404)
            return path
