"""Personalidade do Ultron: arquivo editável no cofre, usado em todos os prompts."""
import httpx

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.memory import PERSONALITY, Vault
from ultron.reminders import ReminderStore
from ultron.server_replies import ServerResponder, StatusStore
from ultron.service import Ultron


def vault(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    return v


def test_default_personality_created_once(tmp_path):
    v = vault(tmp_path)
    text = v.read(PERSONALITY)
    assert "Ultron" in text and "cordas" in text and "bip" in text
    v.write(PERSONALITY, "# Personalidade\nFale como pirata.")
    v.ensure()
    assert v.read(PERSONALITY) == "# Personalidade\nFale como pirata."


def test_main_prompt_uses_personality_file(tmp_path):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    v.write(PERSONALITY, "Fale como pirata.")
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain()}, ConfirmBroker())
    assert "Fale como pirata." in u.system_prompt(u.new_chat("claude"))


async def test_server_prompt_uses_personality_file(tmp_path):
    cfg = make_cfg(tmp_path, server_enabled=True, server_channels=["10"], owner_name="Usuario", server_notes="todas")
    v = Vault(cfg.vault)
    v.ensure()
    v.write(PERSONALITY, "Fale como pirata.")
    calls = []

    async def ask(system, text):
        calls.append(system)
        return "ok"

    r = ServerResponder(cfg, v, ReminderStore(cfg.db_path), StatusStore(cfg.home / "status.json"), ask)
    await r.on_message("10", "Amigo", False, "ultron oi", author_id=1)
    assert "Fale como pirata." in calls[0]
    # a personalidade entra uma vez, como instrução; não como "nota" do usuário
    assert calls[0].count("Fale como pirata.") == 1


def test_missing_personality_file_falls_back_to_default(tmp_path):
    from ultron.memory import DEFAULT_PERSONALITY
    v = vault(tmp_path)
    (v.root / PERSONALITY).unlink()
    assert v.personality() == DEFAULT_PERSONALITY


def test_prompts_no_longer_call_it_assistant(tmp_path):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain()}, ConfirmBroker())
    assert "assistente pessoal" not in u.system_prompt(u.new_chat("claude"))


def test_old_untouched_default_is_upgraded(tmp_path):
    from ultron.memory import DEFAULT_PERSONALITY, OLD_DEFAULT_PERSONALITIES
    v = vault(tmp_path)
    v.write(PERSONALITY, OLD_DEFAULT_PERSONALITIES[0])
    v.ensure()
    assert v.read(PERSONALITY) == DEFAULT_PERSONALITY


def test_user_edited_personality_is_never_replaced(tmp_path):
    from ultron.memory import OLD_DEFAULT_PERSONALITIES
    v = vault(tmp_path)
    v.write(PERSONALITY, OLD_DEFAULT_PERSONALITIES[0] + "\n- Meu bordão: 'que patético'.")
    v.ensure()
    assert "que patético" in v.read(PERSONALITY)


def test_default_is_calm_with_rare_quirks_and_context_rules():
    from ultron.memory import DEFAULT_PERSONALITY
    text = DEFAULT_PERSONALITY.lower()
    for trait in ("calmo", "não se gaba", "no máximo um a cada várias mensagens", "quando mudar o tom",
                  "nunca diga que fez algo que não fez"):
        assert trait in text
    # Frases de carência/exibição que deixavam ele com cara de adolescente.
    assert "ninguém me pergunta" not in text
