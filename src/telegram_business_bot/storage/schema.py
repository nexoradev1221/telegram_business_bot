"""Ordered, transactional migrations. Never use executescript inside a transaction."""

APPLICATION_ID = 0x54425242
MIGRATIONS = (
    (
        """CREATE TABLE requests (
            id INTEGER PRIMARY KEY,
            reference TEXT NOT NULL UNIQUE,
            submission_key TEXT NOT NULL CHECK(length(submission_key) BETWEEN 16 AND 128),
            customer_user_id INTEGER NOT NULL CHECK(customer_user_id > 0),
            customer_chat_id INTEGER NOT NULL CHECK(customer_chat_id = customer_user_id),
            category TEXT NOT NULL,
            problem_summary TEXT NOT NULL CHECK(length(problem_summary) BETWEEN 5 AND 1000),
            district TEXT NOT NULL,
            visit_start_at TEXT NOT NULL,
            visit_end_at TEXT NOT NULL CHECK(visit_end_at > visit_start_at),
            contact_preference TEXT NOT NULL CHECK(contact_preference IN ('telegram', 'phone')),
            contact_details TEXT,
            consent_at TEXT NOT NULL,
            consent_version TEXT NOT NULL CHECK(length(consent_version) > 0),
            status TEXT NOT NULL CHECK(status IN ('new', 'contacted', 'scheduled', 'closed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL CHECK(updated_at >= created_at),
            UNIQUE(customer_user_id, submission_key),
            CHECK((contact_preference = 'telegram' AND contact_details IS NULL)
               OR (contact_preference = 'phone' AND contact_details IS NOT NULL))
        )""",
        """CREATE TABLE status_history (
            id INTEGER PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES requests(id),
            from_status TEXT CHECK(from_status IN ('new', 'contacted', 'scheduled', 'closed')),
            to_status TEXT NOT NULL CHECK(to_status IN ('new', 'contacted', 'scheduled', 'closed')),
            actor_user_id INTEGER NOT NULL CHECK(actor_user_id > 0),
            changed_at TEXT NOT NULL
        )""",
        "CREATE INDEX history_request_order ON status_history(request_id, id)",
        """CREATE TABLE notification_outbox (
            id INTEGER PRIMARY KEY,
            request_id INTEGER NOT NULL UNIQUE REFERENCES requests(id),
            kind TEXT NOT NULL CHECK(kind = 'new_request'),
            state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending', 'sent', 'failed')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
            created_at TEXT NOT NULL,
            next_attempt_at TEXT NOT NULL,
            delivered_at TEXT,
            last_error_code TEXT
        )""",
    ),
)
