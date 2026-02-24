from __future__ import annotations
from dataclasses import dataclass
import os
import json

@dataclass
class Settings:
    base_url: str
    state_path: str
    webhooks: dict[str, str]
    webhook_name: str
    embed_color: int

    # termes volontairement gardés (pas traduit)
    keep_terms: tuple[str, ...] = ("Burst", "Tag", "AOE", "DPS", "PvE", "PvP")

    @staticmethod
    def from_env() -> "Settings":
        base_url = "https://hideoutgacha.com/games/seven-deadly-sins-origin"
        state_path = os.getenv("STATE_PATH", "data/state.json")

        wh_json = os.getenv("DISCORD_WEBHOOKS", "").strip()
        if not wh_json:
            raise SystemExit("Secret DISCORD_WEBHOOKS manquant (JSON).")
        webhooks = json.loads(wh_json)

        webhook_name = os.getenv("WEBHOOK_NAME", "Origins DB").strip() or "Origins DB"
        color_hex = os.getenv("EMBED_COLOR", "C99700").strip().lstrip("#")
        embed_color = int(color_hex, 16)

        return Settings(
            base_url=base_url,
            state_path=state_path,
            webhooks=webhooks,
            webhook_name=webhook_name,
            embed_color=embed_color,
        )
