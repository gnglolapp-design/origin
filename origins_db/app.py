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

            prev = store.get(entity.entity_id)
            if prev and prev.get("hash") == entity.content_hash:
                continue

            plan = build_message_plan(entity, settings)

            use_forum = (entity.kind == "character") and ("personnages_forum" in settings.webhooks)
            channel_key = "personnages_forum" if use_forum else plan.channel_key

            wh = router.get(channel_key)
            if wh is None:
                wh = router.get("boss_infos")
                channel_key = "boss_infos"
            if wh is None:
                raise RuntimeError("Aucun webhook valide trouvé (boss_infos manquant).")

            thread_id = None

            if use_forum:
                thread_id = (prev or {}).get("thread_id")

                if thread_id and prev and prev.get("messages"):
                    new_ids = wh.upsert_message_set(prev["messages"], plan.messages, thread_id=thread_id)
                else:
                    first_id, created_thread_id = wh.send_forum_post(entity.title, plan.messages[0])
                    rest_ids = [wh.send(m, thread_id=created_thread_id) for m in plan.messages[1:]]
                    new_ids = [first_id] + rest_ids
                    thread_id = created_thread_id

                # nettoyage: si avant c’était publié ailleurs, tenter suppression (si webhook dispo)
                if prev and prev.get("channel") and prev.get("channel") != channel_key:
                    old_wh = router.get(prev["channel"])
                    if old_wh and prev.get("messages"):
                        for mid in prev["messages"]:
                            try:
                                old_wh.delete(mid)
                            except Exception:
                                pass

            else:
                if prev and prev.get("messages"):
                    new_ids = wh.upsert_message_set(prev["messages"], plan.messages)
                else:
                    new_ids = wh.create_message_set(plan.messages)

            store.set(entity.entity_id, {
                "hash": entity.content_hash,
                "url": entity.url,
                "title": entity.title,
                "channel": channel_key,
                "messages": new_ids,
                "thread_id": thread_id
            })
            store.save()

    finally:
        render.close()
