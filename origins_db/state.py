from __future__ import annotations
import json
import os
from typing import Any

class StateStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self.data: dict[str, Any] = {}

    def load(self) -> None:
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                try:
                    self.data = json.load(f)
                except json.JSONDecodeError:
                    self.data = {}
        else:
            self.data = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2, sort_keys=True)

    def get(self, entity_id: str):
        return self.data.get(entity_id)

    def set(self, entity_id: str, value):
        self.data[entity_id] = value
