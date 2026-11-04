"""Servidor local: REST + WebSocket para a HUD, e a rota de permissão usada pelo Claude Code."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ultron.confirm import ConfirmBroker
from ultron.service import Ultron

MCP_PREFIX = "mcp__ultron__"


class NewChat(BaseModel):
    brain: str


class Permission(BaseModel):
    tool_name: str
    input: dict = {}
    chat: str | None = None


class Like(BaseModel):
    reply: str


class Answer(BaseModel):
    allow: bool
    edited: dict | None = None


def _status(u: Ultron) -> dict:
    from ultron.tools.steam import find_steam_root, installed_games
    import shutil

    notes = sum(1 for _ in u.vault.root.rglob("*.md")) if u.vault.root.exists() else 0
    diary = u.vault.root / "Ultron" / "Diario" / f"{u.now():%Y-%m-%d}.md"
    actions = sum(1 for l in diary.read_text(encoding="utf-8").splitlines() if l.startswith("- ")) if diary.exists() else 0
    try:
        root = u.cfg.steam_root or find_steam_root()
        games = len(installed_games(root)) if root else 0
    except OSError:
        games = 0
    return {"notes": notes, "actions_today": actions, "games": games,
            "claude": shutil.which(u.cfg.claude_bin) is not None, "ollama": None,
            "brains": list(u.brains)}


LOCAL_HOSTS = ["127.0.0.1", "localhost"]


def create_app(ultron: Ultron, broker: ConfirmBroker, hud_dir: Path, token: str | None = None,
               capturer=None, reminders=None, remote=None, mode=None, system=None) -> FastAPI:
    """`token`: segredo gerado a cada abertura. Só a HUD (que recebe o token na URL) e o servidor MCP
    (que recebe por variável de ambiente) conseguem usar a API. Sites abertos no navegador não."""
    app = FastAPI(title="Ultron")
    app.state.ultron = ultron
    hud_dir = Path(hud_dir)

    if token:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)

        @app.middleware("http")
        async def require_token(request: Request, call_next):
            if request.url.path.startswith("/api/") and request.headers.get("X-Ultron-Token") != token:
                return JSONResponse({"detail": "Acesso negado"}, status_code=403)
            return await call_next(request)

    @app.get("/")
    def index():
        return FileResponse(hud_dir / "index.html")

    app.mount("/hud", StaticFiles(directory=hud_dir), name="hud")

    def chat_or_404(chat_id: int):
        try:
            return ultron.store.get(chat_id)
        except KeyError:
            raise HTTPException(404, "Chat não encontrado")

    @app.get("/api/chats")
    def chats():
        return [asdict(c) for c in ultron.store.list()]

    @app.post("/api/chats")
    def new_chat(body: NewChat):
        try:
            return asdict(ultron.new_chat(body.brain))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/chats/{chat_id}/messages")
    def messages(chat_id: int):
        chat_or_404(chat_id)
        return [asdict(m) for m in ultron.store.messages(chat_id)]

    @app.post("/api/chats/{chat_id}/switch")
    async def switch(chat_id: int, body: NewChat):
        chat_or_404(chat_id)
        try:
            return asdict(await ultron.switch_brain(chat_id, body.brain))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/chats/{chat_id}/close")
    async def close(chat_id: int):
        chat_or_404(chat_id)
        await ultron.close_chat(chat_id)
        return {"ok": True}

    @app.get("/api/system")
    async def system_info():
        if system is None:
            return {"cpu": None, "ram": None, "gpu": None, "vram": None, "game": None}
        return await asyncio.to_thread(system.snapshot)

    @app.get("/api/mode")
    def get_mode():
        return {"brain": mode.get() if mode else "claude"}

    @app.post("/api/mode")
    def set_mode(body: NewChat):
        if mode is None:
            return {"brain": body.brain}
        try:
            return {"brain": mode.set(body.brain)}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/status")
    async def status():
        s = await asyncio.to_thread(_status, ultron)
        try:
            async with httpx.AsyncClient() as h:
                r = await h.get(f"{ultron.cfg.ollama_url.rstrip('/')}/api/tags", timeout=1)
                s["ollama"] = r.status_code == 200
        except httpx.HTTPError:
            s["ollama"] = False
        return s

    @app.post("/api/chats/{chat_id}/like")
    def like(chat_id: int, body: Like):
        """👍 da HUD: guarda a resposta (e a mensagem que a provocou) no banco de exemplos."""
        from ultron.examples import ExampleStore

        chat_or_404(chat_id)
        reply = body.reply.strip()
        msgs = ultron.store.messages(chat_id)
        for i in range(len(msgs) - 1, -1, -1):
            m = msgs[i]
            if m.role == "assistant" and reply and reply in m.content:
                question = next((x.content for x in reversed(msgs[:i]) if x.role == "user"), "")
                if not question:
                    break
                ExampleStore(ultron.vault).add(question, reply, "pc")
                return {"ok": True}
        raise HTTPException(409, "Resposta ainda não salva no chat. Espere terminar e tente de novo.")

    @app.get("/api/conclusions")
    def conclusions():
        order = {"alta": 0, "média": 1, "baixa": 2}
        items = sorted(ultron.vault.conclusions(), key=lambda c: c.date, reverse=True)
        items.sort(key=lambda c: order[c.confidence])
        return [asdict(c) for c in items[:5]]

    @app.post("/api/permission")
    async def permission(body: Permission):
        action = body.tool_name.removeprefix(MCP_PREFIX)
        meta = None
        if remote is not None and remote.is_remote_chat(body.chat):
            if not body.tool_name.startswith(MCP_PREFIX):
                # pelo celular: terminal, edição de arquivos e afins sempre negados
                ultron.vault.log(f"[celular] negado automaticamente: {body.tool_name}", ultron.now())
                return {"allow": False, "input": body.input}
            meta = {"remote": True}
        allow, edited = await broker.request_detail(action, body.input, meta)
        if allow:
            ultron.vault.log(f"[permitido] {action}", ultron.now())
        return {"allow": allow, "input": edited or body.input}

    def scheduler_or_404():
        if reminders is None:
            raise HTTPException(404, "Lembretes indisponíveis")
        return reminders

    @app.get("/api/reminders/active")
    def reminders_active():
        return scheduler_or_404().active()

    @app.post("/api/reminders/{rid}/ok")
    def reminder_ok(rid: int):
        scheduler_or_404().ack(rid)
        return {"ok": True}

    @app.post("/api/reminders/{rid}/snooze")
    def reminder_snooze(rid: int):
        scheduler_or_404().snooze(rid, 10)
        return {"ok": True}

    @app.get("/api/briefing")
    def briefing():
        return scheduler_or_404().briefing(ultron.vault)

    @app.post("/api/screenshot")
    async def screenshot():
        if not ultron.cfg.screen_enabled:
            raise HTTPException(403, "Leitura de tela desligada no ultron.toml ([tela] habilitada).")
        if capturer is None:
            raise HTTPException(500, "Captura de tela indisponível.")
        try:
            shot = await capturer.capture()
        except Exception as e:
            raise HTTPException(500, f"Não consegui capturar a tela: {e}")
        ultron.vault.log(f"[claude] ver_tela {shot.width}x{shot.height}", ultron.now())
        return {"png_b64": shot.png_b64, "width": shot.width, "height": shot.height}

    @app.post("/api/confirm/{request_id}")
    def confirm(request_id: str, body: Answer):
        broker.answer(request_id, body.allow, body.edited)
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        if token:
            origin = socket.headers.get("origin")
            # o Host já foi validado (só 127.0.0.1/localhost); a origem tem de ser a própria HUD
            same_origin = f"http://{socket.headers.get('host', '')}"
            if socket.query_params.get("t") != token or (origin is not None and origin != same_origin):
                await socket.close(code=1008)
                return
        await socket.accept()
        lock = asyncio.Lock()
        queue = broker.subscribe()
        alive = True

        async def push(msg: dict):
            # Se a HUD caiu, segue consumindo a resposta para ela ser salva no chat.
            nonlocal alive
            if not alive:
                return
            try:
                async with lock:
                    await socket.send_json(msg)
            except Exception:
                alive = False

        async def forward_confirms():
            for item in broker.pending():
                await push({"type": "confirm", **item})
            while True:
                item = await queue.get()
                # pedidos de confirmação não têm "type"; avisos (ex.: lembrete) já vêm com o seu
                await push(item if "type" in item else {"type": "confirm", **item})

        async def stream(chat_id: int, text: str):
            try:
                async for ev in ultron.send(chat_id, text):
                    await push({"chat_id": chat_id, **ev.to_dict()})
            except KeyError:
                await push({"chat_id": chat_id, "type": "error", "text": "Chat não encontrado", "data": {}})
            except Exception as e:  # nunca deixa a HUD sem resposta
                await push({"chat_id": chat_id, "type": "error", "text": f"Erro interno: {e}", "data": {}})

        fwd = asyncio.create_task(forward_confirms())
        tasks: set[asyncio.Task] = set()
        try:
            while True:
                msg = await socket.receive_json()
                if msg.get("type") == "send":
                    t = asyncio.create_task(stream(int(msg["chat_id"]), str(msg["text"])))
                    tasks.add(t)
                    t.add_done_callback(tasks.discard)
                elif msg.get("type") == "confirm":
                    broker.answer(msg["id"], bool(msg.get("allow")), msg.get("edited"))
        except WebSocketDisconnect:
            pass
        finally:
            alive = False
            fwd.cancel()
            broker.unsubscribe(queue)
            # as tarefas de resposta continuam até o fim e salvam a mensagem no chat

    return app
