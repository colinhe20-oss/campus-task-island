"""每次操作独立连接；数据库路径不依赖启动目录。"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / ".runtime" / "campus.sqlite3"

TASK_TABLE = '''CREATE TABLE {table} (
    id TEXT PRIMARY KEY, title TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('learning','creative','music','daily')),
    description TEXT NOT NULL, completion_criteria TEXT NOT NULL,
    location TEXT, deadline TEXT, reward TEXT,
    is_listed INTEGER NOT NULL DEFAULT 1 CHECK(is_listed IN (0,1)),
    status TEXT NOT NULL DEFAULT 'published'
        CHECK(status IN ('published','in_progress','pending_review','completed','paused','cancelled')),
    created_at TEXT NOT NULL,
    publisher_id TEXT REFERENCES users(id), assignee_id TEXT REFERENCES users(id),
    acceptance_mode TEXT NOT NULL DEFAULT 'approval' CHECK(acceptance_mode IN ('approval','direct')),
    application_requirements TEXT NOT NULL DEFAULT '{{"reason":"required","experience":"disabled","supplement":"disabled"}}',
    reward_type TEXT NOT NULL DEFAULT 'legacy' CHECK(reward_type IN ('legacy','mutual','paid')),
    reward_amount_fen INTEGER,
    terms_version INTEGER NOT NULL DEFAULT 1,
    collaboration_version INTEGER NOT NULL DEFAULT 1 CHECK(collaboration_version>=1),
    paused_from_status TEXT CHECK(paused_from_status IS NULL OR paused_from_status IN ('in_progress','pending_review')),
    pause_reason TEXT, cancelled_at TEXT, cancel_reason TEXT,
    cancellation_settlement_fen INTEGER CHECK(cancellation_settlement_fen IS NULL OR cancellation_settlement_fen>=0),
    cancellation_settlement_reason TEXT,
    CHECK(publisher_id IS NULL OR assignee_id IS NULL OR publisher_id != assignee_id)
)'''


def configured_db_path() -> Path:
    return Path(os.getenv("CAMPUS_DB_PATH") or DEFAULT_DB_PATH).expanduser().resolve()


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(tasks)')}
            current_version=connection.execute('PRAGMA user_version').fetchone()[0]
            if columns and ('publisher_id' not in columns or 'is_listed' not in columns):
                stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
                backup_path = self.path.with_name(f'{self.path.stem}.before-collaboration-{stamp}.sqlite3')
                with closing(sqlite3.connect(backup_path)) as backup:
                    connection.backup(backup)
            elif columns and current_version<14:
                stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
                backup_path = self.path.with_name(f'{self.path.stem}.before-lifecycle-{stamp}.sqlite3')
                with closing(sqlite3.connect(backup_path)) as backup:
                    connection.backup(backup)
            connection.execute('PRAGMA journal_mode=WAL')
            # Status and application history need broader CHECK/UNIQUE rules. Rebuild
            # only those two tables with FK enforcement paused; restore and verify it
            # before committing the migration.
            connection.execute('PRAGMA foreign_keys=OFF')
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('''CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
                salt TEXT NOT NULL, password_hash TEXT NOT NULL,
                account_status TEXT NOT NULL DEFAULT 'active' CHECK(account_status IN ('active','closed')),
                closed_at TEXT)''')
            user_columns = {row['name'] for row in connection.execute('PRAGMA table_info(users)')}
            if 'account_status' not in user_columns:
                connection.execute("ALTER TABLE users ADD COLUMN account_status TEXT NOT NULL DEFAULT 'active' CHECK(account_status IN ('active','closed'))")
            if 'closed_at' not in user_columns:
                connection.execute('ALTER TABLE users ADD COLUMN closed_at TEXT')
            connection.execute('CREATE INDEX IF NOT EXISTS idx_users_account_status ON users(account_status)')
            if not columns:
                connection.execute(TASK_TABLE.format(table='tasks'))
            elif 'publisher_id' not in columns:
                connection.execute(TASK_TABLE.format(table='tasks_migrated'))
                connection.execute('''INSERT INTO tasks_migrated
                    (id,title,category,description,completion_criteria,location,deadline,reward,status,created_at)
                    SELECT id,title,category,description,completion_criteria,location,deadline,reward,status,created_at FROM tasks''')
                connection.execute('DROP TABLE tasks')
                connection.execute('ALTER TABLE tasks_migrated RENAME TO tasks')
            current_columns = {row['name'] for row in connection.execute('PRAGMA table_info(tasks)')}
            if 'is_listed' not in current_columns:
                connection.execute('ALTER TABLE tasks ADD COLUMN is_listed INTEGER NOT NULL DEFAULT 1 CHECK(is_listed IN (0,1))')
            statements = [
                '''CREATE TABLE IF NOT EXISTS activity_permissions (
                    user_id TEXT PRIMARY KEY REFERENCES users(id),
                    can_publish INTEGER NOT NULL CHECK(can_publish IN (0,1)))''',
                '''CREATE TABLE IF NOT EXISTS activity_bootstrap (
                    name TEXT PRIMARY KEY, created_at TEXT NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS activities (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL, description TEXT NOT NULL, location TEXT NOT NULL,
                    starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
                    opens_at TEXT NOT NULL, closes_at TEXT NOT NULL,
                    capacity INTEGER NOT NULL CHECK(capacity>0),
                    registration_mode TEXT NOT NULL CHECK(registration_mode IN ('direct','review')),
                    recognition_tags TEXT NOT NULL, recognition_description TEXT NOT NULL,
                    organization_name TEXT NOT NULL, information_source TEXT NOT NULL, contact TEXT NOT NULL,
                    participation_requirements TEXT NOT NULL, created_at TEXT NOT NULL,
                    queue_counter INTEGER NOT NULL DEFAULT 0 CHECK(queue_counter>=0),
                    cancelled_at TEXT, cancellation_reason TEXT,
                    CHECK(opens_at<closes_at AND closes_at<=starts_at AND starts_at<ends_at))''',
                '''CREATE TABLE IF NOT EXISTS activity_registrations (
                    id TEXT PRIMARY KEY, activity_id TEXT NOT NULL REFERENCES activities(id),
                    user_id TEXT NOT NULL REFERENCES users(id), attempt INTEGER NOT NULL CHECK(attempt>0),
                    application_note TEXT NOT NULL, status TEXT NOT NULL
                        CHECK(status IN ('pending','registered','waitlisted','rejected','cancelled','activity_cancelled')),
                    queue_sequence INTEGER, review_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(activity_id,user_id,attempt), UNIQUE(activity_id,queue_sequence))''',
                "CREATE UNIQUE INDEX IF NOT EXISTS one_active_registration ON activity_registrations(activity_id,user_id) WHERE status IN ('pending','registered','waitlisted')",
                'CREATE INDEX IF NOT EXISTS idx_activity_queue ON activity_registrations(activity_id,status,queue_sequence)',
                'CREATE INDEX IF NOT EXISTS idx_activity_person ON activity_registrations(user_id,activity_id,attempt)',
                'CREATE INDEX IF NOT EXISTS idx_activity_window ON activities(ends_at,starts_at)',
                '''CREATE TABLE IF NOT EXISTS activity_events (
                    id TEXT PRIMARY KEY, activity_id TEXT NOT NULL REFERENCES activities(id),
                    registration_id TEXT REFERENCES activity_registrations(id),
                    actor_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL,
                    reason TEXT NOT NULL, created_at TEXT NOT NULL, sequence INTEGER NOT NULL,
                    UNIQUE(activity_id,sequence))''',
                '''CREATE TABLE IF NOT EXISTS task_stage_plans (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(id), version INTEGER NOT NULL CHECK(version>=1))''',
                '''CREATE TABLE IF NOT EXISTS task_stage_plan_versions (
                    task_id TEXT NOT NULL REFERENCES tasks(id), version INTEGER NOT NULL,
                    fields TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
                    suggestion_id TEXT, PRIMARY KEY(task_id,version))''',
                '''CREATE TABLE IF NOT EXISTS task_stages (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    position INTEGER NOT NULL CHECK(position>=1), title TEXT NOT NULL,
                    completion_criteria TEXT NOT NULL, deadline TEXT NOT NULL,
                    responsible_role TEXT NOT NULL CHECK(responsible_role IN ('publisher','assignee')),
                    status TEXT NOT NULL CHECK(status IN ('not_started','in_progress','submitted','changes_requested','confirmed')),
                    version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1), UNIQUE(task_id,position))''',
                '''CREATE TABLE IF NOT EXISTS stage_submissions (
                    id TEXT PRIMARY KEY, stage_id TEXT NOT NULL REFERENCES task_stages(id),
                    task_id TEXT NOT NULL REFERENCES tasks(id), author_id TEXT NOT NULL REFERENCES users(id),
                    summary TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('submitted','accepted','changes_requested')),
                    feedback TEXT, created_at TEXT NOT NULL, reviewed_at TEXT, reviewer_id TEXT REFERENCES users(id))''',
                "CREATE UNIQUE INDEX IF NOT EXISTS one_stage_submission ON stage_submissions(stage_id) WHERE status='submitted'",
                '''CREATE TABLE IF NOT EXISTS stage_suggestions (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    user_id TEXT NOT NULL REFERENCES users(id), conversation_id TEXT NOT NULL REFERENCES guide_conversations(id),
                    base_version INTEGER NOT NULL, fields TEXT NOT NULL, model TEXT,
                    applied_version INTEGER, created_at TEXT NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS guide_runs (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    conversation_id TEXT, status TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, duration_ms INTEGER, model TEXT,
                    metrics TEXT NOT NULL DEFAULT '{}', events TEXT NOT NULL DEFAULT '[]',
                    result TEXT, error TEXT)''',
                'CREATE INDEX IF NOT EXISTS idx_guide_runs_user ON guide_runs(user_id,started_at DESC)',
                'CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC,id DESC)',
                'CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(category)',
                '''CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at REAL NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    applicant_id TEXT NOT NULL REFERENCES users(id), reason TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected','withdrawn')),
                    created_at TEXT NOT NULL, request_id TEXT, withdrawn_at TEXT)''',
                "CREATE UNIQUE INDEX IF NOT EXISTS one_accepted_application ON applications(task_id) WHERE status='accepted'",
                "CREATE UNIQUE INDEX IF NOT EXISTS one_pending_application_per_user ON applications(task_id,applicant_id) WHERE status='pending'",
                '''CREATE TABLE IF NOT EXISTS submissions (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    author_id TEXT NOT NULL REFERENCES users(id), summary TEXT NOT NULL, link TEXT,
                    status TEXT NOT NULL CHECK(status IN ('submitted','accepted','changes_requested')),
                    feedback TEXT, created_at TEXT NOT NULL, reviewed_at TEXT)''',
                '''CREATE TABLE IF NOT EXISTS guide_conversations (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    history TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS guide_task_drafts (
                    conversation_id TEXT PRIMARY KEY REFERENCES guide_conversations(id),
                    user_id TEXT NOT NULL REFERENCES users(id), fields TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version>=1),
                    status TEXT NOT NULL CHECK(status IN ('draft','published','cancelled')),
                    published_task_id TEXT REFERENCES tasks(id), updated_at TEXT NOT NULL)''',
            ]
            from .volunteer_db import STATEMENTS as volunteer_statements
            statements.extend(volunteer_statements)
            from .discovery_db import STATEMENTS as discovery_statements
            statements.extend(discovery_statements)
            for statement in statements:
                connection.execute(statement)
            from .notifications import STATEMENTS as notification_statements
            for statement in notification_statements:
                connection.execute(statement)
            task_columns = {r['name'] for r in connection.execute('PRAGMA table_info(tasks)')}
            if 'acceptance_mode' not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN acceptance_mode TEXT NOT NULL DEFAULT 'approval' CHECK(acceptance_mode IN ('approval','direct'))")
                connection.execute("""ALTER TABLE tasks ADD COLUMN application_requirements TEXT NOT NULL DEFAULT '{"reason":"required","experience":"disabled","supplement":"disabled"}'""")
            app_columns = {r['name'] for r in connection.execute('PRAGMA table_info(applications)')}
            for name in ('experience','supplement'):
                if name not in app_columns:
                    connection.execute(f"ALTER TABLE applications ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            task_columns = {r['name'] for r in connection.execute('PRAGMA table_info(tasks)')}
            for name,definition in [('reward_type',"TEXT NOT NULL DEFAULT 'legacy' CHECK(reward_type IN ('legacy','mutual','paid'))"),('reward_amount_fen','INTEGER'),('terms_version','INTEGER NOT NULL DEFAULT 1')]:
                if name not in task_columns:
                    connection.execute(f'ALTER TABLE tasks ADD COLUMN {name} {definition}')
            app_columns={r['name'] for r in connection.execute('PRAGMA table_info(applications)')}
            for name,definition in [('request_id','TEXT'),('withdrawn_at','TEXT')]:
                if name not in app_columns:connection.execute(f'ALTER TABLE applications ADD COLUMN {name} {definition}')
            task_sql=connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()[0]
            if "'paused'" not in task_sql or "'cancelled'" not in task_sql:
                connection.execute(TASK_TABLE.format(table='tasks_lifecycle_new'))
                old={r['name'] for r in connection.execute('PRAGMA table_info(tasks)')}
                new={r['name'] for r in connection.execute('PRAGMA table_info(tasks_lifecycle_new)')}
                common=sorted(old & new)
                connection.execute(f"INSERT INTO tasks_lifecycle_new ({','.join(common)}) SELECT {','.join(common)} FROM tasks")
                connection.execute('DROP TABLE tasks')
                connection.execute('ALTER TABLE tasks_lifecycle_new RENAME TO tasks')
                connection.execute('CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC,id DESC)')
                connection.execute('CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(category)')
            app_sql=connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='applications'").fetchone()[0]
            if 'UNIQUE(task_id,applicant_id)' in app_sql or "'withdrawn'" not in app_sql:
                connection.execute('''CREATE TABLE applications_history_new (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    applicant_id TEXT NOT NULL REFERENCES users(id), reason TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected','withdrawn')),
                    created_at TEXT NOT NULL, experience TEXT NOT NULL DEFAULT '', supplement TEXT NOT NULL DEFAULT '',
                    request_id TEXT, withdrawn_at TEXT)''')
                old={r['name'] for r in connection.execute('PRAGMA table_info(applications)')}
                new={r['name'] for r in connection.execute('PRAGMA table_info(applications_history_new)')}
                common=sorted(old & new)
                connection.execute(f"INSERT INTO applications_history_new ({','.join(common)}) SELECT {','.join(common)} FROM applications")
                connection.execute('DROP TABLE applications')
                connection.execute('ALTER TABLE applications_history_new RENAME TO applications')
                connection.execute("CREATE UNIQUE INDEX one_accepted_application ON applications(task_id) WHERE status='accepted'")
                connection.execute("CREATE UNIQUE INDEX one_pending_application_per_user ON applications(task_id,applicant_id) WHERE status='pending'")
                connection.execute("CREATE UNIQUE INDEX one_application_request ON applications(task_id,applicant_id,request_id) WHERE request_id IS NOT NULL")
                connection.execute('CREATE INDEX IF NOT EXISTS idx_applications_person ON applications(applicant_id,task_id,created_at)')
            else:
                connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_application_request ON applications(task_id,applicant_id,request_id) WHERE request_id IS NOT NULL")
            from .terms import STATEMENTS as terms_statements
            for statement in terms_statements:connection.execute(statement)
            from .changes import migrate
            migrate(connection)
            from .changes import migrate_control_columns
            migrate_control_columns(connection)
            if 'amount_fen' not in {r['name'] for r in connection.execute('PRAGMA table_info(task_settlements)')}:
                connection.execute('ALTER TABLE task_settlements ADD COLUMN amount_fen INTEGER')
            connection.execute('PRAGMA user_version=14')
            connection.commit()
            connection.execute('PRAGMA foreign_keys=ON')
            violations=connection.execute('PRAGMA foreign_key_check').fetchall()
            if violations:raise sqlite3.IntegrityError(f'foreign key violations after schema migration: {len(violations)}')
