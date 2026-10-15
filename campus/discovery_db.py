STATEMENTS=[
    '''CREATE TABLE IF NOT EXISTS discoveries (
        id TEXT PRIMARY KEY, author_id TEXT NOT NULL REFERENCES users(id),
        category TEXT NOT NULL CHECK(category IN ('facility','safety','interesting','life')),
        title TEXT NOT NULL, description TEXT NOT NULL, location TEXT NOT NULL,
        discovered_at TEXT NOT NULL, information_source TEXT NOT NULL, image_ids TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('unverified','verified','reported','in_progress','resolved','valid','invalid','visible','expired')),
        version INTEGER NOT NULL CHECK(version>0), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        withdrawn_at TEXT, withdrawal_reason TEXT)''',
    '''CREATE TABLE IF NOT EXISTS discovery_comments (
        id TEXT PRIMARY KEY, discovery_id TEXT NOT NULL REFERENCES discoveries(id),
        author_id TEXT NOT NULL REFERENCES users(id), content TEXT NOT NULL, image_ids TEXT NOT NULL,
        created_at TEXT NOT NULL, withdrawn_at TEXT)''',
    'CREATE INDEX IF NOT EXISTS idx_discovery_comments ON discovery_comments(discovery_id,created_at,id)',
    'CREATE INDEX IF NOT EXISTS idx_discovery_list ON discoveries(withdrawn_at,updated_at DESC,id)',
    '''CREATE TABLE IF NOT EXISTS discovery_versions (
        discovery_id TEXT NOT NULL REFERENCES discoveries(id), version INTEGER NOT NULL,
        actor_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL, reason TEXT NOT NULL,
        changed_fields TEXT NOT NULL, before_fields TEXT NOT NULL, after_fields TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(discovery_id,version))''',
    '''CREATE TABLE IF NOT EXISTS discovery_status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, discovery_id TEXT NOT NULL REFERENCES discoveries(id),
        actor_id TEXT NOT NULL REFERENCES users(id), previous_status TEXT, status TEXT NOT NULL,
        reason TEXT NOT NULL, created_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS discovery_images (
        id TEXT PRIMARY KEY, uploader_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
        width INTEGER NOT NULL, height INTEGER NOT NULL, size INTEGER NOT NULL,
        attached_discovery_id TEXT REFERENCES discoveries(id), attached_comment_id TEXT REFERENCES discovery_comments(id),
        CHECK(attached_discovery_id IS NULL OR attached_comment_id IS NULL))''',
]
