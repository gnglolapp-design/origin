from __future__ import annotations
import re
from functools import lru_cache
from typing import Iterable
import torch
from transformers import MarianMTModel, MarianTokenizer

MODEL_NAME = "Helsinki-NLP/opus-mt-en-fr"

@lru_cache(maxsize=1)
def _load():
    tok = MarianTokenizer.from_pretrained(MODEL_NAME)
    model = MarianMTModel.from_pretrained(MODEL_NAME)
    model.eval()
    return tok, model

def protect_terms(text: str, keep: Iterable[str]) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    out = text
    for i, term in enumerate(sorted(set(keep), key=len, reverse=True)):
        key = f"__KEEP{i}__"
        pattern = re.escape(term)
        out = re.sub(pattern, key, out)
        mapping[key] = term
    return out, mapping

def unprotect_terms(text: str, mapping: dict[str, str]) -> str:
    out = text
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out

def _segment_text(s: str, max_len: int = 420) -> list[str]:
    """Découpe un texte en segments courts pour éviter les troncatures."""
    # segmentation phrases -> paquets
    parts = re.split(r"(?<=[.!?])\s+", s)
    segments: list[str] = []
    cur = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not cur:
            cur = p
            continue
        if len(cur) + 1 + len(p) <= max_len:
            cur += " " + p
        else:
            segments.append(cur)
            cur = p
    if cur:
        segments.append(cur)

    # fallback si une "phrase" est trop longue
    fixed: list[str] = []
    for seg in segments:
        if len(seg) <= 520:
            fixed.append(seg)
        else:
            for i in range(0, len(seg), max_len):
                fixed.append(seg[i:i+max_len])
    return fixed

def translate_en_fr(text: str, keep: Iterable[str]=()) -> str:
    """Traduction EN->FR robuste.

    Marian a une limite de longueur. On découpe donc le texte en segments courts
    et on recolle le résultat.
    """
    s = (text or "").strip()
    if not s:
        return s

    protected, mapping = protect_terms(s, keep)
    segments = _segment_text(protected)

    tok, model = _load()
    out_parts: list[str] = []
    for seg in segments:
        batch = tok([seg], return_tensors="pt", padding=True, truncation=True, max_length=512)
        with torch.no_grad():
            gen = model.generate(**batch, max_new_tokens=512)
        out = tok.batch_decode(gen, skip_special_tokens=True)[0]
        out_parts.append(out)

    out_all = " ".join([x.strip() for x in out_parts if x.strip()])
    out_all = unprotect_terms(out_all, mapping)
    return out_all
