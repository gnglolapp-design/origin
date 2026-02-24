from __future__ import annotations

import hashlib
import json
import re
from bs4 import BeautifulSoup, Tag

from origins_db.hideout.fetch import RenderClient
from origins_db.hideout.model import Entity, Section
from origins_db.hideout.translate import translate_en_fr
from origins_db.config import Settings

TAB_LABELS_CHARACTER = ["Basic Info", "Weapons", "Armor", "Potentials"]

# Libellés connus sur la page Armes
CARD_LABEL_FR: dict[str, str] = {
    "Passive": "Passif",
    "Normal Attack": "Attaque normale",
    "Special Attack": "Attaque spéciale",
    "Normal Skill": "Compétence normale",
    "Attack Skill": "Compétence d’attaque",
}

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s

def _normalize_img(src: str) -> str:
    if not src:
        return src
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://hideoutgacha.com" + src
    return src

def _pick_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    return _clean(h1.get_text(" ", strip=True)) if h1 else "Sans titre"

def _pick_hero_image(soup: BeautifulSoup, title_hint: str | None = None) -> str | None:
    """Choisit une image "portrait" plausible.

    Heuristique : privilégie les images dans <main>, avec alt proche du titre,
    ou dont l'URL contient des segments utiles.
    """
    title_hint = (title_hint or "").strip().lower()

    main = soup.find("main") or soup
    imgs = main.select("img[src]")
    if not imgs:
        imgs = soup.select("img[src]")

    best = None
    best_score = -1
    for img in imgs:
        src = _normalize_img(img.get("src", ""))
        alt = (img.get("alt") or "").strip().lower()
        score = 0
        if title_hint and alt and title_hint in alt:
            score += 5
        if any(x in src.lower() for x in ("character", "characters", "boss", "origin")):
            score += 2
        if any(x in src.lower() for x in ("portrait", "thumb", "icon", "render", "art")):
            score += 1
        # évite les petites icônes UI
        if any(x in src.lower() for x in ("logo", "favicon", "discord", "kofi")):
            score -= 5
        if score > best_score:
            best_score = score
            best = src

    return best if best_score >= 0 else None

def _find_clickable_by_text(page, label: str):
    # texte exact ou partiel
    return page.locator(f"text={label}").first

def _close_cookie_banner(page) -> None:
    # évite que le bandeau masque des blocs
    for txt in ("Accept", "J'accepte", "Accepter"):
        try:
            loc = page.locator(f"text={txt}").first
            if loc.count() > 0:
                loc.click(timeout=1500)
                page.wait_for_timeout(200)
                return
        except Exception:
            pass

def _main_inner_text(page) -> str:
    try:
        main = page.locator("main").first
        if main.count() > 0:
            return _clean(main.inner_text())
    except Exception:
        pass
    return _clean(page.inner_text())

def _main_screenshot_bytes(page) -> bytes | None:
    # uniquement en fallback (si extraction textuelle échoue)
    try:
        main = page.locator("main").first
        if main.count() == 0:
            return None
        return main.screenshot(type="jpeg", quality=70)
    except Exception:
        return None

# ----------------------------
# Extraction via __NEXT_DATA__
# ----------------------------

def _parse_next_data(html: str) -> dict | None:
    try:
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("script", id="__NEXT_DATA__")
        if tag and tag.string:
            return json.loads(tag.string)
    except Exception:
        return None
    return None

def _iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _iter_dicts(x)

def _pick_first_str(d: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None

def _find_best_payload(next_data: dict, scorer) -> dict | None:
    best = None
    best_score = -1
    for d in _iter_dicts(next_data):
        s = scorer(d)
        if s > best_score:
            best_score = s
            best = d
    return best if best_score > 0 else None

def _score_character(d: dict) -> int:
    score = 0
    # nom
    if isinstance(d.get("name"), str) or isinstance(d.get("title"), str):
        score += 1
    # armes
    for k, v in d.items():
        if isinstance(k, str) and "weapon" in k.lower() and isinstance(v, list) and v and all(isinstance(x, dict) for x in v[:2]):
            score += 4
    # potentiels / armure
    for key in d.keys():
        if isinstance(key, str) and "potential" in key.lower():
            score += 2
        if isinstance(key, str) and "armor" in key.lower():
            score += 1
    # stats
    for key in d.keys():
        if isinstance(key, str) and "stat" in key.lower():
            score += 1
    return score

def _score_boss(d: dict) -> int:
    score = 0
    if isinstance(d.get("name"), str) or isinstance(d.get("title"), str):
        score += 1
    for key, v in d.items():
        if isinstance(key, str) and key.lower() in ("overview", "mechanics", "strategy", "tips") and isinstance(v, (str, list, dict)):
            score += 2
    # gros bloc texte
    if any(isinstance(v, str) and len(v) > 250 for v in d.values()):
        score += 1
    return score

def _as_kv_list(stats_obj) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(stats_obj, dict):
        for k, v in stats_obj.items():
            if isinstance(v, (int, float, str)):
                out.append((_clean(str(k)), _clean(str(v))))
    elif isinstance(stats_obj, list):
        for it in stats_obj:
            if isinstance(it, dict):
                k = _pick_first_str(it, ("name", "label", "stat"))
                v = it.get("value") if "value" in it else _pick_first_str(it, ("val", "amount"))
                if k and v is not None:
                    out.append((_clean(k), _clean(str(v))))
    # filtrage minimal
    out = [(k, v) for k, v in out if k and v and len(k) <= 32]
    return out

def _collect_cards(obj, default_label: str | None = None) -> list[dict]:
    """Récupère des 'cartes' (nom + description) dans une structure JSON."""
    cards: list[dict] = []

    def walk(o, label: str | None):
        if isinstance(o, dict):
            name = _pick_first_str(o, ("name", "title"))
            desc = _pick_first_str(o, ("description", "desc", "text", "effect"))
            typ = _pick_first_str(o, ("type", "category", "kind"))
            if name and desc:
                cards.append({
                    "label": _clean(typ or label or default_label or ""),
                    "name": _clean(name),
                    "desc": _clean(desc),
                })
            for k, v in o.items():
                if isinstance(v, (dict, list)):
                    walk(v, _clean(str(k)))
        elif isinstance(o, list):
            for it in o:
                walk(it, label)

    walk(obj, default_label)

    # dédoublonnage simple
    seen = set()
    uniq: list[dict] = []
    for c in cards:
        key = (c.get("label"), c.get("name"), c.get("desc"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq

def _label_to_fr(label: str, settings: Settings) -> str:
    l = _clean(label)
    if not l:
        return ""
    if l in CARD_LABEL_FR:
        return CARD_LABEL_FR[l]
    # camelCase -> mots
    l2 = re.sub(r"([a-z])([A-Z])", r"\1 \2", l)
    l2 = l2.replace("_", " ")
    l2 = _clean(l2)
    # traduction courte
    return translate_en_fr(l2, settings.keep_terms)

def _extract_character_from_next(next_data: dict, title_fallback: str, settings: Settings) -> tuple[str | None, list[Section]]:
    payload = _find_best_payload(next_data, _score_character)
    if not payload:
        return None, []

    name = _pick_first_str(payload, ("name", "title")) or title_fallback

    # image
    hero = _pick_first_str(payload, ("image", "portrait", "thumbnail", "icon", "art", "render"))
    if hero:
        hero = _normalize_img(hero)

    # stats
    stats_obj = None
    for k, v in payload.items():
        if isinstance(k, str) and "stat" in k.lower():
            stats_obj = v
            break
    stats_kv = _as_kv_list(stats_obj) if stats_obj is not None else []

    # weapons list
    weapons_list = None
    for k, v in payload.items():
        if isinstance(k, str) and "weapon" in k.lower() and isinstance(v, list) and v and all(isinstance(x, dict) for x in v[:1]):
            weapons_list = v
            break

    sections: list[Section] = []

    # Profil
    prof_blocks: list[dict] = []
    if stats_kv:
        prof_blocks.append({"type": "kv", "title": "Stats", "items": [{"k": k, "v": v} for k, v in stats_kv]})

    # infos simples éventuelles
    info_keys = [
        ("Element", ("element", "attribute")),
        ("Rôle", ("role", "class", "archetype")),
        ("Rareté", ("rarity",)),
    ]
    infos: list[str] = []
    for label_fr, keys in info_keys:
        val = None
        for key in keys:
            if isinstance(payload.get(key), str):
                val = payload.get(key)
                break
        if val:
            infos.append(f"**{label_fr}** : {translate_en_fr(_clean(str(val)), settings.keep_terms)}")
    if infos:
        prof_blocks.insert(0, {"type": "text", "text": "\n".join(infos)})

    if prof_blocks:
        sections.append(Section(title="Profil", blocks=prof_blocks, images=[]))

    # Armes
    if weapons_list:
        for w in weapons_list[:8]:
            wname = _pick_first_str(w, ("name", "title")) or "Arme"
            welem = _pick_first_str(w, ("element", "attribute", "type"))
            cards = _collect_cards(w)

            # nettoyage / tri : regrouper par label connu quand possible
            norm_cards: list[dict] = []
            for c in cards:
                label = c.get("label") or ""
                label_fr = _label_to_fr(label, settings)
                norm_cards.append({
                    "label": label_fr or "Compétence",
                    "name": c.get("name") or "",
                    "desc": translate_en_fr(c.get("desc") or "", settings.keep_terms),
                })

            header_lines = []
            if welem:
                header_lines.append(f"**Affinité** : {translate_en_fr(_clean(str(welem)), settings.keep_terms)}")

            blocks: list[dict] = []
            if header_lines:
                blocks.append({"type": "text", "text": "\n".join(header_lines)})
            if norm_cards:
                blocks.append({"type": "cards", "cards": norm_cards})

            sections.append(Section(title=f"Arme : {wname}", blocks=blocks, images=[]))

    # Potentiels
    pot_list = None
    for k, v in payload.items():
        if isinstance(k, str) and "potential" in k.lower() and isinstance(v, list):
            pot_list = v
            break
    if pot_list:
        items = []
        for p in pot_list[:120]:
            if isinstance(p, str):
                items.append(translate_en_fr(_clean(p), settings.keep_terms))
            elif isinstance(p, dict):
                pn = _pick_first_str(p, ("name", "title"))
                pd = _pick_first_str(p, ("description", "desc", "effect", "text"))
                if pn and pd:
                    items.append(f"**{translate_en_fr(_clean(pn), settings.keep_terms)}** — {translate_en_fr(_clean(pd), settings.keep_terms)}")
                elif pn:
                    items.append(translate_en_fr(_clean(pn), settings.keep_terms))
        if items:
            sections.append(Section(title="Potentiels", blocks=[{"type": "list", "items": items}], images=[]))

    # Armure
    armor_list = None
    for k, v in payload.items():
        if isinstance(k, str) and "armor" in k.lower() and isinstance(v, list):
            armor_list = v
            break
    if armor_list:
        items = []
        for a in armor_list[:120]:
            if isinstance(a, str):
                items.append(translate_en_fr(_clean(a), settings.keep_terms))
            elif isinstance(a, dict):
                an = _pick_first_str(a, ("name", "title"))
                ad = _pick_first_str(a, ("description", "desc", "effect", "text"))
                if an and ad:
                    items.append(f"**{translate_en_fr(_clean(an), settings.keep_terms)}** — {translate_en_fr(_clean(ad), settings.keep_terms)}")
                elif an:
                    items.append(translate_en_fr(_clean(an), settings.keep_terms))
        if items:
            sections.append(Section(title="Armure", blocks=[{"type": "list", "items": items}], images=[]))

    return hero, sections

# ----------------------------
# Boss via __NEXT_DATA__
# ----------------------------

def _value_to_blocks(val, settings: Settings) -> list[dict]:
    blocks: list[dict] = []
    if val is None:
        return blocks
    if isinstance(val, str):
        t = _clean(val)
        if t:
            blocks.append({"type": "text", "text": translate_en_fr(t, settings.keep_terms)})
        return blocks
    if isinstance(val, list):
        items: list[str] = []
        for it in val:
            if isinstance(it, str):
                s = _clean(it)
                if s:
                    items.append(translate_en_fr(s, settings.keep_terms))
            elif isinstance(it, dict):
                nm = _pick_first_str(it, ("name", "title", "label"))
                ds = _pick_first_str(it, ("description", "desc", "text", "effect"))
                if nm and ds:
                    items.append(f"**{translate_en_fr(_clean(nm), settings.keep_terms)}** — {translate_en_fr(_clean(ds), settings.keep_terms)}")
                elif nm:
                    items.append(translate_en_fr(_clean(nm), settings.keep_terms))
        if items:
            blocks.append({"type": "list", "items": items})
        return blocks
    if isinstance(val, dict):
        # tente d'extraire du texte et des listes
        text_bits: list[str] = []
        list_bits: list[str] = []
        for k, v in val.items():
            if isinstance(v, str) and len(v.strip()) > 0:
                key = _clean(str(k))
                if key and key.lower() not in ("id", "slug", "image", "icon"): 
                    text_bits.append(f"**{translate_en_fr(key, settings.keep_terms)}** : {translate_en_fr(_clean(v), settings.keep_terms)}")
                else:
                    text_bits.append(translate_en_fr(_clean(v), settings.keep_terms))
            elif isinstance(v, list):
                for it in v:
                    if isinstance(it, str) and it.strip():
                        list_bits.append(translate_en_fr(_clean(it), settings.keep_terms))
        if list_bits:
            blocks.append({"type": "list", "items": list_bits[:200]})
        if text_bits:
            blocks.append({"type": "text", "text": "\n".join(text_bits)})
        return blocks
    return blocks

def _extract_boss_from_next(next_data: dict, boss_label: str, settings: Settings) -> tuple[str | None, list[Section]]:
    want = (boss_label or "").strip().lower()
    best = None
    best_score = -1
    for d in _iter_dicts(next_data):
        nm = _pick_first_str(d, ("name", "title"))
        if not nm:
            continue
        if want and want not in nm.lower():
            continue
        s = _score_boss(d) + 3
        if s > best_score:
            best_score = s
            best = d
    if not best:
        return None, []

    hero = _pick_first_str(best, ("image", "portrait", "thumbnail", "icon", "art", "render"))
    if hero:
        hero = _normalize_img(hero)

    key_order = [
        ("overview", "Résumé"),
        ("mechanics", "Mécaniques"),
        ("strategy", "Stratégies"),
        ("tips", "Conseils"),
        ("phases", "Phases"),
        ("rewards", "Récompenses"),
    ]

    sections: list[Section] = []
    for k, title_fr in key_order:
        if k in best:
            blocks = _value_to_blocks(best.get(k), settings)
            if blocks:
                sections.append(Section(title=title_fr, blocks=blocks, images=[]))

    # si rien n'a matché : fallback sur les gros textes du payload
    if not sections:
        big = []
        for v in best.values():
            if isinstance(v, str) and len(v) > 180:
                big.append(translate_en_fr(_clean(v), settings.keep_terms))
        if big:
            sections.append(Section(title="Résumé", blocks=[{"type": "text", "text": "\n\n".join(big[:3])}], images=[]))

    return hero, sections

def _extract_sections_generic_from_html(html: str, settings: Settings) -> list[Section]:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup

    sections: list[Section] = []

    cur_title: str | None = None
    cur_paras: list[str] = []
    cur_bullets: list[str] = []

    def flush():
        nonlocal cur_title, cur_paras, cur_bullets
        if not cur_title:
            return
        blocks: list[dict] = []

        if cur_paras:
            txt = " ".join([_clean(x) for x in cur_paras if _clean(x)])
            txt = translate_en_fr(txt, settings.keep_terms)
            if txt:
                blocks.append({"type": "text", "text": txt})

        if cur_bullets:
            items = []
            for b in cur_bullets:
                b = _clean(b).lstrip("•").strip()
                if b:
                    items.append(translate_en_fr(b, settings.keep_terms))
            if items:
                blocks.append({"type": "list", "items": items[:200]})

        if blocks:
            sections.append(Section(title=translate_en_fr(_clean(cur_title), settings.keep_terms), blocks=blocks, images=[]))

        cur_title = None
        cur_paras = []
        cur_bullets = []

    # texte d’intro avant le 1er titre
    intro_parts: list[str] = []
    for node in main.find_all(["h2", "h3", "h4", "p"], recursive=True):
        if node.name in ("h2", "h3", "h4"):
            break
        if node.name == "p":
            t = _clean(node.get_text(" ", strip=True))
            if t:
                intro_parts.append(t)
    if intro_parts:
        sections.append(Section(
            title="Introduction",
            blocks=[{"type": "text", "text": translate_en_fr(" ".join(intro_parts), settings.keep_terms)}],
            images=[]
        ))

    # parcours en ordre des titres + contenu
    for node in main.find_all(["h2", "h3", "h4", "p", "li"], recursive=True):
        if node.name in ("h2", "h3", "h4"):
            flush()
            cur_title = _clean(node.get_text(" ", strip=True))
            continue

        if not cur_title:
            continue

        if node.name == "p":
            t = _clean(node.get_text(" ", strip=True))
            if t:
                cur_paras.append(t)

        elif node.name == "li":
            t = _clean(node.get_text(" ", strip=True))
            if t:
                cur_bullets.append(t)

    flush()

    # fallback si vraiment vide
    if not sections:
        text = _clean((main).get_text(" ", strip=True))
        if text:
            sections.append(Section(
                title="Résumé",
                blocks=[{"type": "text", "text": translate_en_fr(text, settings.keep_terms)}],
                images=[]
            ))
    return sections

# ----------------------------
# Point d'entrée
# ----------------------------

def extract_entity(render: RenderClient, target, settings: Settings) -> Entity | None:
    page = render.goto(target.url)
    _close_cookie_banner(page)

    html_full = page.content()
    soup = BeautifulSoup(html_full, "lxml")

    title = _pick_title(soup)

    # hero image : tentative via HTML (améliorée) + possible override via next-data
    hero_img = _pick_hero_image(soup, title_hint=title)

    sections: list[Section] = []
    header_shot = None
    header_name = None

    next_data = _parse_next_data(html_full)

    if target.kind == "character":
        # extraction structurée (priorité)
        if next_data:
            hero_nd, sections_nd = _extract_character_from_next(next_data, title, settings)
            if sections_nd:
                sections = sections_nd
            if hero_nd:
                hero_img = hero_nd

        # fallback DOM : on tente de récupérer au moins l'onglet Armes + Stats
        if not sections:
            # Stats (Basic Info)
            try:
                loc = _find_clickable_by_text(page, "Basic Info")
                if loc.count() > 0:
                    loc.click(timeout=10_000)
                    page.wait_for_timeout(400)
            except Exception:
                pass

            basic_text = _main_inner_text(page)
            stats_lines: list[str] = []
            # heuristique "Stat 123" par regex
            # extraction plus simple par regex
            for m in re.finditer(r"\b([A-Za-z][A-Za-z \-]{1,24})\s*(\d{2,7})\b", basic_text):
                k = _clean(m.group(1))
                v = m.group(2)
                if k.lower() in ("home", "games", "about", "accept"):
                    continue
                if any(x in k.lower() for x in ("cookie", "privacy")):
                    continue
                stats_lines.append(f"**{translate_en_fr(k, settings.keep_terms)}** : {v}")
            if stats_lines:
                sections.append(Section(title="Profil", blocks=[{"type": "text", "text": "\n".join(stats_lines[:25])}], images=[]))

            # Armes
            try:
                loc = _find_clickable_by_text(page, "Weapons")
                if loc.count() > 0:
                    loc.click(timeout=10_000)
                    page.wait_for_timeout(500)
            except Exception:
                pass

            # découvre des boutons "arme" (courts, hors onglets)
            weapon_buttons = []
            try:
                cands = page.locator("main button, main [role=button]").all()
                for el in cands:
                    try:
                        txt = _clean(el.inner_text())
                    except Exception:
                        continue
                    if not txt or len(txt) > 32:
                        continue
                    if txt in TAB_LABELS_CHARACTER:
                        continue
                    if txt.lower() in ("accept",):
                        continue
                    # très probable : armes
                    weapon_buttons.append((txt, el))
            except Exception:
                weapon_buttons = []

            seen = set()
            for wname, el in weapon_buttons:
                if wname in seen:
                    continue
                seen.add(wname)
                try:
                    el.click(timeout=5000)
                    page.wait_for_timeout(350)
                except Exception:
                    pass

                t = _main_inner_text(page)
                # parse cartes via marqueurs connus
                labels = list(CARD_LABEL_FR.keys())
                toks = [x for x in re.split(r"\n+", t) if _clean(x)]
                cards = []
                i = 0
                while i < len(toks):
                    cur = toks[i]
                    if cur in labels:
                        label = cur
                        name_line = toks[i+1] if i+1 < len(toks) else ""
                        desc_parts = []
                        j = i + 2
                        while j < len(toks) and toks[j] not in labels:
                            desc_parts.append(toks[j])
                            j += 1
                        desc_en = _clean(" ".join(desc_parts))
                        cards.append({
                            "label": _label_to_fr(label, settings),
                            "name": _clean(name_line),
                            "desc": translate_en_fr(desc_en, settings.keep_terms) if desc_en else "",
                        })
                        i = j
                        continue
                    i += 1

                if cards:
                    sections.append(Section(
                        title=f"Arme : {wname}",
                        blocks=[{"type": "cards", "cards": cards}],
                        images=[]
                    ))

        channel_key = "personnages"
        entity_id = f"character:{target.url.rsplit('/', 1)[-1].lower()}"
        out_title = title

    elif target.kind == "combat_guide":
        channel_key = "combat"
        entity_id = "guide:combat"
        sections = _extract_sections_generic_from_html(html_full, settings)
        out_title = "Guide de combat"

    elif target.kind == "general_info":
        channel_key = "infos_generales"
        entity_id = "guide:infos_generales"
        sections = _extract_sections_generic_from_html(html_full, settings)
        out_title = "Infos générales"

    elif target.kind == "boss_index":
        # onglet "Information"
        try:
            loc = _find_clickable_by_text(page, "Information")
            if loc.count() > 0:
                loc.click(timeout=10_000)
                page.wait_for_timeout(500)
        except Exception:
            pass

        sections = _extract_sections_generic_from_html(page.content(), settings)
        channel_key = "boss_infos"
        entity_id = "boss:index"
        out_title = "Boss — infos générales"

    elif target.kind == "boss_tab":
        label = (target.extra or {}).get("tab") or (target.title_hint or "Boss")
        try:
            loc = _find_clickable_by_text(page, label)
            if loc.count() > 0:
                loc.click(timeout=10_000)
                page.wait_for_timeout(600)
        except Exception:
            pass

        html_now = page.content()
        nd_now = _parse_next_data(html_now)
        if nd_now:
            hero_nd, sec_nd = _extract_boss_from_next(nd_now, label, settings)
            if sec_nd:
                sections = sec_nd
            if hero_nd:
                hero_img = hero_nd

        if not sections:
            soup_now = BeautifulSoup(html_now, "lxml")
            hero_img = _pick_hero_image(soup_now, title_hint=label) or hero_img
            sections = _extract_sections_generic_from_html(html_now, settings)

        slug = _slugify(label)
        channel_key = slug if slug in settings.webhooks else "boss_infos"
        entity_id = f"boss:{slug}"
        out_title = label

    else:
        return None

    # fallback ultime : si rien n'est extrait, on joint une capture pour éviter un message vide
    if not sections:
        header_shot = _main_screenshot_bytes(page)
        header_name = "fallback.jpg" if header_shot else None
        sections = [Section(
            title="Contenu",
            blocks=[{"type": "text", "text": "Impossible d’extraire proprement cette page. La capture jointe sert de secours."}],
            images=[]
        )]

    norm = out_title + "\n" + "\n".join(s.title + ":" + str(s.blocks) for s in sections)
    content_hash = _sha(norm)

    return Entity(
        entity_id=entity_id,
        kind=target.kind,
        url=target.url,
        title=out_title,
        channel_key=channel_key,
        hero_image=hero_img,
        sections=sections,
        content_hash=content_hash,
        header_attachment_name=header_name,
        header_attachment_bytes=header_shot,
    )
