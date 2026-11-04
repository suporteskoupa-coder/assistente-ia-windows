import time

import pytest

from ultron.chats import ChatStore


def test_create_get_roundtrip(tmp_path):
    s = ChatStore(tmp_path / "u.db")
    c = s.create("claude")
    got = s.get(c.id)
    assert got.brain == "claude" and got.title == "Novo chat"
    assert got.claude_session_id is None and got.continues_from is None


def test_list_orders_by_last_message(tmp_path):
    s = ChatStore(tmp_path / "u.db")
    a = s.create("claude", "A")
    b = s.create("claude", "B")
    time.sleep(0.01)
    s.add_message(a.id, "user", "oi")
    assert [c.title for c in s.list()] == ["A", "B"]


def test_messages_in_order(tmp_path):
    s = ChatStore(tmp_path / "u.db")
    c = s.create("ollama")
    s.add_message(c.id, "user", "1")
    s.add_message(c.id, "assistant", "2")
    assert [(m.role, m.content) for m in s.messages(c.id)] == [("user", "1"), ("assistant", "2")]


def test_set_session_persists_after_reopen(tmp_path):
    s = ChatStore(tmp_path / "u.db")
    c = s.create("claude")
    s.set_session(c.id, "abc")
    s.rename(c.id, "Título")
    s2 = ChatStore(tmp_path / "u.db")
    assert s2.get(c.id).claude_session_id == "abc"
    assert s2.get(c.id).title == "Título"


def test_get_unknown_raises_keyerror(tmp_path):
    with pytest.raises(KeyError):
        ChatStore(tmp_path / "u.db").get(99)


def test_continues_from_saved(tmp_path):
    s = ChatStore(tmp_path / "u.db")
    a = s.create("claude")
    b = s.create("ollama", continues_from=a.id)
    assert s.get(b.id).continues_from == a.id
