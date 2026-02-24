from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from origins_db.discord.webhook import DiscordMessage
from origins_db.hideout.model import Entity, Section
from origins_db.render.text import chunk_for_discord
from origins_db.config import Settings

@dataclass
class MessagePlan:
    channel_key: str
    messages: list[DiscordMessage]

def _embed_base(title: str, url: str, color: int, thumbnail_url: str | None = None) -> dict[str, Any]:
    e: dict[str, Any] = {
        "title": title[:256],
        "url": url,
        "color": color,
        "footer": {"text": "Origins DB • Source : HideoutGacha"},
    }
    if thumbnail_url:
        e["thumbnail"] = {"url": thumbnail_url}
    return e

def _kv_to_lines(items: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for it in items:
        k = (it.get("k") or "").strip()
        v = (it.get("v") or "").strip()
        if k and v:
            lines.append(f"• **{k}** : {v}")
    return "\n".join(lines)

def _cards_to_fields(cards: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Regroupe des cartes par label pour éviter l'effet pavé."""
    groups: dict[str, list[dict[str, str]]] = {}
    for c in cards:
        label = (c.get("label") or "Compétence").strip() or "Compétence"
        groups.setdefault(label, []).append(c)

    fields: list[dict[str, Any]] = []
    for label, lst in groups.items():
        parts: list[str] = []
        for c in lst:
            nm = (c.get("name") or "").strip()
            desc = (c.get("desc") or "").strip()
            if nm and desc:
                parts.append(f"**{nm}**\n{desc}")
            elif desc:
                parts.append(desc)
        value = "\n\n".join(parts).strip()
        for chunk in chunk_for_discord(value, 1000):
            fields.append({"name": label[:256], "value": chunk, "inline": False})
    return fields[:25]

def section_to_text(sec: Section) -> str:
    out: list[str] = []
    for b in sec.blocks:
        if b["type"] == "text":
            out.append(b["text"])
        elif b["type"] == "list":
            out.append("\n".join([f"• {x}" for x in b["items"]]))
        elif b["type"] == "kv":
            out.append(_kv_to_lines(b.get("items", [])))
    return "\n\n".join([x for x in out if x.strip()]).strip()

def _blocks_to_desc_fields(blocks: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    desc_parts: list[str] = []
    fields: list[dict[str, Any]] = []

    for b in blocks:
        t = b.get("type")
        if t == "text":
            desc_parts.append(b.get("text", ""))
        elif t == "list":
            txt = "\n".join([f"• {x}" for x in b.get("items", [])])
            for chunk in chunk_for_discord(txt, 1000):
                fields.append({"name": "Points clés", "value": chunk, "inline": False})
        elif t == "kv":
            title = (b.get("title") or "Stats")
            txt = _kv_to_lines(b.get("items", []))
            for chunk in chunk_for_discord(txt, 1000):
                fields.append({"name": title[:256], "value": chunk, "inline": False})
        elif t == "cards":
            fields.extend(_cards_to_fields(b.get("cards", [])))
        elif t == "subsections":
            for sec in b.get("sections", []):
                val = section_to_text(sec)
                for chunk in chunk_for_discord(val, 1000):
                    fields.append({"name": sec.title[:256], "value": chunk, "inline": False})

    desc = "\n\n".join(chunk_for_discord("\n\n".join(desc_parts), 3800))[:4096]
    return desc, fields[:25]

def build_message_plan(entity: Entity, settings: Settings) -> MessagePlan:
    embeds: list[dict[str, Any]] = []

    # Header : pas de gros screenshot par défaut. L'image du boss/personnage doit être lisible.
    header = _embed_base(entity.title, entity.url, settings.embed_color, thumbnail_url=entity.hero_image)
    
    # Image en grand (perso/boss) si dispo
if entity.hero_image and entity.kind in ("character", "boss_tab"):
    header["image"] = {"url": entity.hero_image}

    if entity.kind == "character":
        header["description"] = "Fiche du personnage (stats + armes + potentiels)."
    elif entity.kind in ("boss_tab", "boss_index"):
        header["description"] = "Infos de boss structurées (résumé + mécaniques + conseils)."
    else:
        header["description"] = "Guide structuré à partir de la page source."

    # Fallback capture uniquement si l'extraction échoue (jointe au 1er message)
    files_first: list[tuple[str, bytes]] = []
    if entity.header_attachment_name and entity.header_attachment_bytes:
        files_first.append((entity.header_attachment_name, entity.header_attachment_bytes))
        header["image"] = {"url": f"attachment://{entity.header_attachment_name}"}

    embeds.append(header)

    # Sections -> embeds
    for sec in entity.sections:
        e = _embed_base(sec.title, entity.url, settings.embed_color, thumbnail_url=entity.hero_image)
        desc, fields = _blocks_to_desc_fields(sec.blocks)
        if desc:
            e["description"] = desc[:4096]
        if fields:
            e["fields"] = fields[:25]
        embeds.append(e)

    # Discord : max 10 embeds / message
    messages: list[DiscordMessage] = []
    i = 0
    msg_index = 0
    while i < len(embeds):
        chunk = embeds[i:i+10]
        files = files_first if msg_index == 0 else []
        messages.append(DiscordMessage(embeds=chunk, files=files))
        i += 10
        msg_index += 1

    return MessagePlan(channel_key=entity.channel_key, messages=messages)
