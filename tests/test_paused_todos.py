"""R5: paused collaboration requests distinguish waiting from actionable work."""
import json
import unittest

import test_terms as base
from campus.schemas import StagePlanInput
from campus.todos import personal_state
from tools.campus import build_campus_registry


class PausedTodoTests(unittest.TestCase):
    setUp = base.TermsTests.setUp
    login = base.TermsTests.login
    create = base.TermsTests.create
    join = base.TermsTests.join
    stamp = base.TermsTests.stamp

    @staticmethod
    def other(name):
        return 'helper' if name == 'publisher' else 'publisher'

    def propose(self, task_id, kind, name='publisher', **extra):
        self.login(name)
        task = self.service.get_task(task_id)
        body = dict(version=task.terms_version, reason='双方协商调整')
        if kind == 'agreement':
            endpoint = 'changes'
            body['changes'] = {'description': '暂停期间重新约定的工作范围'}
        else:
            endpoint = 'collaboration-requests'
            body.update(action=kind, collaboration_version=task.collaboration_version, extend_deadline=False)
        response = self.client.post(f'/api/tasks/{task_id}/{endpoint}', json=body | extra)
        self.assertEqual(response.status_code, 200, response.text)
        pending = [item for item in response.json()['items'] if item['status'] == 'pending']
        self.assertEqual(len(pending), 1)
        return pending[0]

    def resolve(self, request, name, decision='approve'):
        self.login(name)
        endpoint = 'cancel' if decision == 'cancel' else 'review'
        body = {'version': request['version']}
        if endpoint == 'review':
            body.update(decision=decision, reason='双方确认处理结果')
        response = self.client.post(f"/api/task-changes/{request['id']}/{endpoint}", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return next(item for item in response.json()['items'] if item['id'] == request['id'])

    def paused(self, *, paid=False, submitted=False, staged=False):
        task_id = self.create(paid=paid)
        if staged:
            self.app.state.stage_service.set_plan(task_id, self.users['publisher'], StagePlanInput(
                expected_version=0, stages=[dict(title='第一阶段', completion_criteria='完成初稿',
                    deadline=self.stamp(.5), responsible_role='assignee')]))
        self.join(task_id)
        if submitted:
            self.login('helper')
            response = self.client.post(f'/api/tasks/{task_id}/submissions',
                                        json={'summary': '待验收成果', 'collaboration_version': 1})
            self.assertEqual(response.status_code, 201, response.text)
        request = self.propose(task_id, 'pause')
        self.resolve(request, 'helper')
        self.assertEqual(self.service.get_task(task_id).status, 'paused')
        return task_id

    def assert_views(self, task_id, name, todos, waiting):
        user_id = self.users[name]
        actions = lambda items, key: sorted(item['action'] for item in items if item[key] == task_id)
        state = personal_state(self.service, user_id)
        self.assertEqual(sorted(item.action for item in state.todos if item.task_id == task_id), sorted(todos))
        self.assertEqual(sorted(item.action for item in state.waiting if item.task_id == task_id), sorted(waiting))

        self.login(name)
        response = self.client.get('/api/guide/todos')
        self.assertEqual(response.status_code, 200, response.text)
        personal = response.json()
        self.assertEqual(actions(personal['todos'], 'task_id'), sorted(todos))
        self.assertEqual(actions(personal['waiting'], 'task_id'), sorted(waiting))
        response = self.client.get('/api/me/home')
        self.assertEqual(response.status_code, 200, response.text)
        home = response.json()
        self.assertEqual(actions(home['todos'], 'resource_id'), sorted(todos))
        self.assertEqual(home['todo_count'], len(state.todos))

        registry = build_campus_registry(self.service, user_id, activities=self.app.state.activity_service,
            volunteers=self.app.state.volunteer_service, home=self.app.state.home_service)
        tasks = json.loads(registry.get('get_my_tasks').invoke({}))
        self.assertEqual(actions(tasks['todos'], 'task_id'), sorted(todos))
        self.assertEqual(actions(tasks['waiting'], 'task_id'), sorted(waiting))
        self.assertEqual(tasks['totals']['todos'], len(state.todos))
        self.assertEqual(tasks['totals']['waiting'], len(state.waiting))
        overview = json.loads(registry.get('get_my_overview').invoke({}))
        self.assertEqual(actions(overview['todos'], 'resource_id'), sorted(todos))
        self.assertEqual(actions(overview['waiting'], 'resource_id'), sorted(waiting))
        self.assertEqual(overview['todo_count'], len(state.todos))
        self.assertEqual(overview['waiting_count'], len(state.waiting))
        for item in personal['todos'] + personal['waiting']:
            if item['task_id'] == task_id:
                self.assertEqual(item['href'], '#/tasks/' + task_id)

    def test_paused_task_requester_is_waiting_rather_than_actionable(self):
        task_id = self.paused()
        for name in ('publisher', 'helper'):
            for kind in ('resume', 'cancel', 'agreement'):
                with self.subTest(requester=name, kind=kind):
                    request = self.propose(task_id, kind, name)
                    try:
                        self.assert_views(task_id, name, [], ['wait_for_change'])
                        self.assert_views(task_id, self.other(name), ['review_change'], [])
                        self.assert_views(task_id, 'observer', [], [])
                    finally:
                        self.resolve(request, name, decision='cancel')

    def test_rejected_or_withdrawn_requests_leave_no_pending_work_while_paused(self):
        task_id = self.paused()
        for name in ('publisher', 'helper'):
            for kind in ('resume', 'cancel', 'agreement'):
                for decision in ('reject', 'cancel'):
                    with self.subTest(requester=name, kind=kind, decision=decision):
                        request = self.propose(task_id, kind, name)
                        result = self.resolve(request, name if decision == 'cancel' else self.other(name), decision)
                        self.assertEqual(result['status'], 'cancelled' if decision == 'cancel' else 'rejected')
                        self.assertEqual(self.service.get_task(task_id).status, 'paused')
                        for party in ('publisher', 'helper'):
                            self.assert_views(task_id, party, [], [])

    def test_resume_approval_restores_work_for_original_execution_state(self):
        for submitted in (False, True):
            with self.subTest(submitted=submitted):
                task_id = self.paused(submitted=submitted)
                request = self.propose(task_id, 'resume', 'helper')
                self.resolve(request, 'publisher')
                self.assertEqual(self.service.get_task(task_id).status, 'pending_review' if submitted else 'in_progress')
                self.assert_views(task_id, 'publisher', ['review_results'] if submitted else [],
                                  [] if submitted else ['wait_for_submission'])
                self.assert_views(task_id, 'helper', [] if submitted else ['submit_results'],
                                  ['wait_for_review'] if submitted else [])

    def test_paused_stage_stays_frozen_and_reappears_only_after_resume(self):
        task_id = self.paused(staged=True)
        request = self.propose(task_id, 'resume')
        self.assert_views(task_id, 'publisher', [], ['wait_for_change'])
        self.assert_views(task_id, 'helper', ['review_change'], [])
        self.login('helper')
        stage = self.client.get(f'/api/tasks/{task_id}/stages').json()['stages'][0]
        blocked = self.client.post(f"/api/tasks/{task_id}/stages/{stage['id']}/start", json={'version': stage['version']})
        self.assertEqual(blocked.status_code, 409)
        self.resolve(request, 'helper')
        self.assert_views(task_id, 'publisher', [], ['wait_for_stage_submission'])
        self.assert_views(task_id, 'helper', ['start_stage'], [])

    def test_paid_cancellation_replaces_request_with_settlement_work(self):
        task_id = self.paused(paid=True)
        request = self.propose(task_id, 'cancel', 'helper', cancellation_settlement_fen=500)
        self.resolve(request, 'publisher')
        for name in ('publisher', 'helper'):
            self.assert_views(task_id, name, ['confirm_settlement'], [])
        self.login('publisher')
        settlement = self.client.get(f'/api/tasks/{task_id}/settlement').json()
        response = self.client.post(f'/api/tasks/{task_id}/settlement/confirmation',
                                   json={'version': settlement['version'], 'confirmed': True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_views(task_id, 'publisher', [], ['wait_for_settlement'])
        self.assert_views(task_id, 'helper', ['confirm_settlement'], [])

    def test_zero_cancellation_clears_request_without_creating_settlement_work(self):
        task_id = self.paused(paid=True)
        request = self.propose(task_id, 'cancel', cancellation_settlement_fen=0)
        self.resolve(request, 'helper')
        self.assertEqual(self.service.get_task(task_id).status, 'cancelled')
        for name in ('publisher', 'helper'):
            self.assert_views(task_id, name, [], [])

    def test_agreement_approval_clears_request_but_keeps_execution_paused(self):
        task_id = self.paused()
        request = self.propose(task_id, 'agreement', 'helper')
        self.resolve(request, 'publisher')
        task = self.service.get_task(task_id)
        self.assertEqual(task.status, 'paused')
        self.assertEqual(task.description, '暂停期间重新约定的工作范围')
        for name in ('publisher', 'helper'):
            self.assert_views(task_id, name, [], [])

    def test_unpaused_requests_keep_existing_classification_and_execution_work(self):
        task_id = self.create()
        self.join(task_id)
        self.propose(task_id, 'pause')
        self.assert_views(task_id, 'publisher', [], ['wait_for_change', 'wait_for_submission'])
        self.assert_views(task_id, 'helper', ['review_change', 'submit_results'], [])


if __name__ == '__main__':
    unittest.main()
