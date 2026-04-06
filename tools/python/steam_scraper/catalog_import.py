from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


NUMERIC_FIELDS = {"cores", "threads", "base_ghz", "boost_ghz", "vram_gb", "score"}


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
    for token in ["(tm)", "(r)", "Â®", "â„¢", "®", "™"]:
        normalized = normalized.replace(token, "")

    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or None


def slugify(value: str | None) -> str | None:
    normalized = normalize_alias(value)
    if not normalized:
        return None
    return normalized.replace(" ", "_")


def to_number(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return value

    text = clean_text(value)
    if not text:
        return None

    cleaned = text.replace(",", "")
    try:
        number = float(cleaned)
    except ValueError:
        return None

    if number.is_integer():
        return int(number)
    return number


def normalize_numeric_fields(component: dict) -> dict:
    normalized = dict(component)
    for key in NUMERIC_FIELDS:
        normalized[key] = to_number(normalized.get(key))
    return normalized


def build_component_aliases(component: dict) -> list[str]:
    aliases: list[str] = []
    raw_aliases = list(component.get("aliases") or [])

    for value in [
        component.get("name"),
        f"{component.get('brand') or ''} {component.get('family') or ''} {component.get('model') or ''}".strip(),
        f"{component.get('family') or ''} {component.get('model') or ''}".strip(),
        *raw_aliases,
    ]:
        normalized = normalize_alias(value)
        if normalized and normalized not in aliases:
            aliases.append(normalized)

    return aliases


def infer_brand(name: str | None) -> str | None:
    normalized = normalize_alias(name) or ""
    if not normalized:
        return None

    if normalized.startswith("intel "):
        return "Intel"
    if normalized.startswith("amd ") or " ryzen " in f" {normalized} " or normalized.startswith("ryzen "):
        return "AMD"
    if normalized.startswith("nvidia ") or normalized.startswith("geforce ") or " geforce " in f" {normalized} ":
        return "NVIDIA"
    if normalized.startswith("radeon ") or " radeon " in f" {normalized} ":
        return "AMD"
    return None


def generate_component_id(component: dict) -> str | None:
    kind = clean_text(component.get("kind"))
    name_slug = slugify(component.get("name"))
    if not kind or not name_slug:
        return None
    return f"{kind}_{name_slug}"


def create_component(component: dict) -> dict:
    normalized = normalize_numeric_fields(component)
    normalized["name"] = clean_text(normalized.get("name"))
    normalized["kind"] = clean_text(normalized.get("kind"))
    normalized["brand"] = clean_text(normalized.get("brand")) or infer_brand(normalized.get("name"))
    normalized["family"] = clean_text(normalized.get("family"))
    normalized["model"] = clean_text(normalized.get("model"))
    normalized["sources"] = list(normalized.get("sources") or [])
    normalized["aliases"] = build_component_aliases(normalized)
    normalized["id"] = clean_text(normalized.get("id")) or generate_component_id(normalized)

    return {
        "id": normalized.get("id"),
        "kind": normalized.get("kind"),
        "brand": normalized.get("brand"),
        "family": normalized.get("family"),
        "model": normalized.get("model"),
        "name": normalized.get("name"),
        "aliases": normalized.get("aliases") or [],
        "cores": normalized.get("cores"),
        "threads": normalized.get("threads"),
        "base_ghz": normalized.get("base_ghz"),
        "boost_ghz": normalized.get("boost_ghz"),
        "vram_gb": normalized.get("vram_gb"),
        "score": normalized.get("score"),
        "sources": normalized.get("sources") or [],
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


def fetch_text_url(url: str) -> str:
    request = Request(url, headers={"User-Agent": "steamspecs-component-importer/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def fetch_json_url(url: str):
    return json.loads(fetch_text_url(url))


def load_payload_text(source: dict) -> str:
    path_value = clean_text(source.get("path"))
    url_value = clean_text(source.get("url"))

    if path_value:
        return Path(path_value).read_text(encoding="utf-8")
    if url_value:
        return fetch_text_url(url_value)
    raise ValueError(f"Source {source.get('id')} is missing both path and url")


def load_source_payload(source: dict):
    source_format = clean_text(source.get("format"))

    if source_format == "csv":
        text = load_payload_text(source)
        return list(csv.DictReader(text.splitlines()))

    path_value = clean_text(source.get("path"))
    url_value = clean_text(source.get("url"))

    if path_value:
        return json.loads(Path(path_value).read_text(encoding="utf-8"))
    if url_value:
        return fetch_json_url(url_value)
    raise ValueError(f"Source {source.get('id')} is missing both path and url")


def build_alias_index(store: dict[str, dict]) -> dict[tuple[str, str], str]:
    index: dict[tuple[str, str], str] = {}
    for component_id, component in store.items():
        kind = clean_text(component.get("kind"))
        if not kind:
            continue
        for alias in component.get("aliases") or []:
            index[(kind, alias)] = component_id
    return index


def resolve_component_id(store: dict[str, dict], component: dict) -> str | None:
    incoming_id = clean_text(component.get("id"))
    if incoming_id and incoming_id in store:
        return incoming_id

    alias_index = build_alias_index(store)
    kind = clean_text(component.get("kind"))
    for alias in component.get("aliases") or []:
        found = alias_index.get((kind, alias))
        if found:
            return found

    return incoming_id or generate_component_id(component)


def coerce_value(key: str, value: Any):
    if key in NUMERIC_FIELDS:
        return to_number(value)
    return clean_text(value)


def read_mapped_value(row: dict, mapping: Any):
    if isinstance(mapping, list):
        values = []
        for item in mapping:
          value = read_mapped_value(row, item)
          if value is None:
              continue
          if isinstance(value, list):
              values.extend(value)
          else:
              values.append(value)
        return values

    if isinstance(mapping, dict):
        if mapping.get("template"):
            try:
                return mapping["template"].format(**row)
            except KeyError:
                return None
        if mapping.get("column"):
            return row.get(mapping["column"])
        return None

    if isinstance(mapping, str):
        return row.get(mapping)

    return None


def map_component_row(row: dict, source: dict) -> dict:
    columns = source.get("columns") or {}
    kind = clean_text(source.get("kind")) or clean_text(read_mapped_value(row, columns.get("kind")))

    component = {
        "id": clean_text(read_mapped_value(row, columns.get("id"))),
        "kind": kind,
        "brand": clean_text(read_mapped_value(row, columns.get("brand"))),
        "family": clean_text(read_mapped_value(row, columns.get("family"))),
        "model": clean_text(read_mapped_value(row, columns.get("model"))),
        "name": clean_text(read_mapped_value(row, columns.get("name"))),
        "cores": to_number(read_mapped_value(row, columns.get("cores"))),
        "threads": to_number(read_mapped_value(row, columns.get("threads"))),
        "base_ghz": to_number(read_mapped_value(row, columns.get("base_ghz"))),
        "boost_ghz": to_number(read_mapped_value(row, columns.get("boost_ghz"))),
        "vram_gb": to_number(read_mapped_value(row, columns.get("vram_gb"))),
        "score": to_number(read_mapped_value(row, columns.get("score"))),
        "aliases": [],
        "sources": [source.get("id")],
    }

    alias_values = read_mapped_value(row, columns.get("aliases"))
    if isinstance(alias_values, list):
        component["aliases"] = [value for value in alias_values if clean_text(value)]
    elif clean_text(alias_values):
        component["aliases"] = [alias_values]

    return component


def resolve_score_target(store: dict[str, dict], source: dict, row: dict) -> str | None:
    columns = source.get("columns") or {}
    direct_id = clean_text(read_mapped_value(row, columns.get("id")))
    if direct_id and direct_id in store:
        return direct_id

    kind = clean_text(source.get("kind")) or clean_text(read_mapped_value(row, columns.get("kind")))
    alias_index = build_alias_index(store)

    candidates = []
    for key in ["name", "alias", "model"]:
        value = normalize_alias(read_mapped_value(row, columns.get(key)))
        if value:
            candidates.append(value)

    for alias in candidates:
        found = alias_index.get((kind, alias)) if kind else None
        if found:
            return found

        if not kind:
            for candidate_kind in ["cpu", "gpu"]:
                found = alias_index.get((candidate_kind, alias))
                if found:
                    return found

    return None


def apply_normalized_components(store: dict[str, dict], source: dict, payload) -> int:
    applied = 0
    for row in payload:
        component = create_component({
            **row,
            "kind": row.get("kind") or source.get("kind"),
            "sources": [source.get("id")],
        })
        resolved_id = resolve_component_id(store, component)
        if not resolved_id or not component["kind"]:
            continue

        component["id"] = resolved_id
        existing = store.get(resolved_id)
        store[resolved_id] = merge_component(existing, component) if existing else component
        applied += 1
    return applied


def apply_mapped_components(store: dict[str, dict], source: dict, payload) -> int:
    applied = 0
    for row in payload:
        component = create_component(map_component_row(row, source))
        resolved_id = resolve_component_id(store, component)
        if not resolved_id or not component["kind"] or not component["name"]:
            continue

        component["id"] = resolved_id
        existing = store.get(resolved_id)
        store[resolved_id] = merge_component(existing, component) if existing else component
        applied += 1
    return applied


def apply_score_overrides(store: dict[str, dict], source: dict, payload) -> int:
    applied = 0
    for row in payload:
        target_id = clean_text(row.get("id"))
        if not target_id or target_id not in store:
            continue
        score = to_number(row.get("score"))
        if score is None:
            continue
        store[target_id]["score"] = score
        if source.get("id") not in store[target_id]["sources"]:
            store[target_id]["sources"].append(source.get("id"))
        applied += 1
    return applied


def apply_mapped_scores(store: dict[str, dict], source: dict, payload) -> int:
    applied = 0
    columns = source.get("columns") or {}

    for row in payload:
        target_id = resolve_score_target(store, source, row)
        if not target_id or target_id not in store:
            continue

        score = to_number(read_mapped_value(row, columns.get("score")))
        if score is None:
            continue

        store[target_id]["score"] = score
        if source.get("id") not in store[target_id]["sources"]:
            store[target_id]["sources"].append(source.get("id"))
        applied += 1

    return applied


def apply_alias_overrides(store: dict[str, dict], source: dict, payload) -> int:
    applied = 0
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
        applied += 1
    return applied


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
    applied_sources = []

    for source in sources:
        if source.get("enabled") is False:
            continue

        source_type = source.get("type")
        optional = bool(source.get("optional"))

        try:
            payload = load_source_payload(source)
        except FileNotFoundError:
            if optional:
                applied_sources.append({
                    "id": source.get("id"),
                    "type": source_type,
                    "kind": source.get("kind"),
                    "path": source.get("path"),
                    "url": source.get("url"),
                    "applied_rows": 0,
                    "status": "missing_optional_source",
                })
                continue
            raise

        if source_type == "normalized_components":
            applied_rows = apply_normalized_components(store, source, payload)
        elif source_type == "mapped_components":
            applied_rows = apply_mapped_components(store, source, payload)
        elif source_type == "score_overrides":
            applied_rows = apply_score_overrides(store, source, payload)
        elif source_type == "mapped_scores":
            applied_rows = apply_mapped_scores(store, source, payload)
        elif source_type == "alias_overrides":
            applied_rows = apply_alias_overrides(store, source, payload)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")

        applied_sources.append({
            "id": source.get("id"),
            "type": source_type,
            "kind": source.get("kind"),
            "path": source.get("path"),
            "url": source.get("url"),
            "applied_rows": applied_rows,
            "status": "ok",
        })

    cpus, gpus = split_components(store)
    write_json(output_dir / "cpus.json", cpus)
    write_json(output_dir / "gpus.json", gpus)

    manifest = {
        "generated_components": len(store),
        "cpu_count": len(cpus),
        "gpu_count": len(gpus),
        "sources": applied_sources,
    }
    write_json(output_dir / "manifest.json", manifest)


def parse_args():
    parser = argparse.ArgumentParser(description="Build local CPU/GPU catalogs from multiple sources.")
    parser.add_argument("--config", default="data/catalog/sources.json")
    parser.add_argument("--refresh-imports", action="store_true")
    parser.add_argument("--include-techpowerup-gpu", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.refresh_imports:
        from steam_scraper.component_source_refresh import refresh_imports
        refresh_imports(Path("data/catalog/imports"), include_techpowerup_gpu=args.include_techpowerup_gpu)
    import_catalog(Path(args.config))
    print(f"Built component catalogs using {args.config}")


if __name__ == "__main__":
    main()
