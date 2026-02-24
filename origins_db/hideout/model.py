from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Section:
    title: str
    blocks: list[dict[str, Any]]  # {"type": "text"|"list"|"table"|"subsections", ...}
    images: list[str] = field(default_factory=list)  # URLs d'images (si utiles)

@dataclass
class Entity:
    entity_id: str
    kind: str
    url: str
    title: str
    channel_key: str
    hero_image: str | None
    sections: list[Section]
    content_hash: str

    # média optionnel à joindre au 1er message (ex : capture du bloc principal)
    header_attachment_name: str | None = None
    header_attachment_bytes: bytes | None = None
