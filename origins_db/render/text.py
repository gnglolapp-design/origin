from __future__ import annotations
from typing import Iterable

def chunk_for_discord(text: str, limit: int) -> list[str]:
    s = (text or "").strip()
    if not s:
        return []
    if len(s) <= limit:
        return [s]

    chunks: list[str] = []
    cur = ""
    for part in s.split("\n"):
        if not cur:
            cur = part
            continue
        if len(cur) + 1 + len(part) <= limit:
            cur += "\n" + part
        else:
            chunks.append(cur.strip())
            cur = part
    if cur:
        chunks.append(cur.strip())

    # Si une ligne dépasse encore, couper brut
    final: list[str] = []
    for c in chunks:
        if len(c) <= limit:
            final.append(c)
        else:
            for j in range(0, len(c), limit):
                final.append(c[j:j+limit])
    return final
