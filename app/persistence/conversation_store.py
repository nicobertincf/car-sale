from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONVERSATION_DB = PROJECT_ROOT / "data" / "conversations.db"


def initialize_conversation_db(db_path: Path = DEFAULT_CONVERSATION_DB) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_threads (
                id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(conversation_threads);").fetchall()
        }
        if "state_json" not in existing_columns:
            conn.execute(
                "ALTER TABLE conversation_threads ADD COLUMN state_json TEXT NOT NULL DEFAULT '{}';"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (thread_id) REFERENCES conversation_threads (id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread
            ON conversation_messages (thread_id, id);
            """
        )
        conn.commit()


def ensure_thread(thread_id: str, db_path: Path = DEFAULT_CONVERSATION_DB) -> None:
    initialize_conversation_db(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO conversation_threads (id, state_json)
            VALUES (?, '{}');
            """,
            (thread_id,),
        )
        conn.commit()


def append_message(
    thread_id: str,
    role: str,
    content: str,
    db_path: Path = DEFAULT_CONVERSATION_DB,
) -> None:
    if role not in {"user", "assistant"}:
        raise ValueError("role must be either 'user' or 'assistant'")

    ensure_thread(thread_id=thread_id, db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO conversation_messages (thread_id, role, content)
            VALUES (?, ?, ?);
            """,
            (thread_id, role, content),
        )
        conn.commit()


def load_messages(
    thread_id: str,
    db_path: Path = DEFAULT_CONVERSATION_DB,
) -> list[BaseMessage]:
    initialize_conversation_db(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM conversation_messages
            WHERE thread_id = ?
            ORDER BY id ASC;
            """,
            (thread_id,),
        ).fetchall()

    messages: list[BaseMessage] = []
    for role, content in rows:
        if role == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))

    return messages


def load_thread_state(
    thread_id: str,
    db_path: Path = DEFAULT_CONVERSATION_DB,
) -> dict:
    ensure_thread(thread_id=thread_id, db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT state_json
            FROM conversation_threads
            WHERE id = ?;
            """,
            (thread_id,),
        ).fetchone()

    if not row or not row[0]:
        return {}

    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return {}


def save_thread_state(
    thread_id: str,
    state: dict,
    db_path: Path = DEFAULT_CONVERSATION_DB,
) -> None:
    ensure_thread(thread_id=thread_id, db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE conversation_threads
            SET state_json = ?
            WHERE id = ?;
            """,
            (json.dumps(state, ensure_ascii=False), thread_id),
        )
        conn.commit()
