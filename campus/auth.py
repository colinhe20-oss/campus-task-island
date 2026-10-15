"""本地预置账号、密码散列和可撤销的 Cookie 会话。"""
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from uuid import uuid4

from .db import Database
from .errors import AppError
from .schemas import UserRead

SESSION_SECONDS = 7 * 24 * 3600
DEMO_USERS = {'publisher': '发布者小林', 'helper': '接取者小陈', 'observer': '同学小周'}


def password_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260_000).hex()


class AuthService:
    def __init__(self, database: Database):
        self.database = database
        self.accounts_path = database.path.with_suffix('.accounts.json')

    def provision_demo_accounts(self) -> None:
        accounts = json.loads(self.accounts_path.read_text(encoding='utf-8')) if self.accounts_path.exists() else {}
        changed = False
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            for username, display_name in DEMO_USERS.items():
                if connection.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
                    continue
                password = secrets.token_urlsafe(12)
                salt = secrets.token_hex(16)
                connection.execute('INSERT INTO users (id,username,display_name,salt,password_hash) VALUES (?,?,?,?,?)',
                    (uuid4().hex, username, display_name, salt, password_hash(password, salt)))
                accounts[username] = {'display_name': display_name, 'password': password}
                changed = True
            publisher = connection.execute("SELECT id FROM users WHERE username='publisher'").fetchone()
            # 保留旧权限记录供历史数据库兼容；发布能力现由有效账号状态决定。
            if not connection.execute("SELECT 1 FROM activity_bootstrap WHERE name='demo_publisher'").fetchone():
                connection.execute('INSERT OR IGNORE INTO activity_permissions VALUES (?,1)', (publisher['id'],))
                connection.execute('INSERT INTO activity_bootstrap VALUES (?,?)', ('demo_publisher', datetime.now(timezone.utc).isoformat()))
            connection.execute('UPDATE tasks SET publisher_id=? WHERE publisher_id IS NULL', (publisher['id'],))
            if changed:
                temporary = self.accounts_path.with_suffix('.json.tmp')
                temporary.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(self.accounts_path)

    def login(self, username: str, password: str) -> tuple[str, UserRead]:
        username = username.strip().lower()
        with self.database.connect() as connection:
            row = connection.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            digest = password_hash(password, row['salt'] if row else '00' * 16)
            if not row or row['account_status'] != 'active' or not hmac.compare_digest(digest, row['password_hash']):
                raise AppError('账号或密码不正确', 401)
            token = secrets.token_urlsafe(32)
            connection.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
            connection.execute('INSERT INTO sessions VALUES (?,?,?)',
                (hashlib.sha256(token.encode()).hexdigest(), row['id'], time.time() + SESSION_SECONDS))
        return token, UserRead(id=row['id'], username=row['username'], display_name=row['display_name'], can_publish_activities=True, can_publish_volunteers=True)

    def register(self, username: str, display_name: str, password: str) -> tuple[str, UserRead]:
        identifier = uuid4().hex
        salt = secrets.token_hex(16)
        digest = password_hash(password, salt)
        token = secrets.token_urlsafe(32)
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
                raise AppError('这个账号名已被使用，请换一个账号名', 409)
            connection.execute('''INSERT INTO users
                (id,username,display_name,salt,password_hash,account_status,closed_at)
                VALUES (?,?,?,?,?,'active',NULL)''',
                (identifier, username, display_name, salt, digest))
            connection.execute('INSERT INTO sessions VALUES (?,?,?)',
                (hashlib.sha256(token.encode()).hexdigest(), identifier, time.time() + SESSION_SECONDS))
        return token, UserRead(id=identifier, username=username, display_name=display_name,
                               can_publish_activities=True, can_publish_volunteers=True)

    def current_user(self, token: str | None) -> UserRead:
        if not token:
            raise AppError('请先登录', 401)
        with self.database.connect() as connection:
            row = connection.execute('''SELECT u.id,u.username,u.display_name FROM sessions s
                JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.account_status='active' ''',
                (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if row is None:
            raise AppError('登录已失效，请重新登录', 401)
        return UserRead.model_validate(dict(row) | {'can_publish_activities':True,'can_publish_volunteers':True})

    def logout(self, token: str | None) -> None:
        if token:
            with self.database.connect() as connection:
                connection.execute('DELETE FROM sessions WHERE token_hash=?',
                    (hashlib.sha256(token.encode()).hexdigest(),))

    def reset_password(self, username: str, password: str) -> None:
        salt = secrets.token_hex(16)
        digest = password_hash(password, salt)
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute("SELECT id FROM users WHERE username=? AND account_status='active'", (username,)).fetchone()
            if row is None:
                raise AppError('有效账号不存在；注销账号不会被重新启用', 404)
            connection.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?', (salt, digest, row['id']))
            connection.execute('DELETE FROM sessions WHERE user_id=?', (row['id'],))
