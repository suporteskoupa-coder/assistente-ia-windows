import httpx
import pytest

from tests.tools.helpers import make_cfg
from ultron.memory import Vault
from ultron.tools.registry import build_registry, confirm_tool_names

EXPECTED = {
    "abrir_app", "abrir_jogo", "ativar_modo", "listar_pasta", "planejar_organizacao",
    "organizar_pasta", "desfazer_organizacao", "obsidian_ler", "obsidian_buscar",
    "obsidian_escrever", "obsidian_pendencias", "lembrar", "concluir", "discord_enviar",
    "lembrete_criar", "lembrete_listar", "lembrete_cancelar", "definir_status",
}


@pytest.fixture
def reg(tmp_path):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    calls = []
    r = build_registry(cfg, v, calls.append, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
    r.launched = calls
    return r


def test_all_tools_present(reg):
    assert {t.name for t in reg.all()} == EXPECTED


def test_confirm_tools(reg):
    assert set(confirm_tool_names(reg)) == {"organizar_pasta", "desfazer_organizacao", "discord_enviar"}


def test_local_excludes_concluir(reg):
    names = {t.name for t in reg.local()}
    assert "concluir" not in names and "abrir_jogo" in names


def test_schemas_are_objects(reg):
    for t in reg.all():
        assert t.schema["type"] == "object"
        assert t.description


async def test_call_runs_tool(reg):
    out = await reg.call("abrir_app", {"nome": "vscode"})
    assert reg.launched == ["code"] and "vscode" in out


async def test_call_exception_becomes_error_text(reg):
    out = await reg.call("listar_pasta", {"caminho": "/nao/existe/mesmo"})
    assert out.startswith("ERRO:")


async def test_call_missing_args_is_error(reg):
    assert (await reg.call("abrir_app", {})).startswith("ERRO:")


async def test_call_unknown_tool(reg):
    assert (await reg.call("formatar_disco", {})).startswith("ERRO:")


async def test_obsidian_write_outside_vault_is_error(reg, tmp_path):
    out = await reg.call("obsidian_escrever", {"caminho": "../x.md", "conteudo": "x"})
    assert out.startswith("ERRO:") and not (tmp_path / "x.md").exists()


async def test_concluir_and_lembrar(reg):
    await reg.call("lembrar", {"fato": "Meu servidor é Os Cria"})
    await reg.call("concluir", {"texto": "Joga à noite", "confianca": "média"})
    ctx = (await reg.call("obsidian_ler", {"caminho": "Ultron/Memoria/perfil.md"}))
    assert "Os Cria" in ctx
    assert "Joga à noite" in await reg.call("obsidian_ler", {"caminho": "Ultron/Memoria/conclusoes.md"})


async def test_pendencias_formatting(reg):
    await reg.call("obsidian_escrever", {"caminho": "Notas/a.md", "conteudo": "- [ ] estudar"})
    out = await reg.call("obsidian_pendencias", {})
    assert "estudar" in out and "Notas/a.md" in out
