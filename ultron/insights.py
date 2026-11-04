"""Análise automática: a cada poucas conversas, o Ultron extrai fatos duradouros e escreve um
pensamento (na voz dele) sobre a pessoa. Roda numa chamada separada, sem ferramentas, em segundo plano."""
from __future__ import annotations

import json

ANALYZE_EVERY = 5
CONFIDENCES = ("baixa", "média", "alta")
EMPTY = {"fatos": [], "esquecer": [], "pensamento": ""}

ANALYZE_SYSTEM = """Analise as conversas abaixo entre o Ultron e {who}.
Responda SOMENTE um JSON neste formato, sem nenhum texto fora dele:
{{"fatos": [{{"texto": "...", "confianca": "baixa|média|alta"}}], "esquecer": ["..."], "pensamento": "..."}}

fatos: coisas duradouras que valem lembrar sobre {who}: gostos, jogos, funções, times, rotina, apelidos,
opiniões que a pessoa declarou, planos. Uma frase curta cada. Só o que está nas conversas; não invente.
Nunca anote saúde, família, sexualidade, religião, política, endereço, documentos, senhas ou contatos.
Use "alta" só quando a pessoa disse claramente; "baixa" quando é dedução.
esquecer: fatos já conhecidos (lista abaixo) que as conversas contradizem, com o texto exato.
pensamento: UMA frase curta na voz do Ultron (teatral, sarcástico, vaidoso) sobre {who}, como um diário
secreto. É brincadeira: nada de ofensa pessoal, nada sobre aparência, família ou características pessoais.

# Fatos já conhecidos sobre {who}
{known}"""


def _redact(text: str) -> str:
    from ultron.server_replies import redact

    return redact(text)


def parse_insights(raw: str) -> dict:
    """Extrai o JSON da resposta (tolera texto ou ``` em volta). Resposta inválida → nada."""
    start, end = (raw or "").find("{"), (raw or "").rfind("}")
    if start < 0 or end <= start:
        return dict(EMPTY)
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return dict(EMPTY)
    if not isinstance(data, dict):
        return dict(EMPTY)
    fatos = []
    for f in data.get("fatos") or []:
        if not isinstance(f, dict):
            continue
        texto = " ".join(str(f.get("texto", "")).split())[:200]
        conf = str(f.get("confianca", "")).strip().lower().replace("media", "média")
        if texto and conf in CONFIDENCES:
            fatos.append({"texto": _redact(texto), "confianca": conf})
    esquecer = [" ".join(str(x).split()) for x in (data.get("esquecer") or []) if str(x).strip()]
    pensamento = _redact(" ".join(str(data.get("pensamento") or "").split()))[:300]
    return {"fatos": fatos[:10], "esquecer": esquecer[:10], "pensamento": pensamento}
