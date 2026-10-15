STATEMENTS = [
    '''CREATE TABLE IF NOT EXISTS volunteer_activities (
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL,
        description TEXT NOT NULL, organization_name TEXT NOT NULL, information_source TEXT NOT NULL,
        contact TEXT NOT NULL, recognition_conditions TEXT NOT NULL, starts_at TEXT NOT NULL,
        ends_at TEXT NOT NULL, opens_at TEXT NOT NULL, closes_at TEXT NOT NULL,
        registration_mode TEXT NOT NULL CHECK(registration_mode IN ('direct','review')),
        created_at TEXT NOT NULL, cancelled_at TEXT, cancellation_reason TEXT)''',
    '''CREATE TABLE IF NOT EXISTS volunteer_jobs (
        id TEXT PRIMARY KEY, activity_id TEXT NOT NULL REFERENCES volunteer_activities(id),
        position INTEGER NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, requirements TEXT NOT NULL,
        location TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
        capacity INTEGER NOT NULL CHECK(capacity>0), estimated_minutes INTEGER NOT NULL CHECK(estimated_minutes>0),
        estimated_hours_description TEXT NOT NULL, queue_counter INTEGER NOT NULL DEFAULT 0,
        UNIQUE(activity_id,position))''',
    '''CREATE TABLE IF NOT EXISTS volunteer_registrations (
        id TEXT PRIMARY KEY, activity_id TEXT NOT NULL REFERENCES volunteer_activities(id),
        job_id TEXT NOT NULL REFERENCES volunteer_jobs(id), user_id TEXT NOT NULL REFERENCES users(id),
        attempt INTEGER NOT NULL, application_note TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','registered','waitlisted','rejected','cancelled','activity_cancelled')),
        queue_sequence INTEGER, review_reason TEXT NOT NULL DEFAULT '', registered_at TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(activity_id,user_id,attempt), UNIQUE(job_id,queue_sequence))''',
    "CREATE UNIQUE INDEX IF NOT EXISTS one_active_volunteer ON volunteer_registrations(activity_id,user_id) WHERE status IN ('pending','registered','waitlisted')",
    'CREATE INDEX IF NOT EXISTS idx_volunteer_queue ON volunteer_registrations(job_id,status,queue_sequence)',
    'CREATE INDEX IF NOT EXISTS idx_volunteer_person ON volunteer_registrations(user_id,activity_id,attempt)',
    '''CREATE TABLE IF NOT EXISTS volunteer_participation (
        registration_id TEXT PRIMARY KEY REFERENCES volunteer_registrations(id),
        attendance TEXT NOT NULL CHECK(attendance IN ('participated','absent')),
        actual_minutes INTEGER NOT NULL CHECK(actual_minutes>=0), description TEXT NOT NULL,
        confirmed_minutes INTEGER CHECK(confirmed_minutes>=0 AND confirmed_minutes<=actual_minutes),
        hours_reason TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL CHECK(version>0),
        updated_by TEXT NOT NULL REFERENCES users(id), updated_at TEXT NOT NULL,
        CHECK(attendance!='absent' OR actual_minutes=0))''',
    '''CREATE TABLE IF NOT EXISTS volunteer_record_versions (
        registration_id TEXT NOT NULL REFERENCES volunteer_registrations(id), version INTEGER NOT NULL,
        actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, action TEXT NOT NULL,
        reason TEXT NOT NULL, before_fields TEXT NOT NULL, after_fields TEXT NOT NULL,
        PRIMARY KEY(registration_id,version))''',
    '''CREATE TABLE IF NOT EXISTS volunteer_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, activity_id TEXT NOT NULL REFERENCES volunteer_activities(id),
        registration_id TEXT REFERENCES volunteer_registrations(id), actor_id TEXT NOT NULL REFERENCES users(id),
        action TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL)''',
]
