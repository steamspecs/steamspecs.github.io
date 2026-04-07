from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

_MIN_SCORE_CACHE: dict[tuple[int, tuple[str, ...]], int | None] = {}


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


def find_min_score_by_patterns(catalog: list[dict], patterns: list[str]) -> int | None:
    cache_key = (id(catalog), tuple(patterns))
    if cache_key in _MIN_SCORE_CACHE:
        return _MIN_SCORE_CACHE[cache_key]

    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    scores = []

    for component in catalog:
        values = [component.get("name"), *(component.get("aliases") or [])]
        normalized_values = [normalize_alias(value) for value in values if clean_text(value)]
        haystacks = [value for value in normalized_values if value]
        if any(pattern.search(haystack) for haystack in haystacks for pattern in compiled):
            score = component.get("score")
            if score is not None:
                scores.append(score)

    result = min(scores) if scores else None
    _MIN_SCORE_CACHE[cache_key] = result
    return result


def is_generic_cpu_requirement(text: str) -> bool:
    normalized = normalize_alias(text) or ""
    if not normalized:
        return False

    generic_patterns = [
        r"\bsingle core\b",
        r"\bdual core\b",
        r"\bmulti ?core\b",
        r"\bcore duo\b",
        r"\bcpu with\b",
        r"\bprocessor\b",
        r"\bequivalent\b",
        r"\bor better\b",
        r"\bor similar amd\b",
        r"\bamd intel\b",
        r"\bintel amd\b",
        r"\bintel or amd\b",
        r"\bamd or intel\b",
    ]
    if not any(re.search(pattern, normalized) for pattern in generic_patterns):
        return False

    specific_markers = [
        "pentium",
        "athlon",
        "xeon",
        "ryzen",
        "threadripper",
        "fx ",
        "core i3",
        "core i5",
        "core i7",
        "core i9",
        "celeron",
        "phenom",
        "apu",
        "sempron",
        "opteron",
        "a10",
        "a8",
        "a6",
        "a4",
        "turion",
        "epyc",
        "xe ",
    ]
    return not any(marker in normalized for marker in specific_markers)


def legacy_gpu_requirement(raw_text: str | None, catalog: list[dict]) -> dict | None:
    normalized = normalize_alias(raw_text)
    if not normalized:
        return None

    legacy_rules = [
        (
            "legacy_gpu_geforce_fx_6_7_8_radeon_x",
            [r"geforce fx", r"\bgeforce [678]\b", r"radeon x", r"shader 2 0b"],
            [r"geforce 6\d{3}", r"geforce 7\d{3}", r"geforce 8\d{3}", r"radeon x\d+"],
            "Legacy GeForce 6/7/8 or Radeon X-class GPU",
        ),
        (
            "legacy_gpu_shader_model_3",
            [r"shader 3 0", r"pixel shader 3 0"],
            [r"geforce 7\d{3}", r"radeon x1\d{3}", r"radeon hd 2\d{3}"],
            "Legacy Shader Model 3 GPU",
        ),
        (
            "legacy_gpu_shader_model_2",
            [r"shader 2 0", r"shader 2 0b", r"transform and lighting", r"directx 8 1", r"directx 9 compatible"],
            [r"geforce fx", r"geforce 6\d{3}", r"radeon 7\d{3}", r"radeon x\d+"],
            "Legacy Shader Model 2 GPU",
        ),
        (
            "legacy_gpu_geforce2",
            [r"geforce ?2", r"p3 ?600 ?geforce ?2"],
            [r"geforce2", r"geforce 2", r"geforce 256"],
            "Legacy GeForce 2-class GPU",
        ),
        (
            "legacy_gpu_dx9_compliant",
            [r"dx9 compliant", r"directx 9 compliant", r"directx compatible", r"directx 9 0b drivers", r"ps 2 0 support"],
            [r"geforce 5\d{3}", r"geforce 6\d{3}", r"radeon 9\d{3}", r"radeon 9600"],
            "Legacy DirectX 9 GPU",
        ),
        (
            "legacy_gpu_opengl_3d",
            [r"opengl 3d", r"opengl.*video card", r"3d graphic card", r"3d video card"],
            [r"geforce 5\d{3}", r"geforce 6\d{3}", r"radeon 9600", r"radeon 9\d{3}"],
            "Legacy OpenGL 3D GPU",
        ),
        (
            "legacy_gpu_pci_agp",
            [r"pci or agp video card", r"agp video card", r"pci video card", r"video card with 2 mb ram"],
            [r"geforce 256", r"geforce2", r"radeon 7\d{3}"],
            "Legacy PCI/AGP GPU",
        ),
    ]

    for rule_id, triggers, score_patterns, label in legacy_rules:
        if any(re.search(trigger, normalized, re.IGNORECASE) for trigger in triggers):
            min_score = find_min_score_by_patterns(catalog, score_patterns)
            if min_score is None:
                min_score = 1500
            return {
                "raw": clean_text(raw_text),
                "candidates": [{
                    "id": rule_id,
                    "name": label,
                    "score": min_score,
                    "matched_from": clean_text(raw_text),
                }],
                "min_score": min_score,
            }

    return None


def legacy_cpu_requirement(raw_text: str | None, catalog: list[dict]) -> dict | None:
    normalized = normalize_alias(raw_text)
    if not normalized:
        return None

    legacy_rules = [
        (
            "legacy_cpu_pentium_166",
            [r"pentium 166", r"pentium mmx"],
            [r"pentium 166", r"pentium mmx"],
            "Intel Pentium 166-class CPU",
        ),
        (
            "legacy_cpu_pentium_ii",
            [r"pentium ii", r"pentium 2"],
            [r"pentium ii", r"pentium 2"],
            "Intel Pentium II-class CPU",
        ),
        (
            "legacy_cpu_pentium_iii",
            [r"pentium iii", r"pentium 3"],
            [r"pentium iii", r"pentium 3"],
            "Intel Pentium III-class CPU",
        ),
        (
            "legacy_cpu_pentium_4",
            [r"pentium 4"],
            [r"pentium 4"],
            "Intel Pentium 4-class CPU",
        ),
        (
            "legacy_cpu_athlon",
            [r"amd athlon", r"\bathlon xp\b", r"\bathlon\b"],
            [r"athlon xp", r"amd athlon", r"\bathlon\b"],
            "AMD Athlon-class CPU",
        ),
        (
            "legacy_cpu_westmere_i5",
            [r"core i5.*westmere", r"westmere.*core i5"],
            [r"core i5", r"westmere"],
            "Intel Core i5 Westmere-class CPU",
        ),
    ]

    for rule_id, triggers, score_patterns, label in legacy_rules:
        if any(re.search(trigger, normalized, re.IGNORECASE) for trigger in triggers):
            min_score = find_min_score_by_patterns(catalog, score_patterns)
            if min_score is None:
                min_score = 150
            return {
                "raw": clean_text(raw_text),
                "candidates": [{
                    "id": rule_id,
                    "name": label,
                    "score": min_score,
                    "matched_from": clean_text(raw_text),
                }],
                "min_score": min_score,
            }

    return None


def split_requirement_variants(raw_text: str | None, kind: str) -> list[str]:
    text = clean_text(raw_text)
    if not text:
        return []

    if kind == "cpu" and is_generic_cpu_requirement(text):
        return [text]

    separator_pattern = r"\s+or\s+|;"
    if kind == "gpu":
        separator_pattern = r"\s+or\s+|/|;"

    variants = re.split(separator_pattern, text, flags=re.IGNORECASE)
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


def match_component_requirement(raw_text: str | None, catalog: list[dict], kind: str) -> dict:
    normalized = normalize_alias(raw_text)
    if normalized in {"amd", "intel", "nvidia", "ati", "radeon", "geforce", "video card", "graphics card", "graphic card"}:
        return {
            "raw": clean_text(raw_text),
            "candidates": [],
            "min_score": None,
        }

    legacy_cpu = legacy_cpu_requirement(raw_text, catalog) if kind == "cpu" else None
    if legacy_cpu:
        return legacy_cpu

    if kind == "cpu" and is_generic_cpu_requirement(raw_text or ""):
        return {
            "raw": clean_text(raw_text),
            "candidates": [],
            "min_score": None,
        }

    legacy_gpu = legacy_gpu_requirement(raw_text, catalog) if kind == "gpu" else None
    if legacy_gpu:
        return legacy_gpu

    variants = split_requirement_variants(raw_text, kind)
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
    annotated["cpu_match"] = match_component_requirement(annotated.get("cpu"), catalogs.get("cpu", []), "cpu")
    annotated["gpu_match"] = match_component_requirement(annotated.get("gpu"), catalogs.get("gpu", []), "gpu")
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
    result = match_component_requirement(args.text, catalog, args.kind)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
