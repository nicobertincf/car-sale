from app.persistence.conversation_store import (
    append_message,
    load_messages,
    load_thread_state,
    save_thread_state,
)


def test_conversation_store_persists_messages_and_state(tmp_path):
    db_path = tmp_path / "conversation.db"
    thread_id = "thread-123"

    append_message(thread_id=thread_id, role="user", content="Hola", db_path=db_path)
    append_message(thread_id=thread_id, role="assistant", content="Hola, ¿en qué te ayudo?", db_path=db_path)

    messages = load_messages(thread_id=thread_id, db_path=db_path)
    assert len(messages) == 2
    assert messages[0].content == "Hola"
    assert "ayudo" in messages[1].content

    state = {
        "active_flow": "contact",
        "search_filters": {"make": "Toyota", "price_usd_max": 25000},
        "pending_contact": {"customer_name": "Ana"},
    }
    save_thread_state(thread_id=thread_id, state=state, db_path=db_path)

    loaded_state = load_thread_state(thread_id=thread_id, db_path=db_path)
    assert loaded_state["active_flow"] == "contact"
    assert loaded_state["search_filters"]["make"] == "Toyota"
    assert loaded_state["pending_contact"]["customer_name"] == "Ana"
