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
    mapping = {}
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

def translate_en_fr(text: str, keep: Iterable[str]=()) -> str:
    # court-circuit
    s = text.strip()
    if not s:
        return s

    protected, mapping = protect_terms(s, keep)

    tok, model = _load()
    batch = tok([protected], return_tensors="pt", padding=True, truncation=True, max_length=512)
    with torch.no_grad():
        gen = model.generate(**batch, max_new_tokens=512)
    out = tok.batch_decode(gen, skip_special_tokens=True)[0]
    out = unprotect_terms(out, mapping)
    return out
