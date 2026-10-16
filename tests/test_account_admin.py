"""Host administrator checks and destructive maintenance use temporary databases only."""
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from campus.account_admin import HostAccountAdmin, require_host_admin
from campus.accounts import main
from campus.auth import AuthService
from campus.db import Database
from campus.errors import AppError


class HostAccountAdminTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / '含 空格 #账号.sqlite3'
        self.database = Database(self.path)
        self.database.initialize()
        self.auth = AuthService(self.database)
        self.token, self.user = self.auth.register('test.user', '测试同学', 'test-password')
        self.other_token, self.other = self.auth.register('other.user', '另一同学', 'other-password')
        self.admin = HostAccountAdmin(self.path)
        self.admin_check = self.enterContext(patch('campus.account_admin.require_host_admin'))

    def snapshot(self):
        with self.database.connect() as connection:
            return '\n'.join(connection.iterdump())

    def test_all_operations_require_admin_before_opening_database(self):
        self.admin_check.side_effect = AppError('管理员权限不足', 403)
        missing = Path(self.path.parent) / 'does-not-exist.sqlite3'
        service = HostAccountAdmin(missing)
        for operation in (service.list_users, lambda: service.inspect('test.user'),
                          lambda: service.delete('test.user', self.user.id)):
            with self.subTest(operation=operation), self.assertRaises(AppError) as caught:
                operation()
            self.assertEqual(caught.exception.status_code, 403)
        self.assertFalse(missing.exists())

    def test_read_only_list_and_preview_contain_no_credentials_and_change_nothing(self):
        before = self.snapshot()
        accounts = self.admin.list_users()
        self.assertEqual(set(accounts[0]), {'id', 'username', 'display_name', 'account_status'})
        report = self.admin.inspect(' TEST.USER ')
        self.assertTrue(report['can_delete'])
        self.assertEqual(report['cleanup'], [{'table': 'sessions', 'column': 'user_id', 'count': 1}])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list(self.path.parent.glob('*.account-backups')))

    def test_wrong_path_or_incompatible_database_is_never_created_or_migrated(self):
        missing = self.path.parent / 'missing.sqlite3'
        with self.assertRaisesRegex(AppError, '数据库不存在'):
            HostAccountAdmin(missing).list_users()
        self.assertFalse(missing.exists())
        wrong = self.path.parent / 'wrong.sqlite3'
        with closing(sqlite3.connect(wrong)) as connection:
            connection.execute('CREATE TABLE unrelated (value TEXT)')
        with self.assertRaisesRegex(AppError, '不.*兼容'):
            HostAccountAdmin(wrong).list_users()
        with closing(sqlite3.connect(wrong)) as connection:
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('unrelated',)])

    def test_delete_revokes_sessions_removes_legacy_grants_and_has_complete_backup(self):
        with self.database.connect() as connection:
            connection.execute('INSERT INTO activity_permissions VALUES (?,1)', (self.user.id,))
        before = self.snapshot()
        result = self.admin.delete('test.user', self.user.id)
        self.assertEqual(result['id'], self.user.id)
        backup = Path(result['backup'])
        self.assertTrue(backup.is_file())
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual('\n'.join(connection.iterdump()), before)
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        with self.database.connect() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM users WHERE id=?', (self.user.id,)).fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM activity_permissions WHERE user_id=?', (self.user.id,)).fetchone()[0], 0)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
        with self.assertRaises(AppError):
            self.auth.current_user(self.token)
        self.assertEqual(self.auth.current_user(self.other_token).id, self.other.id)
        # Physical deletion deliberately allows later reuse of an ordinary username.
        _, replacement = self.auth.register('test.user', '新账号', 'replacement-password')
        self.assertNotEqual(replacement.id, self.user.id)
        with self.assertRaisesRegex(AppError, '确认 ID'):
            self.admin.delete('test.user', self.user.id)

    def test_missing_or_wrong_confirmation_does_not_delete_or_backup(self):
        before = self.snapshot()
        for confirmation in ('', 'test.user', self.other.id):
            with self.assertRaisesRegex(AppError, '确认 ID'):
                self.admin.delete('test.user', confirmation)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list(self.path.parent.glob('*.account-backups')))

    def test_builtin_demo_accounts_are_protected_even_when_unused(self):
        self.auth.provision_demo_accounts()
        for name in ('publisher', 'helper', 'observer'):
            report = self.admin.inspect(name)
            self.assertFalse(report['can_delete'])
            self.assertIn('演示账号', report['protected_reason'])
            with self.assertRaisesRegex(AppError, '演示账号'):
                self.admin.delete(name, report['id'])

    def test_business_history_blocks_deletion_and_is_rechecked_after_preview(self):
        self.assertTrue(self.admin.inspect('test.user')['can_delete'])
        with self.database.connect() as connection:
            connection.execute('''INSERT INTO tasks
                (id,title,category,description,completion_criteria,status,created_at,publisher_id)
                VALUES ('old-task','已取消测试','daily','说明','要求','cancelled','2026-10-16',?)''', (self.user.id,))
        before = self.snapshot()
        report = self.admin.inspect('test.user')
        self.assertFalse(report['can_delete'])
        self.assertIn({'table': 'tasks', 'column': 'publisher_id', 'count': 1}, report['blockers'])
        with self.assertRaisesRegex(AppError, 'tasks.publisher_id=1'):
            self.admin.delete('test.user', self.user.id)
        self.assertEqual(self.snapshot(), before)

    def test_private_guide_history_and_future_cascading_references_block_deletion(self):
        with self.database.connect() as connection:
            connection.execute("INSERT INTO guide_conversations VALUES ('conversation',?,'[]','2026-10-16')", (self.user.id,))
            connection.execute('CREATE TABLE future_history (actor TEXT REFERENCES users(id) ON DELETE CASCADE)')
            connection.execute('INSERT INTO future_history VALUES (?)', (self.user.id,))
        before = self.snapshot()
        report = self.admin.inspect('test.user')
        self.assertEqual({item['table'] for item in report['blockers']}, {'guide_conversations', 'future_history'})
        with self.assertRaises(AppError):
            self.admin.delete('test.user', self.user.id)
        self.assertEqual(self.snapshot(), before)

    def test_backup_failure_leaves_account_and_sessions_intact(self):
        before = self.snapshot()
        with patch.object(self.admin, '_backup', side_effect=OSError('备份目录不可写')):
            with self.assertRaises(OSError):
                self.admin.delete('test.user', self.user.id)
        self.assertEqual(self.snapshot(), before)

    def test_transaction_failure_after_backup_rolls_back_cleanup(self):
        with self.database.connect() as connection:
            connection.execute("""CREATE TRIGGER prevent_delete BEFORE DELETE ON users
                BEGIN SELECT RAISE(ABORT, 'test rollback'); END""")
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            self.admin.delete('test.user', self.user.id)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.auth.current_user(self.token).id, self.user.id)

    def test_cli_delete_without_confirmation_only_previews(self):
        before = self.snapshot()
        output = io.StringIO()
        with patch('sys.argv', ['accounts', '--db', str(self.path), 'delete', 'test.user']), \
                patch('campus.accounts.require_host_admin'), redirect_stdout(output):
            main()
        self.assertIn('仅预览，未删除', output.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_password_reset_cli_checks_privileges_before_prompt(self):
        with patch('sys.argv', ['accounts', 'reset-password', 'test.user']), \
                patch('campus.accounts.require_host_admin', side_effect=AppError('需要管理员', 403)), \
                patch('campus.accounts.getpass.getpass') as prompt, redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main()
        self.assertEqual(caught.exception.code, 1)
        prompt.assert_not_called()


class OperatingSystemAdminTests(unittest.TestCase):
    def test_windows_requires_elevation(self):
        with patch('campus.account_admin.os.name', 'nt'), \
                patch('campus.account_admin.ctypes.windll', create=True) as windll:
            windll.shell32.IsUserAnAdmin.return_value = 0
            with self.assertRaises(AppError):
                require_host_admin()
            windll.shell32.IsUserAnAdmin.return_value = 1
            require_host_admin()

    def test_unix_requires_root_and_fails_closed_without_supported_api(self):
        with patch('campus.account_admin.os.name', 'posix'), \
                patch('campus.account_admin.os.geteuid', create=True, return_value=1000) as geteuid:
            with self.assertRaises(AppError):
                require_host_admin()
            geteuid.return_value = 0
            require_host_admin()
            geteuid.side_effect = OSError('unsupported')
            with self.assertRaises(AppError):
                require_host_admin()


if __name__ == '__main__':
    unittest.main()
