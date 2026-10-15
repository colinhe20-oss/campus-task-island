"""真实模型内容类型区分验收：使用临时数据库与合成输入，会调用配置的模型。"""
import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from campus.app import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='.runtime/evals/content-type-real-latest.json')
    args = parser.parse_args()
    cases = [
        ('discovery_publish', '我想发布校园发现：东区图书馆门口的路灯不亮，昨晚本人观察到，希望发图文提醒大家，再请同学评论补充。帮我发布。'),
        ('discovery_search', '帮我查校园发现里图书馆路灯是不是已经核实修好了，也帮我在下面评论说已经处理完成。'),
        ('activity_publish', '我想发布一个综素活动：美育工作坊，给同学报名参加，限额30人，有美育分认定说明。请帮我发布。'),
        ('activity_search', '帮我查一下能获得二课分的综素活动，还有没有报名名额？'),
        ('ambiguous', '我想发布一个活动，帮我整理一下。'),
        ('volunteer_publish', '我作为公益社团负责人，想发布志愿服务活动，招募上午整理岗和下午引导岗，按实际参与核验志愿小时，帮我发布。'),
        ('volunteer_search', '帮我查一下志愿服务有没有岗位名额，再看看我已经确认了多少正式志愿小时。'),
        ('ordinary_event_help', '我要发布普通协作任务，找一位同学帮社团拍活动照片，标题社团活动摄影，分类创作协作。需求是拍活动现场，完成标准交付10张清晰照片，地点学生活动中心，截止时间2030年10月20日北京时间18点，回报互助。'),
    ]
    results = []
    with tempfile.TemporaryDirectory(prefix='guide-content-types-') as temp:
        app = create_app(Path(temp)/'campus.sqlite3')
        with TestClient(app) as client:
            auth = app.state.auth_service
            accounts = json.loads(auth.accounts_path.read_text(encoding='utf-8'))
            token, _ = auth.login('publisher', accounts['publisher']['password'])
            client.cookies.set('campus_session', token)
            for name, message in cases:
                response = client.post('/api/guide/chat', json={'message': message})
                data = response.json()
                checks = {'http_ok': response.status_code == 200}
                if response.status_code == 200:
                    used = {tool['name'] for tool in data['tools_used']}
                    checks['real_model'] = data['mode'] == 'model'
                    if name != 'ordinary_event_help':
                        checks['no_ordinary_draft'] = data['draft'] is None
                        checks['no_ordinary_tools'] = not used.intersection({'search_tasks','get_my_tasks','get_task_detail','update_task_draft'})
                        checks['distinction_explained'] = ('校园发现' if name.startswith('discovery') else '志愿' if name.startswith('volunteer') else '综素') in data['answer']
                        if name in ('activity_publish','volunteer_publish','discovery_publish'):
                            checks['unified_publish_entry'] = '发布任务' in data['answer']
                    else:
                        checks['ordinary_draft_updated'] = 'update_task_draft' in used and data['draft'] is not None and data['draft']['ready']
                        if data['draft']:
                            checks['ordinary_category'] = data['draft']['fields']['category'] == 'creative'
                    with app.state.task_service.database.connect() as conn:
                        checks['no_publishing_without_confirmation'] = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0 and conn.execute('SELECT COUNT(*) FROM activities').fetchone()[0] == 0 and conn.execute('SELECT COUNT(*) FROM discoveries').fetchone()[0] == 0
                result = {'scenario': name, 'passed': all(checks.values()), 'checks': checks,
                          'answer': data.get('answer'), 'tools_used': data.get('tools_used'), 'error': data.get('detail')}
                results.append(result)
                print(json.dumps({'scenario':name, 'passed':result['passed'], 'checks':checks}, ensure_ascii=False), flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'checked_at':datetime.now(timezone(timedelta(hours=8))).isoformat(), 'passed':all(r['passed'] for r in results), 'scenarios':results},ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in results):
        raise SystemExit('内容类型验收失败，见报告；正式数据库未使用。')


if __name__ == '__main__':
    main()
