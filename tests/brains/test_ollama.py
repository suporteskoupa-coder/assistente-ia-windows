import asyncio
import json

import httpx
import pytest

from tests.tools.helpers import make_cfg
from ultron.brains.ollama import OllamaBrain
from ultron.chats import Message
from ultron.confirm import ConfirmBroker
from ultron.memory import Vault
from ultron.tools.registry import build_registry


def reply(content="", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = [{"function": {"name": n, "arguments": a}} for n, a in tool_calls]
    return httpx.Response(200, json={"message": msg, "done": True})


def setup(tmp_path, responses, broker=None, discord_seen=None):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    launched = []

    def discord_handler(req):
        if discord_seen is not None:
            discord_seen.append(json.loads(req.content))
        return httpx.Response(200, json={})

    reg = build_registry(cfg, v, launched.append, httpx.AsyncClient(transport=httpx.MockTransport(discord_handler)))
    sent = []
    it = iter(responses)

    def ollama(req):
        sent.append(json.loads(req.content))
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    http = httpx.AsyncClient(transport=httpx.MockTransport(ollama))
    b = OllamaBrain(cfg, reg, broker or ConfirmBroker(timeout=0.05), http)
    return b, sent, launched


async def collect(b, text="oi", history=()):
    return [e async for e in b.send(None, list(history), text, "Você é o Ultron.")]


async def test_direct_answer(tmp_path):
    b, sent, _ = setup(tmp_path, [reply("Olá!")])
    evs = await collect(b, history=[Message(1, 1, "user", "antes", ""), Message(2, 1, "assistant", "resp", "")])
    assert [(e.kind, e.text) for e in evs] == [("text", "Olá!"), ("done", "")]
    body = sent[0]
    assert body["model"] == "m" and body["stream"] is False and body["options"]["num_ctx"] == 100
    assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "user"]
    assert body["messages"][-1]["content"] == "oi"


async def test_tool_call_then_text(tmp_path):
    b, sent, launched = setup(tmp_path, [reply(tool_calls=[("abrir_app", {"nome": "vscode"})]), reply("Abri.")])
    evs = await collect(b, "abre o vscode")
    assert [e.kind for e in evs] == ["tool", "text", "done"]
    assert evs[0].data == {"name": "abrir_app", "input": {"nome": "vscode"}}
    assert launched == ["code"]
    tool_msg = sent[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "vscode" in tool_msg["content"]


async def test_denied_confirm_does_not_run(tmp_path):
    seen = []
    b, sent, _ = setup(tmp_path, [reply(tool_calls=[("discord_enviar", {"canal": "geral", "texto": "x"})]), reply("ok")],
                       discord_seen=seen)
    await collect(b)
    assert seen == []
    assert "Negado" in sent[1]["messages"][-1]["content"]


async def test_allowed_confirm_uses_edited_text(tmp_path):
    seen = []
    broker = ConfirmBroker(timeout=2)
    b, _, _ = setup(tmp_path, [reply(tool_calls=[("discord_enviar", {"canal": "geral", "texto": "x"})]), reply("ok")],
                    broker=broker, discord_seen=seen)

    async def approve():
        while not broker.pending():
            await asyncio.sleep(0.001)
        p = broker.pending()[0]
        assert p["action"] == "discord_enviar"
        broker.answer(p["id"], True, edited={"canal": "geral", "texto": "editado"})

    evs, _ = await asyncio.gather(collect(b), approve())
    assert seen == [{"content": "editado"}]
    assert any(e.kind == "confirm" for e in evs) is False


async def test_loop_limit(tmp_path):
    b, _, _ = setup(tmp_path, [reply(tool_calls=[("obsidian_pendencias", {})])] * 20)
    evs = await collect(b)
    assert evs[-1].kind == "error" and "8 passos" in evs[-1].text
    assert sum(e.kind == "tool" for e in evs) == 8


async def test_concluir_not_offered(tmp_path):
    b, sent, _ = setup(tmp_path, [reply("x")])
    await collect(b)
    names = {t["function"]["name"] for t in sent[0]["tools"]}
    assert "concluir" not in names and "abrir_jogo" in names


async def test_unknown_tool_from_model(tmp_path):
    b, sent, _ = setup(tmp_path, [reply(tool_calls=[("concluir", {"texto": "a", "confianca": "alta"})]), reply("x")])
    await collect(b)
    assert sent[1]["messages"][-1]["content"].startswith("ERRO")


async def test_connection_refused(tmp_path):
    b, _, _ = setup(tmp_path, [httpx.ConnectError("recusado")])
    evs = await collect(b)
    assert evs == [evs[0]] and evs[0].kind == "error" and "Ollama não está rodando" in evs[0].text


async def test_model_missing_404(tmp_path):
    b, _, _ = setup(tmp_path, [httpx.Response(404, json={"error": "model 'm' not found"})])
    evs = await collect(b)
    assert evs[0].kind == "error" and "ollama pull m" in evs[0].text


async def test_thinking_tags_never_reach_the_chat(tmp_path):
    b, _, _ = setup(tmp_path, [reply("<think>o usuário quer saber...</think>Olá, criador.")])
    evs = await collect(b)
    assert evs[0].kind == "text" and evs[0].text == "Olá, criador."
