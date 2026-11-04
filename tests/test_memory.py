from datetime import datetime

import pytest

from ultron.memory import Conclusion, Vault


@pytest.fixture
def vault(tmp_path):
    v = Vault(tmp_path / "vault")
    v.ensure()
    return v


def test_ensure_creates_memory_files(vault):
    for name in ("perfil.md", "preferencias.md", "conclusoes.md"):
        assert (vault.root / "Ultron" / "Memoria" / name).exists()
    assert (vault.root / "Ultron" / "Diario").is_dir()
    assert (vault.root / "Ultron" / "Chats").is_dir()
    assert (vault.root / "Notas").is_dir()


@pytest.mark.parametrize("bad", ["../x.md", "C:/x.md", "/etc/x.md", "Notas/../../x.md", "C:\\x.md"])
def test_resolve_outside_vault_raises(vault, bad, tmp_path):
    with pytest.raises(ValueError, match="fora do cofre"):
        vault.write(bad, "x")
    assert not (tmp_path / "x.md").exists()


def test_write_and_read(vault):
    vault.write("Notas/a/b.md", "olá")
    assert vault.read("Notas/a/b.md") == "olá"


def test_pending_finds_open_tasks_in_subfolders(vault):
    vault.write("Notas/p/x.md", "- [ ] comprar pão\n- [x] feito\n  - [ ] sub\n")
    items = vault.pending()
    assert ("Notas/p/x.md", "comprar pão") in items
    assert ("Notas/p/x.md", "sub") in items
    assert all(t != "feito" for _, t in items)


def test_conclude_twice_increments_seen(vault):
    vault.conclude("Joga à noite", "baixa", "2026-10-01")
    c = vault.conclude("Joga à noite", "média", "2026-10-02")
    assert c.seen == 2 and c.confidence == "média" and c.date == "2026-10-02"
    assert len(vault.conclusions()) == 1


def test_conclusion_line_format_roundtrip(vault):
    items = [Conclusion("Prefere respostas curtas", "alta", 4, "2026-10-27")]
    vault.save_conclusions(items)
    text = vault.read("Ultron/Memoria/conclusoes.md")
    assert "- Prefere respostas curtas · confiança: alta · visto em 4 chats · 2026-10-27" in text
    assert vault.conclusions() == items


def test_low_confidence_not_in_context(vault):
    for src in ("#1 a", "#2 b"):
        vault.conclude("palpite fraco", "baixa", "2026-10-27", source=src)
        vault.conclude("palpite forte", "alta", "2026-10-27", source=src)
    ctx = vault.fixed_context()
    assert "palpite forte" in ctx and "palpite fraco" not in ctx


def test_fixed_context_limit_keeps_profile(vault):
    vault.remember("Meu nome é Operador")
    items = [Conclusion(f"conclusao numero {i} " + "palavra " * 30, "alta", 1, f"2026-10-{(i % 28) + 1:02d}") for i in range(100)]
    vault.save_conclusions(items)
    ctx = vault.fixed_context(max_words=1500)
    assert len(ctx.split()) <= 1500
    assert "Meu nome é Operador" in ctx


def test_log_creates_daily_file(vault):
    vault.log("abriu VS Code", datetime(2026, 10, 27, 14, 2))
    assert "- 14:02 abriu VS Code" in vault.read("Ultron/Diario/2026-10-27.md")


def test_search_ignores_case_and_accents(vault):
    vault.write("Notas/t.md", "Lista de Pendência da semana")
    res = vault.search("pendencia")
    assert res and res[0][0] == "Notas/t.md"
