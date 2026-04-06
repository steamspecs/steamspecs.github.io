from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def clean_text(value) -> str | None:
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
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or None


def load_catalog(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalogs(catalog_dir: Path) -> dict[str, list[dict]]:
    return {
        "cpu": load_catalog(catalog_dir / "cpus.json"),
        "gpu": load_catalog(catalog_dir / "gpus.json"),
    }


def split_requirement_variants(raw_text: str | None) -> list[str]:
    text = clean_text(raw_text)
    if not text:
        return []

    variants = re.split(r"\s+or\s+|/|;", text, flags=re.IGNORECASE)
    return [variant.strip(" ,") for variant in variants if clean_text(variant)]


def match_component_variant(raw_text: str, catalog: list[dict]) -> dict | None:
    normalized = normalize_alias(raw_text)
    if not normalized:
        return None

    exact_matches = []
    partial_matches = []

    for component in catalog:
        aliases = component.get("aliases") or []
        if normalized in aliases:
            exact_matches.append(component)
            continue

        for alias in aliases:
            if alias and (alias in normalized or normalized in alias):
                partial_matches.append(component)
                break

    if exact_matches:
        exact_matches.sort(key=lambda item: item.get("score") or 0, reverse=True)
        return exact_matches[0]

    if partial_matches:
        partial_matches.sort(key=lambda item: item.get("score") or 0, reverse=True)
        return partial_matches[0]

    return None


def match_component_requirement(raw_text: str | None, catalog: list[dict]) -> dict:
    variants = split_requirement_variants(raw_text)
    candidates = []

    for variant in variants:
        match = match_component_variant(variant, catalog)
        if match and match["id"] not in [candidate["id"] for candidate in candidates]:
            candidates.append({
                "id": match["id"],
                "name": match.get("name"),
                "score": match.get("score"),
                "matched_from": variant,
            })

    valid_scores = [candidate["score"] for candidate in candidates if candidate.get("score") is not None]
    min_score = min(valid_scores) if valid_scores else None

    return {
        "raw": clean_text(raw_text),
        "candidates": candidates,
        "min_score": min_score,
    }


def annotate_requirement_components(requirement: dict | None, catalogs: dict[str, list[dict]]) -> dict | None:
    if not requirement:
        return requirement

    annotated = dict(requirement)
    annotated["cpu_match"] = match_component_requirement(annotated.get("cpu"), catalogs.get("cpu", []))
    annotated["gpu_match"] = match_component_requirement(annotated.get("gpu"), catalogs.get("gpu", []))
    return annotated


def parse_args():
    parser = argparse.ArgumentParser(description="Match a Steam requirement string against a local component catalog.")
    parser.add_argument("--kind", choices=["cpu", "gpu"], required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--catalog-dir", default="data/catalog")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog_dir = Path(args.catalog_dir)
    catalog_file = catalog_dir / ("cpus.json" if args.kind == "cpu" else "gpus.json")
    catalog = load_catalog(catalog_file)
    result = match_component_requirement(args.text, catalog)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
