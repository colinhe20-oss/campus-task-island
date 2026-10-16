"""Host-only maintenance for unused accounts; deliberately not registered with FastAPI."""
from __future__ import annotations

import ctypes
import os
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .auth import DEMO_USERS
from .errors import AppError


def require_host_admin() -> None:
    """Require an elevated Windows process or Unix root, failing closed elsewhere."""
    try:
        if os.name == 'nt':
            allowed = bool(ctypes.windll.shell32.IsUserAnAdmin())
        else:
            allowed = hasattr(os, 'geteuid') and os.geteuid() == 0
    except (AttributeError, OSError):
        allowed = False
    if not allowed:
        raise AppError('仅服务主机管理员可用：Windows 请以管理员身份打开终端；Linux 请使用 root。', 403)


def _identifier(name: str) -> str:
    # Identifiers originate from SQLite metadata, but still need SQL quoting.
    return '"' + name.replace('"', '""') + '"'


class HostAccountAdmin:
    """Delete only accounts whose sole dependants are sessions and legacy grants."""

    _REMOVABLE = {('sessions', 'user_id'), ('activity_permissions', 'user_id')}

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path).expanduser().resolve()

    @contextmanager
    def _connect(self, *, write: bool = False):
        require_host_admin()
        # mode=rw/ro prevents a typo from creating an empty database. Never migrate here.
        if not self.path.is_file():
            raise AppError(f'数据库不存在：{self.path}', 404)
        mode = 'rw' if write else 'ro'
        with closing(sqlite3.connect(f'{self.path.as_uri()}?mode={mode}', uri=True, timeout=10)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(users)')}
            if not {'id', 'username', 'display_name', 'account_status'} <= columns:
                raise AppError('数据库不是兼容的校园任务岛账号库，请先核对路径和应用版本。')
            with connection:
                yield connection

    def list_users(self) -> list[dict]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                'SELECT id,username,display_name,account_status FROM users ORDER BY username'
            )]

    def _inspect(self, connection: sqlite3.Connection, username: str) -> dict:
        row = connection.execute(
            'SELECT id,username,display_name,account_status FROM users WHERE username=?',
            (username.strip().lower(),),
        ).fetchone()
        if row is None:
            raise AppError('账号不存在', 404)
        blockers, cleanup = [], []
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for table in tables:
            table_name = table['name']
            for foreign_key in connection.execute(f'PRAGMA foreign_key_list({_identifier(table_name)})'):
                if foreign_key['table'].lower() != 'users':
                    continue
                # The current schema uses simple references to users(id). Unknown
                # future composite/non-id references must not silently be skipped.
                if foreign_key['seq'] != 0 or foreign_key['to'] not in ('id', None):
                    raise AppError(f'存在不支持的账号外键：{table_name}，请先更新管理工具。')
                column = foreign_key['from']
                count = connection.execute(
                    f'SELECT COUNT(*) FROM {_identifier(table_name)} WHERE {_identifier(column)}=?',
                    (row['id'],),
                ).fetchone()[0]
                if count:
                    target = cleanup if (table_name, column) in self._REMOVABLE else blockers
                    target.append({'table': table_name, 'column': column, 'count': count})
        protected = '内置演示账号由启动流程补建，当前不允许删除。' if row['username'] in DEMO_USERS else None
        return dict(row) | {
            'can_delete': not protected and not blockers,
            'protected_reason': protected,
            'blockers': blockers,
            'cleanup': cleanup,
        }

    def inspect(self, username: str) -> dict:
        with self._connect() as connection:
            connection.execute('BEGIN')
            return self._inspect(connection, username)

    def _backup(self) -> Path:
        directory = self.path.parent / f'{self.path.stem}.account-backups'
        directory.mkdir(mode=0o700, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        descriptor, name = tempfile.mkstemp(prefix=f'before-delete-{stamp}-', suffix='.sqlite3', dir=directory)
        os.close(descriptor)
        destination = Path(name)
        try:
            # A separate reader backs up the committed state while our writer holds
            # BEGIN IMMEDIATE. Backing up the writer itself would wait on its own txn.
            with closing(sqlite3.connect(f'{self.path.as_uri()}?mode=ro', uri=True, timeout=10)) as source:
                with closing(sqlite3.connect(destination)) as target:
                    source.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise AppError('备份完整性检查失败，账号未删除。')
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return destination

    def delete(self, username: str, confirmation_id: str) -> dict:
        with self._connect(write=True) as connection:
            # Serialize registration/business writes with the final dependency check.
            connection.execute('BEGIN IMMEDIATE')
            report = self._inspect(connection, username)
            if confirmation_id != report['id']:
                raise AppError('确认 ID 与当前账号不一致，请重新检查账号；未删除。')
            if not report['can_delete']:
                details = ', '.join(f"{item['table']}.{item['column']}={item['count']}" for item in report['blockers'])
                raise AppError(report['protected_reason'] or f'存在业务或历史记录，禁止删除：{details}')
            if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise AppError('数据库已有外键异常，账号未删除，请先排查数据完整性。')
            backup = self._backup()
            for table, column in sorted(self._REMOVABLE):
                connection.execute(f'DELETE FROM {_identifier(table)} WHERE {_identifier(column)}=?', (report['id'],))
            connection.execute('DELETE FROM users WHERE id=?', (report['id'],))
            if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise AppError('删除后完整性检查失败，本次删除已回滚。')
            result = {'id': report['id'], 'username': report['username'], 'backup': str(backup)}
        return result
