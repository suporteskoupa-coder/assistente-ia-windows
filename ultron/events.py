"""Eventos trocados entre cérebros, serviço e HUD."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Event:
    kind: str  # text | tool | confirm | done | error | session
    text: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = d.pop("kind")
        return d
