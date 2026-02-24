from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import requests


def _parse_webhook(url: str) -> tuple[str, str]:
    m = re.search(r"/webhooks/(\d+)/([^/?]+)", url)
    if not m:
        raise ValueError("Webhook Discord invalide.")
    return m.group(1), m.group(2)


@dataclass
class DiscordMessage:
    embeds: list[dict[str, Any]]
    files: list[tuple[str, bytes]]  # (filename, bytes)


class DiscordWebhook:
    def __init__(self, webhook_url: str, username: str) -> None:
        self.webhook_url = webhook_url
        self.webhook_id, self.webhook_token = _parse_webhook(webhook_url)
        self.username = username

    def _request(self, method: str, url: str, **kwargs):
        for _ in range(10):
            r = requests.request(method, url, timeout=90, **kwargs)
            if r.status_code == 429:
                retry = r.json().get("retry_after", 1.0)
                time.sleep(float(retry) + 0.25)
                continue
            if 200 <= r.status_code < 300:
                return r
            if r.status_code in (500, 502, 503, 504):
                time.sleep(1.5)
                continue
            raise RuntimeError(f"Discord API erreur {r.status_code}: {r.text[:800]}")
        raise RuntimeError("Discord API: trop de 429/erreurs temporaires.")

    def send(self, message: DiscordMessage, *, thread_id: str | None = None) -> str:
        params: dict[str, Any] = {"wait": "true"}
        if thread_id:
            params["thread_id"] = thread_id

        data = {
            "username": self.username,
            "allowed_mentions": {"parse": []},
            "embeds": message.embeds,
        }

        if message.files:
            files = {
                f"files[{i}]": (name, content, "application/octet-stream")
                for i, (name, content) in enumerate(message.files)
            }
            payload = {"payload_json": (None, json.dumps(data), "application/json")}
            r = self._request("POST", self.webhook_url, params=params, files={**payload, **files})
        else:
            r = self._request("POST", self.webhook_url, params=params, json=data)

        return r.json()["id"]

    def send_forum_post(self, thread_name: str, message: DiscordMessage) -> Tuple[str, str]:
        # CrÃ©ation dâ€™un post (thread) dans un salon Forum via webhook
        safe_name = (thread_name or "Post").strip()[:100]
        params: dict[str, Any] = {"wait": "true"}

        data = {
            "username": self.username,
            "thread_name": safe_name,
            "allowed_mentions": {"parse": []},
            "embeds": message.embeds,
        }

        if message.files:
            files = {
                f"files[{i}]": (name, content, "application/octet-stream")
                for i, (name, content) in enumerate(message.files)
            }
            payload = {"payload_json": (None, json.dumps(data), "application/json")}
            r = self._request("POST", self.webhook_url, params=params, files={**payload, **files})
        else:
            r = self._request("POST", self.webhook_url, params=params, json=data)

        js = r.json()
        msg_id = js["id"]

        # Discord renvoie le "channel_id" = lâ€™ID du thread crÃ©Ã© (le post forum)
        thread_id = js.get("channel_id") or ""
        if not thread_id:
            raise RuntimeError("CrÃ©ation post forum: thread_id introuvable (channel_id manquant).")
        return msg_id, thread_id

    def edit(self, message_id: str, message: DiscordMessage) -> None:
        url = f"https://discord.com/api/webhooks/{self.webhook_id}/{self.webhook_token}/messages/{message_id}"
        data: dict[str, Any] = {
            "username": self.username,
            "allowed_mentions": {"parse": []},
            "embeds": message.embeds,
        }

        if message.files:
            # Remplacement simple des piÃ¨ces jointes : on indique qu'on ne garde rien
            data["attachments"] = []
            files = {
                f"files[{i}]": (name, content, "application/octet-stream")
                for i, (name, content) in enumerate(message.files)
            }
            payload = {"payload_json": (None, json.dumps(data), "application/json")}
            self._request("PATCH", url, files={**payload, **files})
        else:
            self._request("PATCH", url, json=data)

    def delete(self, message_id: str) -> None:
        url = f"https://discord.com/api/webhooks/{self.webhook_id}/{self.webhook_token}/messages/{message_id}"
        self._request("DELETE", url)

    def create_message_set(self, messages: list[DiscordMessage], *, thread_id: str | None = None) -> list[str]:
        ids: list[str] = []
        for msg in messages:
            ids.append(self.send(msg, thread_id=thread_id))
        return ids

    def upsert_message_set(
        self,
        existing_ids: list[str],
        messages: list[DiscordMessage],
        *,
        thread_id: str | None = None,
    ) -> list[str]:
        new_ids: list[str] = []

        for i, msg in enumerate(messages):
            if i < len(existing_ids):
                self.edit(existing_ids[i], msg)
                new_ids.append(existing_ids[i])
            else:
                new_ids.append(self.send(msg, thread_id=thread_id))

        # supprime les anciens messages en trop
        for j in range(len(messages), len(existing_ids)):
            self.delete(existing_ids[j])

        return new_ids


class WebhookRouter:
    def __init__(self, webhooks: dict[str, str], username: str) -> None:
        self._map = {k: DiscordWebhook(v, username) for k, v in webhooks.items()}

    def get(self, key: str) -> Optional[DiscordWebhook]:
        return self._map.get(key)
