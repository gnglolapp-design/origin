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
        "footer": {"text": "Origins DB • Source : HideoutGacha"}
    }
    if thumbnail_url:
        e["thumbnail"] = {"url": thumbnail_url}
    return e

def section_to_text(sec: Section) -> str:
    out: list[str] = []
    for b in sec.blocks:
        if b["type"] == "text":
            out.append(b["text"])
        elif b["type"] == "list":
            out.append("\n".join([f"• {x}" for x in b["items"]]))
    return "\n\n".join(out).strip()

def _blocks_to_fields(blocks: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    desc_parts: list[str] = []
    fields: list[dict[str, Any]] = []

    for b in blocks:
        if b["type"] == "text":
            desc_parts.append(b["text"])
        elif b["type"] == "list":
            txt = "\n".join([f"• {x}" for x in b["items"]])
            for chunk in chunk_for_discord(txt, 1000):
                fields.append({"name": "Points clés", "value": chunk, "inline": False})
        elif b["type"] == "subsections":
            for sec in b["sections"]:
                val = section_to_text(sec)
                for chunk in chunk_for_discord(val, 1000):
                    fields.append({"name": sec.title[:256], "value": chunk, "inline": False})

    desc = "\n\n".join(chunk_for_discord("\n\n".join(desc_parts), 3800))[:4096]
    return desc, fields

def build_message_plan(entity: Entity, settings: Settings) -> MessagePlan:
    embeds: list[dict[str, Any]] = []

    # Header
    header = _embed_base(entity.title, entity.url, settings.embed_color, thumbnail_url=entity.hero_image)

    header_desc = "Contenu mis en forme depuis la page source."
    header["description"] = header_desc

    # screenshot en image (optionnel)
    files_first: list[tuple[str, bytes]] = []
    if entity.header_attachment_name and entity.header_attachment_bytes:
        files_first.append((entity.header_attachment_name, entity.header_attachment_bytes))
        header["image"] = {"url": f"attachment://{entity.header_attachment_name}"}

    embeds.append(header)

    # Sections
    for sec in entity.sections:
        e = _embed_base(sec.title, entity.url, settings.embed_color, thumbnail_url=entity.hero_image)
        desc, fields = _blocks_to_fields(sec.blocks)
        if desc:
            e["description"] = desc[:4096]
        if fields:
            e["fields"] = fields[:25]
        embeds.append(e)

    # Pagination : max 10 embeds / message
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
