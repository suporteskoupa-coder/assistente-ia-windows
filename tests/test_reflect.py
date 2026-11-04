from datetime import date, datetime

from tests.fakes import FakeBrain
from ultron.events import Event
from ultron.memory import Conclusion, Vault
from ultron.reflect import apply_reflection, reflect, seconds_until

TODAY = date(2026, 10, 27)
CUR = [Conclusion("Joga à noite", "média", 2, "2026-10-20")]


def test_valid_reply_replaces():
    reply = "pensei...\n<conclusoes>\n- Joga à noite · confiança: alta · visto em 3 chats · 2026-10-27\n- Gosta de CS · confiança: baixa · visto em 1 chats · 2026-10-27\n</conclusoes>"
    out = apply_reflection(CUR, reply, TODAY)
    assert [c.text for c in out] == ["Joga à noite", "Gosta de CS"]
    assert out[0].confidence == "alta"


def test_reply_without_tags_keeps_current():
    assert apply_reflection(CUR, "não sei", TODAY) == CUR


def test_empty_tags_clears():
    assert apply_reflection(CUR, "<conclusoes>\n</conclusoes>", TODAY) == []


def test_old_single_sighting_removed():
    items = [Conclusion("velha", "baixa", 1, "2026-09-17"), Conclusion("velha forte", "alta", 5, "2026-09-17")]
    reply = "<conclusoes>\n" + "\n".join(c.line() for c in items) + "\n</conclusoes>"
    out = apply_reflection(items, reply, TODAY)
    assert [c.text for c in out] == ["velha forte"]


async def test_reflect_uses_diary_and_saves(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    v.save_conclusions(CUR)
    v.log("abriu CS", datetime(2026, 10, 26, 23, 0))
    b = FakeBrain(script=[Event("text", "<conclusoes>\n- Joga à noite · confiança: alta · visto em 3 chats · 2026-10-27\n</conclusoes>"), Event("done")])
    n = await reflect(v, b, TODAY)
    assert n == 1 and v.conclusions()[0].confidence == "alta"
    assert "abriu CS" in b.calls[0]["text"]


async def test_reflect_brain_error_keeps(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    v.save_conclusions(CUR)
    b = FakeBrain(script=[Event("error", "limite")])
    await reflect(v, b, TODAY)
    assert v.conclusions() == CUR


def test_seconds_until_next_4am():
    assert seconds_until(datetime(2026, 10, 27, 3, 0), 4) == 3600
    assert seconds_until(datetime(2026, 10, 27, 5, 0), 4) == 23 * 3600
