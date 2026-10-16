"""Account information and the host-local administrator CLI."""
from __future__ import annotations

import argparse
import getpass
import json
import sqlite3

from .account_admin import HostAccountAdmin, require_host_admin
from .auth import AuthService
from .db import Database, configured_db_path
from .errors import AppError


class AccountService:
    """Read account information without changing account or business records."""
    def __init__(self, database: Database):
        self.database = database

    def read(self, user_id: str) -> dict:
        with self.database.connect() as connection:
            user = connection.execute(
                "SELECT id,username,display_name FROM users WHERE id=? AND account_status='active'",
                (user_id,),
            ).fetchone()
        if user is None:
            raise AppError('有效账号不存在', 401)
        return dict(user)


def _reset_password_cli(username: str, db_path=None) -> int:
    require_host_admin()
    admin = HostAccountAdmin(db_path or configured_db_path())
    admin.inspect(username)  # Validate the existing database and target before prompting.
    first = getpass.getpass('输入新密码（12–128 个字符）：')
    second = getpass.getpass('再次输入新密码：')
    if first != second:
        print('两次输入不一致。')
        return 2
    if not 12 <= len(first) <= 128 or not first.strip():
        print('密码需为 12–128 个字符，且不能全为空白。')
        return 2
    try:
        auth = AuthService(Database(admin.path))
        auth.reset_password(username.strip().lower(), first)
    except AppError as exc:
        print(str(exc))
        return 1
    print('密码已更新；该账号原有会话已全部退出。')
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description='校园任务岛主机端账号维护')
    parser.add_argument('--db', help='数据库路径；默认使用 CAMPUS_DB_PATH 或项目内默认路径')
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('list', help='列出账号（不包含密码或会话凭证）')
    inspect = subparsers.add_parser('inspect', help='只读检查指定账号能否删除')
    inspect.add_argument('username', help='账号名')
    delete = subparsers.add_parser('delete', help='预览删除；提供确认 ID 才会执行')
    delete.add_argument('username', help='账号名')
    delete.add_argument('--confirm', metavar='ACCOUNT_ID', help='inspect 输出的完整账号 ID')
    reset = subparsers.add_parser('reset-password', help='重置一个有效账号的密码')
    reset.add_argument('username', help='账号名')
    args = parser.parse_args()
    try:
        require_host_admin()
        admin = HostAccountAdmin(args.db or configured_db_path())
        print(f'数据库：{admin.path}')
        if args.command == 'reset-password':
            raise SystemExit(_reset_password_cli(args.username, admin.path))
        if args.command == 'list':
            result = admin.list_users()
        elif args.command == 'inspect' or args.confirm is None:
            result = admin.inspect(args.username)
            if args.command == 'delete':
                print('仅预览，未删除。确认后使用 --confirm 加上本次显示的完整账号 ID。')
        else:
            result = admin.delete(args.username, args.confirm)
            print('账号已永久删除，原有会话已失效。数据库备份：')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (AppError, sqlite3.Error, OSError) as exc:
        print(f'操作失败：{exc}')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
