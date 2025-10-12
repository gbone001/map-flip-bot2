from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class MapEntry:
    game_type: str
    map_pretty: str
    variant: str
    map_id: str


@lru_cache(maxsize=1)
def load_catalog() -> List[MapEntry]:
    data_path = Path(__file__).resolve().parent / "available_maps.json"
    if not data_path.exists():
        return []
    with data_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    entries: List[MapEntry] = []
    for item in raw:
        game_type = item.get("gameType")
        pretty = item.get("mapPretty")
        variant = item.get("variant")
        map_id = item.get("mapId")
        if not (game_type and pretty and variant and map_id):
            continue
        entries.append(MapEntry(game_type=game_type, map_pretty=pretty, variant=variant, map_id=map_id))
    return entries


def available_game_types(map_ids: Iterable[str] | None = None) -> List[str]:
    ids = set(map_ids or [])
    entries = load_catalog()
    if ids:
        entries = [entry for entry in entries if entry.map_id in ids]
    return sorted({entry.game_type for entry in entries})


def maps_for_game_type(game_type: str, map_ids: Iterable[str] | None = None) -> List[str]:
    ids = set(map_ids or [])
    results: List[str] = []
    for entry in load_catalog():
        if entry.game_type != game_type:
            continue
        if ids and entry.map_id not in ids:
            continue
        results.append(entry.map_pretty)
    # Preserve order but ensure unique names
    seen = set()
    unique: List[str] = []
    for name in results:
        if name in seen:
            continue
        seen.add(name)
        unique.append(name)
    return unique


def variants_for_map(game_type: str, map_pretty: str, map_ids: Iterable[str] | None = None) -> List[MapEntry]:
    ids = set(map_ids or [])
    variants: List[MapEntry] = []
    for entry in load_catalog():
        if entry.game_type != game_type:
            continue
        if entry.map_pretty != map_pretty:
            continue
        if ids and entry.map_id not in ids:
            continue
        variants.append(entry)
    return variants
