"""Ferramentas do cofre Obsidian e da memória."""
from __future__ import annotations

from datetime import date

from ultron.memory import CONFIDENCES, Vault
from ultron.tools.registry import Tool, obj, s


def tools(vault: Vault, chat_source: str | None = None) -> list[Tool]:
    def buscar(consulta: str) -> str:
        res = vault.search(consulta)
        return "\n".join(f"{rel}: {trecho}" for rel, trecho in res) or "Nada encontrado."

    def escrever(caminho: str, conteudo: str) -> str:
        vault.write(caminho, conteudo)
        return f"Nota salva: {caminho}"

    def pendencias() -> str:
        items = vault.pending()
        return "\n".join(f"- {t}  ({rel})" for rel, t in items) or "Nenhuma pendência aberta."

    def lembrar(fato: str) -> str:
        vault.remember(fato)
        return "Anotado no perfil."

    def concluir(texto: str, confianca: str) -> str:
        c = vault.conclude(texto, confianca, date.today().isoformat(), source=chat_source)
        return f"Conclusão registrada (visto em {c.seen} chats, confiança {c.confidence})."

    return [
        Tool("obsidian_ler", "Lê uma nota do cofre (caminho relativo ao cofre).",
             obj({"caminho": s("Ex.: Notas/ideias.md")}, ["caminho"]), lambda caminho: vault.read(caminho)),
        Tool("obsidian_buscar", "Busca texto nas notas do cofre.",
             obj({"consulta": s("Texto a buscar")}, ["consulta"]), buscar),
        Tool("obsidian_escrever", "Cria ou substitui uma nota dentro do cofre.",
             obj({"caminho": s("Caminho relativo, ex.: Notas/resumo.md"), "conteudo": s("Markdown")}, ["caminho", "conteudo"]),
             escrever),
        Tool("obsidian_pendencias", "Lista as tarefas abertas (- [ ]) de todas as notas.", obj(), pendencias),
        Tool("lembrar", "Guarda um fato que o usuário pediu para lembrar.",
             obj({"fato": s("O fato, em uma frase")}, ["fato"]), lembrar),
        Tool("concluir", "Registra uma conclusão (hipótese) sobre o usuário a partir de um padrão observado.",
             obj({"texto": s("A conclusão, em uma frase"), "confianca": s("Confiança", enum=list(CONFIDENCES))}, ["texto", "confianca"]),
             concluir, local=False),
    ]
