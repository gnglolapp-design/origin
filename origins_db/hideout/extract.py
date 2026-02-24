from __future__ import annotations
import hashlib
import re
from bs4 import BeautifulSoup, Tag
from origins_db.hideout.fetch import RenderClient
from origins_db.hideout.model import Entity, Section
from origins_db.hideout.translate import translate_en_fr
from origins_db.config import Settings

TAB_LABELS_CHARACTER = ["Basic Info", "Weapons", "Armor", "Potentials"]

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s

def _pick_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    return _clean(h1.get_text(" ", strip=True)) if h1 else "Sans titre"

def _pick_hero_image(soup: BeautifulSoup) -> str | None:
    # première image proche du titre
    img = soup.find("img")
    if not img:
        return None
    src = img.get("src")
    if not src:
        return None
    if src.startswith("//"):
        src = "https:" + src
    if src.startswith("/"):
        src = "https://hideoutgacha.com" + src
    return src

def _find_clickable_by_text(page, label: str):
    return page.locator(f"text={label}").first

def _extract_visible_main_html(page) -> str:
    try:
        main = page.locator("main").first
        if main.count() > 0:
            return main.inner_html()
    except Exception:
        pass
    return page.content()

def _main_screenshot_bytes(page) -> bytes | None:
    try:
        main = page.locator("main").first
        if main.count() == 0:
            return None
        return main.screenshot(type="jpeg", quality=70)
    except Exception:
        return None

def _normalize_img(src: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://hideoutgacha.com" + src
    return src

def _extract_sections_generic(html: str, settings: Settings) -> list[Section]:
    soup = BeautifulSoup(html, "lxml")
    roots = soup.select("h2, h3")
    sections: list[Section] = []

    for h in roots:
        title_en = _clean(h.get_text(" ", strip=True))
        if not title_en:
            continue

        blocks = []
        images: list[str] = []
        cur = h.next_sibling
        texts: list[str] = []
        bullets: list[str] = []

        while cur is not None:
            if isinstance(cur, Tag) and cur.name in ("h2", "h3"):
                break
            if isinstance(cur, Tag):
                for img in cur.select("img[src]"):
                    images.append(_normalize_img(img["src"]))

                # listes
                for li in cur.select("li"):
                    t = _clean(li.get_text(" ", strip=True))
                    if t:
                        bullets.append(t)

                # paragraphes
                for p in cur.select("p"):
                    t = _clean(p.get_text(" ", strip=True))
                    if t:
                        texts.append(t)
            cur = cur.next_sibling

        if bullets:
            fr_bullets = [translate_en_fr(b, settings.keep_terms) for b in bullets[:120]]
            blocks.append({"type": "list", "items": fr_bullets})

        if texts:
            joined = " ".join(texts)
            joined = translate_en_fr(joined, settings.keep_terms)
            blocks.append({"type": "text", "text": joined})

        if not blocks:
            continue

        title_fr = translate_en_fr(title_en, settings.keep_terms)
        sections.append(Section(title=title_fr, blocks=blocks, images=images))

    if not sections:
        text = _clean(soup.get_text(" ", strip=True))
        if text:
            sections.append(Section(
                title="Résumé",
                blocks=[{"type": "text", "text": translate_en_fr(text, settings.keep_terms)}],
                images=[]
            ))
    return sections

def extract_entity(render: RenderClient, target, settings: Settings) -> Entity | None:
    page = render.goto(target.url)
    html_full = page.content()
    soup = BeautifulSoup(html_full, "lxml")
    title = _pick_title(soup)
    hero_img = _pick_hero_image(soup)

    sections: list[Section] = []
    header_shot = None
    header_name = None

    if target.kind == "character":
        # onglets : Basic Info / Weapons / Armor / Potentials
        for label in TAB_LABELS_CHARACTER:
            try:
                loc = _find_clickable_by_text(page, label)
                if loc.count() > 0:
                    loc.click(timeout=10_000)
                    page.wait_for_timeout(500)
            except Exception:
                pass

            html = _extract_visible_main_html(page)
            tab_sections = _extract_sections_generic(html, settings)
            tab_title = {
                "Basic Info": "Infos de base",
                "Weapons": "Armes",
                "Armor": "Armure",
                "Potentials": "Potentiels",
            }.get(label, translate_en_fr(label, settings.keep_terms))

            if tab_sections:
                sections.append(Section(
                    title=tab_title,
                    blocks=[{"type": "subsections", "sections": tab_sections}],
                    images=[]
                ))

            # une capture “utile” : on prend celle de l’onglet Armes (souvent le plus visuel)
            if label == "Weapons" and header_shot is None:
                header_shot = _main_screenshot_bytes(page)
                header_name = "armes.jpg"

        channel_key = "personnages"
        entity_id = f"character:{target.url.rsplit('/', 1)[-1].lower()}"
        out_title = title  # noms identiques

    elif target.kind == "combat_guide":
        channel_key = "combat"
        entity_id = "guide:combat"
        html = _extract_visible_main_html(page)
        sections = _extract_sections_generic(html, settings)
        header_shot = _main_screenshot_bytes(page)
        header_name = "guide.jpg"
        out_title = translate_en_fr(title, settings.keep_terms)

    elif target.kind == "general_info":
        channel_key = "infos_generales"
        entity_id = "guide:infos_generales"
        html = _extract_visible_main_html(page)
        sections = _extract_sections_generic(html, settings)
        header_shot = _main_screenshot_bytes(page)
        header_name = "infos.jpg"
        out_title = translate_en_fr(title, settings.keep_terms)

    elif target.kind == "boss_index":
        # onglet "Information" uniquement
        try:
            loc = _find_clickable_by_text(page, "Information")
            if loc.count() > 0:
                loc.click(timeout=10_000)
                page.wait_for_timeout(500)
        except Exception:
            pass
        html = _extract_visible_main_html(page)
        sections = _extract_sections_generic(html, settings)
        header_shot = _main_screenshot_bytes(page)
        header_name = "boss_infos.jpg"
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
        html = _extract_visible_main_html(page)
        sections = _extract_sections_generic(html, settings)
        header_shot = _main_screenshot_bytes(page)
        header_name = f"{_slugify(label)[:40]}.jpg"

        slug = _slugify(label)
        channel_key = slug if slug in settings.webhooks else "boss_infos"
        entity_id = f"boss:{slug}"
        out_title = label  # nom boss inchangé

    else:
        return None

    # hash du contenu structuré (titre + sections). On inclut la présence de screenshot.
    norm = out_title + "\n" + "\n".join(s.title + ":" + str(s.blocks) for s in sections) + f"\nshot={bool(header_shot)}"
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
