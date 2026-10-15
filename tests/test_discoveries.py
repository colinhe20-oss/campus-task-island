import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from io import BytesIO
from threading import Barrier
from PIL import Image
from pydantic import ValidationError
import test_guide as helpers
from campus.discoveries import MAX_IMAGE_BYTES
from campus.discovery_schemas import DiscoveryCreate,DiscoveryEdit,DiscoveryStateInput,DiscoveryWithdraw,DiscoveryCommentInput
from campus.errors import AppError


def picture(format='PNG',size=(48,32)):
    out=BytesIO();Image.new('RGB',size,'green').save(out,format=format);return out.getvalue()


class DiscoveryTests(unittest.TestCase):
    setUpBase=helpers.GuideTests.setUp
    login=helpers.GuideTests.login

    def setUp(self):
        self.setUpBase();self.now=datetime(2030,1,1,tzinfo=timezone.utc)
        self.dis=self.app.state.discovery_service;self.dis.clock=lambda:self.now
        self.owner=self.users['publisher'][1].id;self.helper=self.users['helper'][1].id

    def payload(self,**updates):
        return dict(title='图书馆路灯异常',category='facility',description='东门路灯不亮',location='图书馆东门',discovered_at=self.now.isoformat(),information_source='本人观察',image_ids=[])|updates

    def create(self,**updates):return self.dis.create(DiscoveryCreate.model_validate(self.payload(**updates)),self.owner)
    def edit(self,d,**updates):return self.dis.edit(d['id'],self.owner,DiscoveryEdit.model_validate({k:d[k] for k in ('title','description','location','discovered_at','information_source','image_ids','version')}|updates))
    def state(self,d,status='verified'):return self.dis.state(d['id'],self.owner,DiscoveryStateInput(version=d['version'],status=status,reason='现场观察后更新'))
    def withdraw(self,d):return self.dis.state(d['id'],self.owner,DiscoveryWithdraw(version=d['version'],reason='撤回测试内容'),True)
    def upload(self,user=None,raw=None):return self.dis.upload(raw or picture(),user or self.owner)

    def test_required_fields_timezone_future_and_identity_spoof(self):
        self.login()
        for fields in ({'title':' '},{'location':''},{'discovered_at':'2030-01-01T00:00:00'},{'information_source':''},{'author_id':self.helper},{'category':'volunteer'}):
            self.assertEqual(self.client.post('/api/discoveries',json=self.payload(**fields)).status_code,422)
        self.assertEqual(self.client.post('/api/discoveries',json=self.payload(discovered_at=(self.now+timedelta(seconds=1)).isoformat())).status_code,422)

    def test_any_logged_in_user_can_publish(self):
        self.login('helper');r=self.client.post('/api/discoveries',json=self.payload())
        self.assertEqual(r.status_code,201);self.assertEqual(r.json()['author_id'],self.helper)

    def test_initial_states_and_category_specific_updates(self):
        for category,initial,next_state in [('facility','unverified','reported'),('safety','valid','invalid'),('interesting','visible','expired'),('life','visible','expired')]:
            d=self.create(category=category);self.assertEqual(d['status'],initial)
            self.assertEqual(self.state(d,next_state)['status'],next_state)
            with self.assertRaises(AppError):self.state(d,'in_progress' if category!='facility' else 'expired')

    def test_status_requires_reason_and_different_value(self):
        d=self.create();self.login()
        self.assertEqual(self.client.post('/api/discoveries/'+d['id']+'/status',json={'version':1,'status':'verified','reason':' '}).status_code,422)
        with self.assertRaises(AppError):self.state(d,'unverified')

    def test_end_states_hidden_and_reopen_allowed(self):
        d=self.create();closed=self.state(d,'resolved')
        self.assertEqual(self.dis.search()['total'],0)
        self.assertEqual(self.dis.search(status='resolved')['total'],1)
        self.assertEqual(self.dis.detail(d['id'])['status'],'resolved')
        self.state(closed,'in_progress');self.assertEqual(self.dis.search()['total'],1)

    def test_keyword_category_status_and_pagination(self):
        self.create(title='特殊%_文字');self.create(category='safety',title='通行提醒')
        self.assertEqual(self.dis.search(keyword='%_')['total'],1)
        self.assertEqual(self.dis.search(keyword="' OR 1=1 --")['total'],0)
        self.assertEqual(self.dis.search(category='safety')['total'],1)
        self.assertEqual(len(self.dis.search(limit=1,offset=1)['items']),1)
        self.assertEqual(self.dis.search(keyword='本人观察')['total'],2)

    def test_public_history_hides_old_body_and_private_versions(self):
        d=self.create(description='原始私有版本内容');updated=self.edit(d,description='更正后的公开说明')
        public=self.dis.detail(d['id'])
        self.assertNotIn('原始私有版本内容',json.dumps(public,ensure_ascii=False))
        self.assertEqual(public['changes'][0]['changed_fields'],['description'])
        versions=self.dis.versions(d['id'],self.owner)['items']
        self.assertEqual(versions[0]['before_fields']['description'],'原始私有版本内容')
        self.assertEqual(updated['version'],2)
        with self.assertRaises(AppError):self.dis.versions(d['id'],self.helper)

    def test_status_history_records_author_source_and_shared_version(self):
        d=self.create();edited=self.edit(d,title='已纠错标题');updated=self.state(edited,'reported')
        self.assertEqual(updated['version'],3)
        self.assertEqual(updated['status_history'][-1]['source'],'author_report')
        self.assertEqual(updated['status_history'][-1]['previous_status'],'unverified')
        with self.assertRaises(AppError):self.edit(d,title='过期覆盖')

    def test_category_cannot_be_edited(self):
        d=self.create();self.login()
        fields={k:d[k] for k in ('title','description','location','discovered_at','information_source','image_ids','version')}
        self.assertEqual(self.client.patch('/api/discoveries/'+d['id'],json=fields|{'category':'safety'}).status_code,422)

    def test_edit_and_state_concurrent_only_one_version_wins(self):
        d=self.create();gate=Barrier(2)
        def run(edit):
            gate.wait()
            try:return self.edit(d,title='并发编辑') if edit else self.state(d)
            except AppError:return None
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,[True,False]))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.dis.detail(d['id'])['version'],2)

    def test_comment_pagination_and_comment_does_not_bump_version(self):
        d=self.create()
        for index in range(3):
            self.now+=timedelta(seconds=1)
            self.dis.comment(d['id'],self.helper,DiscoveryCommentInput(content='补充'+str(index)))
        result=self.dis.comments(d['id'],limit=1,offset=1)
        self.assertEqual(result['items'][0]['content'],'补充1');self.assertEqual(result['total'],3)
        detail=self.dis.detail(d['id']);self.assertEqual(detail['version'],1);self.assertEqual(detail['comment_count'],3)

    def test_terminal_discovery_can_still_receive_comments(self):
        d=self.state(self.create(),'resolved')
        self.dis.comment(d['id'],self.helper,DiscoveryCommentInput(content='再次出现问题'))
        self.assertEqual(self.dis.comments(d['id'])['total'],1)

    def test_withdrawn_comment_placeholder_and_image_visibility(self):
        d=self.create();image=self.upload(self.helper)
        r=self.dis.comment(d['id'],self.helper,DiscoveryCommentInput(content='撤回前的评论原文',image_ids=[image['id']]))
        self.assertTrue(self.dis.image_path(image['id']).is_file())
        with self.assertRaises(AppError):self.dis.withdraw_comment(r['id'],self.owner)
        self.dis.withdraw_comment(r['id'],self.helper)
        public=self.dis.comments(d['id'])['items'][0]
        self.assertTrue(public['withdrawn']);self.assertNotIn('content',public);self.assertNotIn('image_ids',public)
        with self.assertRaises(AppError):self.dis.image_path(image['id'])
        self.assertTrue(self.dis.image_path(image['id'],self.helper).is_file())
        self.assertEqual(self.dis.detail(d['id'])['comment_count'],0)

    def test_withdrawn_discovery_hides_all_public_data_and_keeps_owner_history(self):
        image=self.upload();d=self.create(image_ids=[image['id']]);self.dis.comment(d['id'],self.helper,DiscoveryCommentInput(content='补充内容'))
        self.withdraw(d);public=self.dis.detail(d['id'])
        self.assertTrue(public['withdrawn'])
        for key in ('title','description','image_ids','status_history','changes','author_id'):self.assertNotIn(key,public)
        with self.assertRaises(AppError):self.dis.comments(d['id'])
        with self.assertRaises(AppError):self.dis.image_path(image['id'])
        self.assertEqual(self.dis.search()['total'],0)
        own=self.dis.search(user_id=self.owner,mine=True)['items'][0]
        self.assertTrue(own['withdrawn']);self.assertEqual(own['title'],d['title'])
        self.assertEqual(len(self.dis.versions(d['id'],self.owner)['items']),2)

    def test_withdrawn_discovery_stops_all_writes(self):
        d=self.withdraw(self.create())
        for call in (lambda:self.edit(d),lambda:self.state(d),lambda:self.dis.comment(d['id'],self.helper,DiscoveryCommentInput(content='补充'))):
            with self.assertRaises(AppError):call()

    def test_withdraw_and_comment_concurrent_no_public_comment_survives(self):
        d=self.create();gate=Barrier(2)
        def run(withdraw):
            gate.wait()
            try:return self.withdraw(d) if withdraw else self.dis.comment(d['id'],self.helper,DiscoveryCommentInput(content='并发评论'))
            except AppError:return None
        with ThreadPoolExecutor(2) as pool:list(pool.map(run,[True,False]))
        self.assertTrue(self.dis.detail(d['id'])['withdrawn'])
        with self.assertRaises(AppError):self.dis.comments(d['id'])

    def test_other_user_cannot_edit_state_or_withdraw(self):
        d=self.create();self.login('helper')
        fields={k:d[k] for k in ('title','description','location','discovered_at','information_source','image_ids','version')}
        for method,path,body in [('patch','',fields),('post','/status',{'version':1,'status':'verified','reason':'越权'}),('post','/withdraw',{'version':1,'reason':'越权'})]:
            self.assertEqual(self.client.request(method,'/api/discoveries/'+d['id']+path,json=body).status_code,403)
        self.assertEqual(self.client.get('/api/discoveries/'+d['id']+'/versions').status_code,403)

    def test_unauthenticated_writes_and_invalid_cookie_public_read(self):
        d=self.create();self.client.cookies.clear()
        self.assertEqual(self.client.post('/api/discoveries',json=self.payload()).status_code,401)
        self.assertEqual(self.client.post('/api/discoveries/'+d['id']+'/comments',json={'content':'补充'}).status_code,401)
        self.assertEqual(self.client.get('/api/me/discoveries').status_code,401)
        self.client.cookies.set('campus_session','expired')
        self.assertEqual(self.client.get('/api/discoveries/'+d['id']).status_code,200)

    def test_upload_formats_and_normalized_jpeg_metadata(self):
        for format in ('PNG','JPEG','WEBP'):
            image=self.upload(raw=picture(format));path=self.dis.image_path(image['id'],self.owner)
            with Image.open(path) as normalized:
                self.assertEqual(normalized.format,'JPEG');self.assertEqual(normalized.size,(48,32));self.assertFalse(normalized.getexif())
        self.assertEqual(self.dis.search()['total'],0)

    def test_uploaded_exif_orientation_is_applied_and_metadata_removed(self):
        source=Image.new('RGB',(40,20),'red');exif=Image.Exif();exif[274]=6;exif[270]='private description'
        raw=BytesIO();source.save(raw,format='JPEG',exif=exif)
        image=self.upload(raw=raw.getvalue())
        with Image.open(self.dis.image_path(image['id'],self.owner)) as normalized:
            self.assertEqual(normalized.size,(20,40));self.assertFalse(normalized.getexif())

    def test_transparency_composited_and_long_edge_resized(self):
        source=Image.new('RGBA',(4100,2),(255,0,0,0));raw=BytesIO();source.save(raw,format='PNG')
        image=self.upload(raw=raw.getvalue())
        with Image.open(self.dis.image_path(image['id'],self.owner)) as normalized:
            self.assertEqual(normalized.width,4096);self.assertEqual(normalized.mode,'RGB');self.assertGreater(normalized.getpixel((0,0))[0],240)

    def test_invalid_corrupt_animation_size_and_pixels_rejected(self):
        for raw in (b'<svg><script>bad</script></svg>',b'not a png',picture()[:30],b'x'*(MAX_IMAGE_BYTES+1)):
            with self.subTest(size=len(raw)),self.assertRaises(AppError):self.dis.upload(raw,self.owner)
        raw=BytesIO();Image.new('RGB',(2,2),'red').save(raw,format='PNG',save_all=True,append_images=[Image.new('RGB',(2,2),'blue')],duration=100,loop=0)
        with self.assertRaises(AppError):self.upload(raw=raw.getvalue())
        with self.assertRaises(AppError):self.upload(raw=picture(size=(4500,4500)))

    def test_image_ids_max_three_duplicates_and_missing(self):
        for ids in (['a'*32]*2,['a'*32,'b'*32,'c'*32,'d'*32],['../private']):
            with self.assertRaises(ValidationError):DiscoveryCreate.model_validate(self.payload(image_ids=ids))
        with self.assertRaises(AppError):self.create(image_ids=['a'*32])

    def test_staged_images_private_and_other_user_cannot_attach(self):
        image=self.upload(self.helper)
        with self.assertRaises(AppError):self.dis.image_path(image['id'])
        with self.assertRaises(AppError):self.create(image_ids=[image['id']])
        self.assertTrue(self.dis.image_path(image['id'],self.helper).is_file())

    def test_removed_images_private_but_versions_keep_original_ids(self):
        image=self.upload();d=self.create(image_ids=[image['id']]);updated=self.edit(d,image_ids=[])
        with self.assertRaises(AppError):self.dis.image_path(image['id'])
        self.assertTrue(self.dis.image_path(image['id'],self.owner).is_file())
        self.assertEqual(self.dis.versions(d['id'],self.owner)['items'][0]['before_fields']['image_ids'],[image['id']])
        self.assertEqual(self.edit(updated,image_ids=[image['id']])['image_ids'],[image['id']])

    def test_image_cannot_be_reused_for_another_post_or_comment(self):
        image=self.upload();d=self.create(image_ids=[image['id']])
        with self.assertRaises(AppError):self.create(image_ids=[image['id']])
        with self.assertRaises(AppError):self.dis.comment(d['id'],self.owner,DiscoveryCommentInput(content='重复使用',image_ids=[image['id']]))

    def test_staged_cleanup_after_24h_and_linked_history_preserved(self):
        staged=self.upload();attached=self.upload();d=self.create(image_ids=[attached['id']]);self.edit(d,image_ids=[])
        self.now+=timedelta(hours=24)
        with self.assertRaises(AppError):self.create(image_ids=[staged['id']])
        self.dis.cleanup_images()
        self.assertFalse((self.dis.media_dir/(staged['id']+'.jpg')).exists())
        self.assertTrue(self.dis.image_path(attached['id'],self.owner).exists())

    def test_http_image_cache_and_acl_after_withdraw(self):
        self.login();upload=self.client.post('/api/discovery-images',files={'file':('sample.png',picture(),'image/png')})
        self.assertEqual(upload.status_code,201,upload.text);image=upload.json();d=self.create(image_ids=[image['id']])
        self.client.cookies.clear();r=self.client.get(image['url']);self.assertEqual(r.status_code,200);self.assertEqual(r.headers['content-type'],'image/jpeg');self.assertEqual(r.headers['cache-control'],'no-store')
        self.withdraw(d);self.assertEqual(self.client.get(image['url']).status_code,404)
        self.login();self.assertEqual(self.client.get(image['url']).status_code,200)

    def test_oversize_upload_rejected_before_processing(self):
        self.login()
        self.assertEqual(self.client.post('/api/discovery-images',files={'file':('huge.png',b'x'*(MAX_IMAGE_BYTES+1),'image/png')}).status_code,413)
        boundary='test-boundary'
        def chunks():
            yield f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="big.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
            for _ in range(6):yield b'x'*(1024*1024)
            yield f'\r\n--{boundary}--\r\n'.encode()
        self.assertEqual(self.client.post('/api/discovery-images',content=chunks(),headers={'Content-Type':'multipart/form-data; boundary='+boundary}).status_code,413)

    def test_history_and_images_survive_database_reinitialization(self):
        image=self.upload();d=self.create(image_ids=[image['id']]);self.state(d)
        self.dis.database.initialize();self.dis.cleanup_images()
        self.assertEqual(self.dis.detail(d['id'])['version'],2);self.assertTrue(self.dis.image_path(image['id']).exists())
        self.assertEqual(self.client.get('/api/tasks').json()['total'],0)
        self.assertEqual(self.client.get('/api/activities').json()['total'],0)
        self.assertEqual(self.client.get('/api/volunteers').json()['total'],0)
