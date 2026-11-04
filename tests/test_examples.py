"""Banco de exemplos de fala: arquivo no cofre, escolha por semelhança, 👍 da HUD."""
import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.examples import EXAMPLES, SEED, ExampleStore, parse
from ultron.memory import Vault
from ultron.reminders import ReminderStore
from ultron.server import create_app
from ultron.server_replies import ServerResponder, StatusStore
from ultron.service import Ultron


def vault(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    return v


def test_seed_bank_is_valid_and_big_enough():
    items = parse(SEED.read_text(encoding="utf-8"))
    assert len(items) >= 100
    assert {e.place for e in items} == {"pc", "servidor", "qualquer"}
    # sem os vícios da personalidade antiga
    joined = " ".join(e.reply.lower() for e in items)
    for bad in ("ninguém me pergunta", "beep", "processando", "como posso ajudar"):
        assert bad not in joined


def test_bank_created_once_and_user_edits_kept(tmp_path):
    v = vault(tmp_path)
    p = v.root / EXAMPLES
    assert p.exists()
    p.write_text("## meu\nOnde: pc\nMensagem: oi\nUltron: Fala.\n", encoding="utf-8")
    v.ensure()
    assert len(ExampleStore(v).all()) == 1


def test_parse_multiline_reply_and_bad_blocks():
    text = ("## a\nOnde: servidor\nMensagem: oi\nUltron: linha 1\n- linha 2\n\n"
            "## sem resposta\nMensagem: x\n\n## lugar estranho\nOnde: marte\nMensagem: m\nUltron: r\n")
    items = parse(text)
    assert [e.title for e in items] == ["a", "lugar estranho"]
    assert items[0].reply == "linha 1\n- linha 2"
    assert items[1].place == "qualquer"


def test_pick_prefers_similar_and_right_place(tmp_path):
    v = vault(tmp_path)
    (v.root / EXAMPLES).write_text(
        "## jogo\nOnde: pc\nMensagem: abre o counter strike\nUltron: CS aberto.\n"
        "## lembrete\nOnde: pc\nMensagem: me lembra de beber água\nUltron: Marcado.\n"
        "## amigo\nOnde: servidor\nMensagem: cadê ele\nUltron: Estudando.\n"
        "## oi\nOnde: qualquer\nMensagem: oi\nUltron: Estou aqui.\n", encoding="utf-8")
    s = ExampleStore(v)
    assert s.pick("abre o counter strike agora", "pc", k=1)[0].title == "jogo"
    titles = {e.title for e in s.pick("cadê ele?", "servidor", k=3)}
    assert "amigo" in titles and "jogo" not in titles and "lembrete" not in titles
    # sem nada parecido ainda vem exemplo (o tom fica sempre presente), e a escolha é estável
    assert len(s.pick("xyzzy", "pc", k=2)) == 2
    assert s.pick("xyzzy", "pc", k=2) == s.pick("xyzzy", "pc", k=2)


def test_prompt_replaces_creator_and_warns_not_to_copy(tmp_path):
    v = vault(tmp_path)
    (v.root / EXAMPLES).write_text("## a\nOnde: servidor\nMensagem: cadê o {criador}?\nUltron: O {criador} saiu.\n",
                                   encoding="utf-8")
    out = ExampleStore(v).prompt("cadê", "servidor", "Usuario")
    assert "O Usuario saiu." in out and "{criador}" not in out
    assert "Nunca copie" in out


def test_add_appends_safely(tmp_path):
    v = vault(tmp_path)
    s = ExampleStore(v)
    before = len(s.all())
    s.add("abre\n o cs", "Aberto.\n## não é título\nUltron: nem campo", "pc")
    items = s.all()
    assert len(items) == before + 1
    e = items[-1]
    assert e.message == "abre o cs" and e.place == "pc"
    assert "não é título" in e.reply and "nem campo" in e.reply


async def test_examples_go_into_pc_prompt(tmp_path):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    (v.root / EXAMPLES).write_text("## jogo\nOnde: pc\nMensagem: abre o cs\nUltron: Boa caçada.\n", encoding="utf-8")
    brain = FakeBrain()
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": brain}, ConfirmBroker())
    c = u.new_chat("claude")
    async for _ in u.send(c.id, "abre o cs"):
        pass
    assert "Boa caçada." in brain.calls[0]["system"]


async def test_server_uses_only_server_examples_and_redacts(tmp_path):
    cfg = make_cfg(tmp_path, server_enabled=True, server_channels=["10"], owner_name="Usuario")
    v = Vault(cfg.vault)
    v.ensure()
    (v.root / EXAMPLES).write_text(
        "## pc\nOnde: pc\nMensagem: abre o cs\nUltron: SEGREDO_PC\n"
        "## sv\nOnde: servidor\nMensagem: cadê ele\nUltron: Mande para usuario@exemplo.com\n", encoding="utf-8")
    calls = []

    async def ask(system, text):
        calls.append(system)
        return "ok"

    r = ServerResponder(cfg, v, ReminderStore(cfg.db_path), StatusStore(cfg.home / "status.json"), ask)
    await r.on_message("10", "Amigo", False, "ultron cadê ele", author_id=1)
    assert "SEGREDO_PC" not in calls[0]
    assert "Mande para" in calls[0] and "usuario@exemplo.com" not in calls[0]


@pytest.fixture
def client(tmp_path):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    hud = tmp_path / "hud"
    hud.mkdir()
    (hud / "index.html").write_text("<h1>ULTRON</h1>")
    broker = ConfirmBroker(timeout=5)
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain("claude")}, broker)
    with TestClient(create_app(u, broker, hud)) as c:
        c.u = u
        yield c


def test_like_saves_reply_with_its_question(client):
    u = client.u
    cid = u.new_chat("claude").id
    u.store.add_message(cid, "user", "abre o deadlock")
    u.store.add_message(cid, "assistant", "Deadlock aberto.\n\nDivirta-se.")
    r = client.post(f"/api/chats/{cid}/like", json={"reply": "Divirta-se."})
    assert r.status_code == 200
    e = ExampleStore(u.vault).all()[-1]
    assert e.message == "abre o deadlock" and e.reply == "Divirta-se." and e.place == "pc"


def test_like_unknown_reply_is_rejected(client):
    cid = client.u.new_chat("claude").id
    assert client.post(f"/api/chats/{cid}/like", json={"reply": "nunca dito"}).status_code == 409
    assert client.post("/api/chats/999/like", json={"reply": "x"}).status_code == 404
