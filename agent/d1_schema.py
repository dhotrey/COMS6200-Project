"""Idempotent Cloudflare D1 schema for agent conversations and measurements."""

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY NOT NULL,
        title TEXT NOT NULL,
        history TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(history)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY,
        conversation_id TEXT NOT NULL
            REFERENCES conversations(id) ON DELETE CASCADE,
        payload TEXT NOT NULL CHECK (json_valid(payload)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_messages_conversation_id_id
    ON messages(conversation_id, id)
    """,
)

EXPECTED_COLUMNS = {
    "conversations": {"id", "title", "history", "created_at", "updated_at"},
    "messages": {"id", "conversation_id", "payload", "created_at"},
}

EXPECTED_INDEX = "idx_messages_conversation_id_id"
