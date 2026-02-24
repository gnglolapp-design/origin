# Origins DB — Sync HideoutGacha → Discord (webhooks)

Outil automatique (gratuit) : récupère le contenu HideoutGacha (Seven Deadly Sins: Origin), le reformule en **français**, puis publie/édite des messages via **webhooks Discord** sans doublons.

## Salons / routes (mapping)
- Personnages (toutes les pages `/characters/...`) → `#personnages`
- Guides :
  - `/combat-guide` → `#combat`
  - `/general-info` → `#infos-générales`
- Boss :
  - `/boss-guide` (infos générales) → `#boss-infos`
  - Onglets boss (Guardian Golem, Drake, Red Demon, Grey Demon, Albion) → salons dédiés
  - Si un nouveau boss apparaît sans salon dédié → `#boss-infos`

## Pré-requis
- Un webhook **par salon** (URLs stockées dans les *Secrets* GitHub).
- Repo GitHub **public**.
- GitHub Actions activé.

## Configuration (Secrets GitHub)
Crée un secret nommé **`DISCORD_WEBHOOKS`** avec ce JSON :

```json
{
  "personnages": "https://discord.com/api/webhooks/....",
  "combat": "https://discord.com/api/webhooks/....",
  "infos_generales": "https://discord.com/api/webhooks/....",
  "boss_infos": "https://discord.com/api/webhooks/....",
  "guardian_golem": "https://discord.com/api/webhooks/....",
  "drake": "https://discord.com/api/webhooks/....",
  "red_demon": "https://discord.com/api/webhooks/....",
  "grey_demon": "https://discord.com/api/webhooks/....",
  "albion": "https://discord.com/api/webhooks/...."
}
```

## Exécution
- Automatique : **tous les 3 jours** (72h).
- Manuel : onglet **Actions → “Origins DB Sync” → Run workflow**.

## Notes importantes
- Le premier run (état vide) poste tout (personnages + guides + boss). Ça peut prendre du temps et déclencher des limites Discord : le script gère le 429 et ralentit automatiquement.
- Les messages sont **édités** (PATCH) quand le contenu change : pas de doublons.
- État stocké dans `data/state.json` et commité automatiquement.

