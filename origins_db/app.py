import os
import json
from origins_db.config import Settings
from origins_db.hideout.discover import discover_all
from origins_db.hideout.fetch import RenderClient
from origins_db.hideout.extract import extract_entity
from origins_db.render.plan import build_message_plan
from origins_db.state import StateStore
from origins_db.discord.webhook import WebhookRouter

def run() -> None:
    settings = Settings.from_env()

    store = StateStore(settings.state_path)
    store.load()

    router = WebhookRouter(settings.webhooks, settings.webhook_name)

    render = RenderClient(headless=True)

    try:
        targets = discover_all(render, settings.base_url)
        for target in targets:
            entity = extract_entity(render, target, settings)
            if entity is None:
                continue

            entity_id = entity.entity_id
            content_hash = entity.content_hash

            prev = store.get(entity_id)
            if prev and prev.get("hash") == content_hash:
                continue  # pas de changement

            plan = build_message_plan(entity, settings)

            # publier / éditer
            channel_key = plan.channel_key
            wh = router.get(channel_key)

            if wh is None:
                # fallback : boss sans salon dédié -> boss_infos
                wh = router.get("boss_infos")
                channel_key = "boss_infos"

            if prev and prev.get("messages"):
                # éditer les messages existants (et ajuster si le nombre change)
                new_message_ids = wh.upsert_message_set(prev["messages"], plan.messages)
            else:
                new_message_ids = wh.create_message_set(plan.messages)

            store.set(entity_id, {
                "hash": content_hash,
                "url": entity.url,
                "title": entity.title,
                "channel": channel_key,
                "messages": new_message_ids
            })
            store.save()

    finally:
        render.close()
