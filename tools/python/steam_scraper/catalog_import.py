from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_alias(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None

    normalized = text.lower()
    for token in ["(tm)", "(r)", "®", "™"]:
        normalized = normalized.replace(token, "")

    import re
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or None


def create_component(component: dict) -> dict:
    aliases = component.get("aliases") or []
    normalized_aliases = []
    for alias in aliases:
      normalized = normalize_alias(alias)
      if normalized and normalized not in normalized_aliases:
        normalized_aliases.append(normalized)

    name = clean_text(component.get("name"))
    normalized_name = normalize_alias(name)
    if normalized_name and normalized_name not in normalized_aliases:
        normalized_aliases.insert(0, normalized_name)

    return {
        "id": clean_text(component.get("id")),
        "kind": clean_text(component.get("kind")),
        "brand": clean_text(component.get("brand")),
        "family": clean_text(component.get("family")),
        "model": clean_text(component.get("model")),
        "name": name,
        "aliases": normalized_aliases,
        "cores": component.get("cores"),
        "threads": component.get("threads"),
        "base_ghz": component.get("base_ghz"),
        "boost_ghz": component.get("boost_ghz"),
        "vram_gb": component.get("vram_gb"),
        "score": component.get("score"),
        "sources": list(component.get("sources") or []),
    }


def merge_component(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)

    for key in ["kind", "brand", "family", "model", "name", "cores", "threads", "base_ghz", "boost_ghz", "vram_gb", "score"]:
        if merged.get(key) in (None, "") and incoming.get(key) not in (None, ""):
            merged[key] = incoming.get(key)

    if incoming.get("score") not in (None, ""):
        merged["score"] = incoming["score"]

    merged_aliases = list(merged.get("aliases") or [])
    for alias in incoming.get("aliases") or []:
        if alias not in merged_aliases:
            merged_aliases.append(alias)
    merged["aliases"] = merged_aliases

    merged_sources = list(merged.get("sources") or [])
    for source in incoming.get("sources") or []:
        if source not in merged_sources:
            merged_sources.append(source)
    merged["sources"] = merged_sources

    return merged


def fetch_json_url(url: str):
    request = Request(url, headers={"User-Agent": "steamspecs-component-importer/1.0"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def load_source_payload(source: dict):
    path_value = clean_text(source.get("path"))
    url_value = clean_text(source.get("url"))

    if path_value:
        return json.loads(Path(path_value).read_text(encoding="utf-8"))
    if url_value:
        return fetch_json_url(url_value)
    raise ValueError(f"Source {source.get('id')} is missing both path and url")


def apply_normalized_components(store: dict[str, dict], source: dict, payload):
    for row in payload:
        component = create_component({
            **row,
            "kind": row.get("kind") or source.get("kind"),
            "sources": [source.get("id")],
        })
        if not component["id"] or not component["kind"]:
            continue

        existing = store.get(component["id"])
        store[component["id"]] = merge_component(existing, component) if existing else component


def apply_score_overrides(store: dict[str, dict], source: dict, payload):
    for row in payload:
        target_id = clean_text(row.get("id"))
        if not target_id or target_id not in store:
            continue
        score = row.get("score")
        if score in (None, ""):
            continue
        store[target_id]["score"] = score
        if source.get("id") not in store[target_id]["sources"]:
            store[target_id]["sources"].append(source.get("id"))


def apply_alias_overrides(store: dict[str, dict], source: dict, payload):
    for row in payload:
        target_id = clean_text(row.get("id"))
        if not target_id or target_id not in store:
            continue

        aliases = store[target_id].get("aliases") or []
        for alias in row.get("aliases") or []:
            normalized = normalize_alias(alias)
            if normalized and normalized not in aliases:
                aliases.append(normalized)
        store[target_id]["aliases"] = aliases
        if source.get("id") not in store[target_id]["sources"]:
            store[target_id]["sources"].append(source.get("id"))


def split_components(store: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    cpus = []
    gpus = []

    for component in store.values():
        if component.get("kind") == "cpu":
            cpus.append(component)
        elif component.get("kind") == "gpu":
            gpus.append(component)

    cpus.sort(key=lambda item: (item.get("brand") or "", item.get("family") or "", item.get("model") or "", item.get("name") or ""))
    gpus.sort(key=lambda item: (item.get("brand") or "", item.get("family") or "", item.get("model") or "", item.get("name") or ""))
    return cpus, gpus


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def import_catalog(config_path: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    sources = config.get("sources") or []
    output_dir = Path(config.get("output_dir") or "data/catalog")
    store: dict[str, dict] = {}

    for source in sources:
        source_type = source.get("type")
        payload = load_source_payload(source)

        if source_type == "normalized_components":
            apply_normalized_components(store, source, payload)
        elif source_type == "score_overrides":
            apply_score_overrides(store, source, payload)
        elif source_type == "alias_overrides":
            apply_alias_overrides(store, source, payload)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")

    cpus, gpus = split_components(store)
    write_json(output_dir / "cpus.json", cpus)
    write_json(output_dir / "gpus.json", gpus)

    manifest = {
        "generated_components": len(store),
        "cpu_count": len(cpus),
        "gpu_count": len(gpus),
        "sources": [
            {
                "id": source.get("id"),
                "type": source.get("type"),
                "kind": source.get("kind"),
                "path": source.get("path"),
                "url": source.get("url"),
            }
            for source in sources
        ],
    }
    write_json(output_dir / "manifest.json", manifest)


def parse_args():
    parser = argparse.ArgumentParser(description="Build local CPU/GPU catalogs from multiple sources.")
    parser.add_argument("--config", default="data/catalog/sources.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    import_catalog(Path(args.config))
    print(f"Built component catalogs using {args.config}")


if __name__ == "__main__":
    main()
