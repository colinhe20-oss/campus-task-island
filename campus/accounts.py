"""Self-service account registration lifecycle support and host-local password reset CLI."""
from __future__ import annotations

import argparse
import getpass
import hmac
import re
from datetime import datetime, timezone
from urllib.parse import quote

from .auth import AuthService, password_hash
from .db import Database, configured_db_path
from .errors import AppError


class AccountService:
    def __init__(self, database: Database, auth: AuthService, discoveries):
        self.database = database
        self.auth = auth
        self.discoveries = discoveries

    @staticmethod
    def _href(kind: str, identifier: str) -> str:
        escaped = quote(identifier, safe='')
        return {
            'task': f'#/tasks/{escaped}',
            'activity': f'#/activities/{escaped}',
            'volunteer': f'#/volunteers/{escaped}',
            'guide': '#/guide',
        }[kind]

    @classmethod
    def _blockers(cls, connection, user_id: str, now: str) -> list[dict[str, str]]:
        blockers: list[dict[str, str]] = []

        for row in connection.execute('''SELECT id,title FROM tasks
            WHERE (publisher_id=? OR assignee_id=?) AND status IN ('published','in_progress','pending_review','paused')
            AND is_listed=1 ORDER BY created_at,id''', (user_id, user_id)):
            blockers.append(dict(kind='task', title=f'请先结束或协商取消普通任务：{row["title"]}',
                                 href=cls._href('task', row['id'])))

        for row in connection.execute('''SELECT DISTINCT t.id,t.title FROM applications a
            JOIN tasks t ON t.id=a.task_id WHERE a.applicant_id=? AND a.status='pending'
            AND t.status='published' AND t.is_listed=1 ORDER BY t.created_at,t.id''', (user_id,)):
            blockers.append(dict(kind='application', title=f'请先撤回或处理中的接取申请：{row["title"]}',
                                 href=cls._href('task', row['id'])))

        for row in connection.execute('''SELECT id,title FROM activities WHERE owner_id=?
            AND cancelled_at IS NULL AND ends_at>? ORDER BY starts_at,id''', (user_id, now)):
            blockers.append(dict(kind='activity', title=f'请先完成或取消你负责的综素活动：{row["title"]}',
                                 href=cls._href('activity', row['id'])))

        for row in connection.execute('''SELECT DISTINCT a.id,a.title FROM activities a
            JOIN activity_registrations r ON r.activity_id=a.id WHERE r.user_id=?
            AND r.status IN ('pending','registered','waitlisted') AND a.starts_at>? ORDER BY a.starts_at,a.id''',
            (user_id, now)):
            blockers.append(dict(kind='activity_registration', title=f'请先取消或完成有效综素报名：{row["title"]}',
                                 href=cls._href('activity', row['id'])))

        volunteer_owner_rows = connection.execute('''SELECT DISTINCT a.id,a.title FROM volunteer_activities a
            WHERE a.owner_id=? AND a.cancelled_at IS NULL AND a.ends_at>?
            UNION
            SELECT DISTINCT a.id,a.title FROM volunteer_activities a
            JOIN volunteer_registrations r ON r.activity_id=a.id
            JOIN volunteer_jobs j ON j.id=r.job_id
            LEFT JOIN volunteer_participation p ON p.registration_id=r.id
            WHERE a.owner_id=? AND r.status IN ('registered','activity_cancelled') AND j.starts_at<=?
            AND (p.registration_id IS NULL OR p.confirmed_minutes IS NULL)
            ORDER BY title''', (user_id, now, user_id, now)).fetchall()
        for row in volunteer_owner_rows:
            blockers.append(dict(kind='volunteer_owner', title=f'请先完成志愿活动管理或小时核验：{row["title"]}',
                                 href=cls._href('volunteer', row['id'])))

        for row in connection.execute('''SELECT DISTINCT a.id,a.title FROM volunteer_activities a
            JOIN volunteer_registrations r ON r.activity_id=a.id
            JOIN volunteer_jobs j ON j.id=r.job_id WHERE r.user_id=?
            AND r.status IN ('pending','registered','waitlisted') AND j.ends_at>? ORDER BY j.starts_at,a.id''',
            (user_id, now)):
            blockers.append(dict(kind='volunteer_registration', title=f'请先取消或完成有效志愿岗位报名：{row["title"]}',
                                 href=cls._href('volunteer', row['id'])))

        for row in connection.execute("SELECT id FROM guide_runs WHERE user_id=? AND status IN ('running','cancelling')", (user_id,)):
            blockers.append(dict(kind='guide_run', title='请先等待或取消正在运行的引航员任务',
                                 href=cls._href('guide', row['id'])))
        return blockers

    def read(self, user_id: str) -> dict:
        with self.database.connect() as connection:
            connection.execute('BEGIN')
            user = connection.execute("SELECT username,display_name,account_status FROM users WHERE id=?", (user_id,)).fetchone()
            if user is None or user['account_status'] != 'active':
                raise AppError('账号不存在或已注销', 401)
            now = datetime.now(timezone.utc).isoformat()
            blockers = self._blockers(connection, user_id, now)
            return dict(username=user['username'], display_name=user['display_name'], account_status=user['account_status'],
                        can_close=not blockers, blockers=blockers)

    def close(self, user_id: str, password: str) -> dict:
        stamp = datetime.now(timezone.utc).isoformat()
        temp_image_ids: list[str] = []
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            user = connection.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if user is None or user['account_status'] != 'active':
                raise AppError('账号不存在或已经注销', 401)
            digest = password_hash(password, user['salt'])
            if not hmac.compare_digest(digest, user['password_hash']):
                raise AppError('当前密码不正确', 403)
            blockers = self._blockers(connection, user_id, stamp)
            if blockers:
                raise AppError('账号仍有关联业务未完成，请刷新页面查看清单后再注销', 409)

            temp_image_ids = [row['id'] for row in connection.execute('''SELECT id FROM discovery_images
                WHERE uploader_id=? AND attached_discovery_id IS NULL AND attached_comment_id IS NULL''', (user_id,))]
            connection.execute('''UPDATE users SET account_status='closed',closed_at=?,display_name='已注销用户'
                WHERE id=?''', (stamp, user_id))
            connection.execute('UPDATE activity_permissions SET can_publish=0 WHERE user_id=?', (user_id,))
            connection.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            connection.execute('DELETE FROM notifications WHERE recipient_id=?', (user_id,))
            connection.execute("UPDATE guide_conversations SET history='[]',updated_at=? WHERE user_id=?", (stamp, user_id))
            connection.execute("UPDATE guide_task_drafts SET fields='{}',status=CASE WHEN status='draft' THEN 'cancelled' ELSE status END,updated_at=? WHERE user_id=?", (stamp, user_id))
            connection.execute("UPDATE stage_suggestions SET fields='{}' WHERE user_id=?", (user_id,))
            connection.execute("UPDATE guide_runs SET events='[]',result=NULL,error=NULL WHERE user_id=?", (user_id,))
            connection.execute('''DELETE FROM discovery_images WHERE uploader_id=?
                AND attached_discovery_id IS NULL AND attached_comment_id IS NULL''', (user_id,))
        for image_id in temp_image_ids:
            try:
                (self.discoveries.media_dir / f'{image_id}.jpg').unlink(missing_ok=True)
            except OSError:
                # A later normal image cleanup can remove an orphaned temporary file.
                pass
        return dict(closed=True, closed_at=stamp)


def _reset_password_cli(username: str) -> int:
    first = getpass.getpass('输入新密码（12–128 个字符）：')
    second = getpass.getpass('再次输入新密码：')
    if first != second:
        print('两次输入不一致。')
        return 2
    if not 12 <= len(first) <= 128 or not first.strip():
        print('密码需为 12–128 个字符，且不能全为空白。')
        return 2
    try:
        auth = AuthService(Database(configured_db_path()))
        auth.reset_password(username.strip().lower(), first)
    except AppError as exc:
        print(str(exc))
        return 1
    print('密码已更新；该账号原有会话已全部退出。')
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description='校园任务岛主机端账号维护')
    subparsers = parser.add_subparsers(dest='command', required=True)
    reset = subparsers.add_parser('reset-password', help='重置一个有效账号的密码')
    reset.add_argument('username', help='账号名')
    args = parser.parse_args()
    raise SystemExit(_reset_password_cli(args.username))


if __name__ == '__main__':
    main()
