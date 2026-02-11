from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.car_sales_graph import graph
from app.persistence.conversation_store import (
    DEFAULT_CONVERSATION_DB,
    append_message,
    ensure_thread,
    load_messages,
    load_thread_state,
    save_thread_state,
)
from scripts.init_sqlite_db import DEFAULT_DB_PATH, initialize_database


def _latest_assistant_reply(messages) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return str(message.content)
    return "No se pudo generar respuesta."


def run_chat(thread_id: str, inventory_db: Path, conversation_db: Path) -> None:
    if not inventory_db.exists():
        initialize_database(db_path=inventory_db, seed_count=60)

    os.environ["DEALERSHIP_DB_PATH"] = str(inventory_db)

    ensure_thread(thread_id=thread_id, db_path=conversation_db)

    print(f"Conversación persistente iniciada. thread_id={thread_id}")
    print("Escribe '/exit' para salir.")

    while True:
        user_text = input("\nTú: ").strip()
        if not user_text:
            continue
        if user_text.lower() in {"/exit", "exit", "salir", "quit"}:
            print("Sesión finalizada.")
            break

        append_message(thread_id=thread_id, role="user", content=user_text, db_path=conversation_db)

        history = load_messages(thread_id=thread_id, db_path=conversation_db)
        persisted_state = load_thread_state(thread_id=thread_id, db_path=conversation_db)

        payload = {
            "messages": history,
            "route": persisted_state.get("route"),
        }

        output = graph.invoke(payload)
        reply = _latest_assistant_reply(output["messages"])

        append_message(thread_id=thread_id, role="assistant", content=reply, db_path=conversation_db)
        save_thread_state(
            thread_id=thread_id,
            state={"route": output.get("route")},
            db_path=conversation_db,
        )

        print(f"\nAsistente: {reply}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a persistent used-car quote assistant with contact request flow."
    )
    parser.add_argument(
        "--thread-id",
        default=f"chat-{uuid.uuid4().hex[:8]}",
        help="Persistent conversation ID.",
    )
    parser.add_argument(
        "--inventory-db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to inventory SQLite database (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--conversation-db",
        type=Path,
        default=DEFAULT_CONVERSATION_DB,
        help=f"Path to conversation SQLite database (default: {DEFAULT_CONVERSATION_DB}).",
    )

    args = parser.parse_args()
    run_chat(thread_id=args.thread_id, inventory_db=args.inventory_db, conversation_db=args.conversation_db)


if __name__ == "__main__":
    main()
