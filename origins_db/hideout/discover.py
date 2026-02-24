from __future__ import annotations
from dataclasses import dataclass
from bs4 import BeautifulSoup
from origins_db.hideout.fetch import RenderClient

@dataclass(frozen=True)
class Target:
    kind: str  # character | combat_guide | general_info | boss_index | boss_tab
    url: str
    title_hint: str | None = None
    extra: dict | None = None

def _absolute(base: str, href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://hideoutgacha.com" + href
    return base.rstrip("/") + "/" + href.lstrip("/")

def _unique_key(t: Target) -> tuple:
    tab = None
    if t.extra:
        tab = t.extra.get("tab")
    return (t.kind, t.url, tab)

def discover_all(render: RenderClient, base_url: str) -> list[Target]:
    targets: list[Target] = []

    # Guides fixes
    targets.append(Target(kind="combat_guide", url=base_url + "/combat-guide", title_hint="Combat Guide"))
    targets.append(Target(kind="general_info", url=base_url + "/general-info", title_hint="General Information"))

    # Boss guide (index + onglets)
    boss_url = base_url + "/boss-guide"
    targets.append(Target(kind="boss_index", url=boss_url, title_hint="Boss Guide"))

    # Découverte des onglets boss (y compris futurs boss)
    try:
        page = render.goto(boss_url)
        # heuristique : boutons/onglets proches du titre
        candidates = []
        # rôle ARIA tab
        for el in page.locator('[role="tab"]').all():
            txt = (el.inner_text() or "").strip()
            if txt:
                candidates.append(txt)
        # fallback : nav boutons/links courts
        if not candidates:
            for el in page.locator("main a, main button").all():
                txt = (el.inner_text() or "").strip()
                if 2 <= len(txt) <= 30:
                    candidates.append(txt)

        # nettoyage + dédoublonnage
        clean = []
        for c in candidates:
            c = " ".join(c.split())
            if c and c not in clean:
                clean.append(c)

        # on ignore les onglets "Information" pour boss_tab
        for label in clean:
            if label.lower() in ("information",):
                continue
            # certains liens peuvent être hors-sujet ; on garde ceux qui ressemblent à des boss connus
            # mais on accepte aussi les nouveaux boss : on filtre juste les labels trop génériques
            if label.lower() in ("privacy policy", "terms of service", "games"):
                continue
            targets.append(Target(kind="boss_tab", url=boss_url, title_hint=label, extra={"tab": label}))
    except Exception:
        pass

    # Personnages : page roster -> toutes les cartes
    roster_url = base_url + "/characters"
    page = render.goto(roster_url)
    soup = BeautifulSoup(page.content(), "lxml")

    for a in soup.select('a[href*="/characters/"]'):
        href = a.get("href")
        if not href:
            continue
        url = _absolute(base_url, href)
        if url.rstrip("/").endswith("/characters"):
            continue
        name = a.get_text(strip=True) or None
        targets.append(Target(kind="character", url=url, title_hint=name))

    # dédoublonnage (kind+url+tab)
    seen = set()
    out: list[Target] = []
    for t in targets:
        k = _unique_key(t)
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out
