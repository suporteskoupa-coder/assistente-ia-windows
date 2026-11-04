"""Listar e organizar pastas. Nunca apaga: só move, e guarda registro para desfazer."""
from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

CATEGORIES = {
    "Imagens": "png jpg jpeg gif webp bmp svg",
    "Videos": "mp4 mkv avi mov webm",
    "Audio": "mp3 wav flac ogg m4a",
    "Documentos": "pdf doc docx txt md odt xls xlsx csv ppt pptx",
    "Compactados": "zip rar 7z tar gz",
    "Instaladores": "exe msi",
}
EXT_TO_CAT = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts.split()}
SKIP = {"desktop.ini", "thumbs.db"}
PLAN_ID = re.compile(r"^[0-9a-f]{8}$")


@dataclass
class Move:
    src: str
    dst: str


@dataclass
class Plan:
    id: str
    root: str
    moves: list[Move]


def _plans_dir(home: Path) -> Path:
    d = Path(home) / "planos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 1
    while True:
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def list_folder(path: Path) -> list[dict]:
    out = []
    for p in sorted(Path(path).iterdir(), key=lambda p: p.name.lower()):
        st = p.stat()
        out.append({
            "name": p.name,
            "is_dir": p.is_dir(),
            "size": 0 if p.is_dir() else st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes"),
        })
    return out


def plan_organize(home: Path, path: Path) -> Plan:
    root = Path(path)
    moves = []
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.name.lower() in SKIP:
            continue
        cat = EXT_TO_CAT.get(p.suffix.lower().lstrip("."), "Outros")
        moves.append(Move(str(p), str(root / cat / p.name)))
    plan = Plan(uuid.uuid4().hex[:8], str(root), moves)
    (_plans_dir(home) / f"{plan.id}.json").write_text(
        json.dumps(asdict(plan), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return plan


def describe_plan(plan: Plan) -> str:
    counts: dict[str, int] = {}
    for m in plan.moves:
        cat = Path(m.dst).parent.name
        counts[cat] = counts.get(cat, 0) + 1
    parts = ", ".join(f"{n} → {c}" for c, n in sorted(counts.items()))
    return f"Plano {plan.id}: {len(plan.moves)} arquivos em {plan.root}. {parts or 'nada a mover'}."


def execute_plan(home: Path, plan_id: str) -> str:
    if not PLAN_ID.match(plan_id or ""):
        return f"ERRO: id de plano inválido: {plan_id}"
    f = _plans_dir(home) / f"{plan_id}.json"
    done_file = _plans_dir(home) / f"{plan_id}.done.json"
    if not f.exists():
        return f"ERRO: plano {plan_id} não encontrado."
    if done_file.exists() or done_file.with_suffix(".undone.json").exists():
        return f"ERRO: o plano {plan_id} já foi executado. Crie um plano novo."
    data = json.loads(f.read_text(encoding="utf-8"))
    done, failed = [], []
    try:
        for m in data["moves"]:
            src, dst = Path(m["src"]), Path(m["dst"])
            if not src.exists():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                real = _unique(dst)
                shutil.move(str(src), str(real))
                done.append({"src": str(src), "dst": str(real)})
            except OSError as e:  # arquivo aberto/bloqueado, nome de pasta ocupado etc.
                failed.append(f"{src.name} ({e.__class__.__name__})")
    finally:
        done_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    msg = f"Movi {len(done)} arquivos. Para desfazer, use o plano {plan_id}."
    if failed:
        msg += " Não consegui mover: " + ", ".join(failed) + "."
    return msg


def undo_plan(home: Path, plan_id: str) -> str:
    if not PLAN_ID.match(plan_id or ""):
        return f"ERRO: id de plano inválido: {plan_id}"
    f = _plans_dir(home) / f"{plan_id}.done.json"
    if not f.exists():
        return f"ERRO: plano {plan_id} não encontrado ou não executado."
    done = json.loads(f.read_text(encoding="utf-8"))
    n = 0
    for m in reversed(done):
        src, dst = Path(m["src"]), Path(m["dst"])
        if dst.exists():
            shutil.move(str(dst), str(_unique(src)))
            n += 1
    f.rename(f.with_suffix(".undone.json"))
    return f"Desfeito: {n} arquivos voltaram ao lugar."


def to_trash(home: Path, path: Path) -> Path:
    trash = Path(home) / "Lixeira"
    trash.mkdir(parents=True, exist_ok=True)
    dst = _unique(trash / Path(path).name)
    shutil.move(str(path), str(dst))
    return dst
