"""Liga as notas antigas do cofre (diário, pessoas, conclusões, memória) com [[links]] para o grafo.

Uso: python -m ultron.link_vault    (pode rodar quantas vezes quiser; só muda o que falta)
"""
from __future__ import annotations

from pathlib import Path

from ultron.memory import CONCL, HUB_LINK, PERFIL, PERSONALITY, PREFS, Vault
from ultron.people import PeopleStore


def _add_hub_after_title(text: str) -> str:
    if HUB_LINK in text:
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join([lines[0], "", HUB_LINK] + lines[1:]) + "\n"
    return f"{HUB_LINK}\n\n{text}"


def link_vault(vault: Vault) -> int:
    vault.ensure()
    changed = 0

    def update(rel: str, new: str) -> None:
        nonlocal changed
        if vault.read(rel) != new:
            vault.write(rel, new)
            changed += 1

    root = vault.root
    for rel in (PERFIL, PREFS, PERSONALITY):
        if (root / rel).exists():
            update(rel, _add_hub_after_title(vault.read(rel)))
    for p in sorted((root / "Ultron" / "Diario").glob("*.md")):
        rel = p.relative_to(root).as_posix()
        update(rel, _add_hub_after_title(vault.read(rel)))
    for p in sorted((root / "Ultron" / "Chats").glob("*.md")):
        rel = p.relative_to(root).as_posix()
        update(rel, _add_hub_after_title(vault.read(rel)))
    people = PeopleStore(vault)
    renamed = {}
    for p in sorted((root / "Ultron" / "Pessoas").glob("*.md")):
        if not p.stem.isdigit():
            continue
        before = p.read_text(encoding="utf-8")
        pid = int(p.stem)
        people.save(pid, people.load(pid))  # formato novo e nome legível
        new = people._existing(pid)
        if new is not None and new.read_text(encoding="utf-8") != before or new != p:
            changed += 1
            renamed[f"Ultron/Pessoas/{pid}|"] = f"{new.stem}|"
    if renamed:  # corrige os links antigos do diário
        for p in sorted((root / "Ultron" / "Diario").glob("*.md")):
            text = p.read_text(encoding="utf-8")
            new_text = text
            for old, new in renamed.items():
                new_text = new_text.replace(f"[[{old}", f"[[{new}")
            if new_text != text:
                p.write_text(new_text, encoding="utf-8")
    if (root / CONCL).exists():
        before = vault.read(CONCL)
        vault.save_conclusions(vault.conclusions())
        after = _add_hub_after_title(vault.read(CONCL))
        vault.write(CONCL, after)
        if after != before:
            changed += 1
    return changed


def main() -> None:
    from ultron.config import load_config, user_home

    cfg = load_config(user_home() / "Ultron" / "ultron.toml")
    n = link_vault(Vault(cfg.vault))
    print(f"Pronto: {n} notas ligadas. Abra o grafo no Obsidian (Ctrl+G).")


if __name__ == "__main__":
    main()
