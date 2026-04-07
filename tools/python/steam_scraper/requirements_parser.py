from __future__ import annotations

from copy import deepcopy
from html import unescape
import re


EMPTY_REQUIREMENT = {
    "os": None,
    "cpu": None,
    "gpu": None,
    "ram_gb": None,
    "vram_gb": None,
    "storage_gb": None,
    "directx": None,
    "opengl": None,
    "vulkan": False,
    "notes": None,
    "raw_html": None,
}

NULLISH_RE = re.compile(r"^(?:n/?a|none|unknown|not available|not applicable|null|nil|tbd|-+)$", re.IGNORECASE)


def create_requirement() -> dict:
    return deepcopy(EMPTY_REQUIREMENT)


def clean_text(value) -> str | None:
    if value is None:
        return None

    text = unescape(str(value))
    text = text.replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if NULLISH_RE.fullmatch(text):
        return None
    return text or None


def strip_html(html: str | None) -> str:
    if not html:
        return ""

    text = str(html)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</ul>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return clean_text(text) or ""


def normalize_label(text: str | None) -> str:
    cleaned = (clean_text(text) or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", cleaned).strip()


def normalize_number(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_size_in_gb(text: str | None) -> float | None:
    normalized = (clean_text(text) or "").lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(tb|gb|mb)\b", normalized)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2)
    if unit == "tb":
        return value * 1024
    if unit == "mb":
        return value / 1024
    return value


def parse_graphics_memory_gb(text: str | None) -> float | None:
    normalized = (clean_text(text) or "").lower()
    if not normalized:
        return None
    if not re.search(r"\b(vram|video memory|video card|graphics|graphic card|dedicated)\b", normalized):
        return None
    return parse_size_in_gb(normalized)


def update_graphics_api_fields(req: dict, text: str | None) -> None:
    normalized = clean_text(text)
    if not normalized:
        return

    directx_match = re.search(r"(directx|direct3d)\s*([0-9]+(?:\.[0-9]+)?)", normalized, re.IGNORECASE)
    if directx_match and req["directx"] is None:
        req["directx"] = normalize_number(directx_match.group(2))

    opengl_match = re.search(r"opengl\s*([0-9]+(?:\.[0-9]+)?)", normalized, re.IGNORECASE)
    if opengl_match and req["opengl"] is None:
        req["opengl"] = normalize_number(opengl_match.group(1))

    if re.search(r"\bvulkan\b", normalized, re.IGNORECASE):
        req["vulkan"] = True


def choose_better_text(current: str | None, new_value: str | None) -> str | None:
    a = clean_text(current)
    b = clean_text(new_value)
    if not a:
        return b
    if not b:
        return a
    return b if len(b) > len(a) else a


def looks_like_os(text: str | None) -> bool:
    return bool(re.search(r"windows|linux|ubuntu|steamos|mac ?os|os x|sierra|mojave|catalina|ventura", text or "", re.IGNORECASE))


def looks_like_cpu(text: str | None) -> bool:
    return bool(re.search(r"processor|cpu|intel|amd|ryzen|athlon|pentium|celeron|xeon|core [im\d]|dual[\s-]?core|quad[\s-]?core|ghz|mhz", text or "", re.IGNORECASE))


def looks_like_gpu(text: str | None) -> bool:
    return bool(re.search(r"graphics|gpu|video card|video memory|vram|geforce|radeon|gtx|rtx|rx\s*\d|intel hd|iris|arc|nvidia|amd hd|directx|direct3d|opengl|shader|pci|agp", text or "", re.IGNORECASE))


def looks_like_ram(text: str | None) -> bool:
    return bool(re.search(r"\b(memory|ram)\b", text or "", re.IGNORECASE))


def looks_like_storage(text: str | None) -> bool:
    return bool(re.search(r"storage|hard drive|hard disk|disk space|drive space|available space|free space", text or "", re.IGNORECASE))


def split_combined_levels(raw_html: str | None) -> dict:
    if not clean_text(raw_html):
        return {}

    text = str(raw_html)
    pattern = re.compile(r"(?:<strong>\s*)?(Minimum|Recommended)\s*:?\s*(?:</strong>)?", re.IGNORECASE)
    matches = list(pattern.finditer(text))
    if not matches:
        return {}

    sections = {}
    for index, match in enumerate(matches):
        label = match.group(1).lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            sections[label] = chunk
    return sections


def assign_from_label(req: dict, label: str | None, value: str | None) -> bool:
    normalized = normalize_label(label)
    text = clean_text(value)
    if not normalized or not text:
        return False

    if "os" in normalized or "operating system" in normalized or "supported os" in normalized:
        req["os"] = choose_better_text(req["os"], text)
        return True

    if normalized == "processor" or "cpu" in normalized:
        req["cpu"] = choose_better_text(req["cpu"], text)
        return True

    if normalized in {"graphics", "video card", "video"} or normalized.startswith("video card "):
        req["gpu"] = choose_better_text(req["gpu"], text)
        req["vram_gb"] = req["vram_gb"] if req["vram_gb"] is not None else parse_graphics_memory_gb(text)
        update_graphics_api_fields(req, text)
        return True

    if "graphics api" in normalized or "graphics api angle" in normalized or "graphics api opengl" in normalized:
        update_graphics_api_fields(req, text)
        return True

    if "directx" in normalized:
        update_graphics_api_fields(req, f"DirectX {text}")
        return True

    if "opengl" in normalized:
        update_graphics_api_fields(req, f"OpenGL {text}")
        return True

    if "vulkan" in normalized:
        update_graphics_api_fields(req, f"Vulkan {text}")
        return True

    if normalized in {"memory", "system memory"}:
        req["ram_gb"] = req["ram_gb"] if req["ram_gb"] is not None else parse_size_in_gb(text)
        return True

    if "hard drive" in normalized or "hard disk" in normalized or normalized == "storage":
        req["storage_gb"] = req["storage_gb"] if req["storage_gb"] is not None else parse_size_in_gb(text)
        return True

    return False


def parse_freeform_line(req: dict, line: str | None) -> None:
    text = clean_text(line)
    if not text:
        return

    update_graphics_api_fields(req, text)

    if not req["os"] and looks_like_os(text):
        req["os"] = text
        return

    if looks_like_storage(text):
        req["storage_gb"] = req["storage_gb"] if req["storage_gb"] is not None else parse_size_in_gb(text)
        return

    if looks_like_ram(text):
        req["ram_gb"] = req["ram_gb"] if req["ram_gb"] is not None else parse_size_in_gb(text)
        return

    if not req["gpu"] and looks_like_gpu(text):
        req["gpu"] = text
        req["vram_gb"] = req["vram_gb"] if req["vram_gb"] is not None else parse_graphics_memory_gb(text)
        return

    if not req["cpu"] and looks_like_cpu(text):
        req["cpu"] = text


def parse_requirement_block(raw_html: str | None) -> dict:
    req = create_requirement()
    req["raw_html"] = str(raw_html) if clean_text(raw_html) else None
    if not req["raw_html"]:
        return req

    stripped = strip_html(req["raw_html"])
    if not stripped:
        return req

    lines = [
        clean_text(line)
        for line in stripped.split("\n")
    ]
    lines = [
        line for line in lines
        if line and not re.fullmatch(r"(minimum|recommended):?", line, flags=re.IGNORECASE)
    ]

    for line in lines:
        line = re.sub(r"^(minimum|recommended):\s*", "", line, flags=re.IGNORECASE)
        labeled = re.match(r"^([^:]{2,40}):\s*(.+)$", line)
        if labeled and assign_from_label(req, labeled.group(1), labeled.group(2)):
            continue

        segments = [clean_text(part) for part in re.split(r"\s*,\s*", line)]
        for segment in segments:
            if segment:
                parse_freeform_line(req, segment)

    if req["ram_gb"] is not None and req["storage_gb"] is not None and req["ram_gb"] > req["storage_gb"]:
        req["ram_gb"], req["storage_gb"] = req["storage_gb"], req["ram_gb"]

    return req


def parse_requirements_field(field) -> dict:
    direct_minimum = field.get("minimum") if isinstance(field, dict) else None
    direct_recommended = field.get("recommended") if isinstance(field, dict) else None
    combined_raw = field if isinstance(field, str) else None
    sections = split_combined_levels(combined_raw or direct_minimum or "")

    minimum_raw = sections.get("minimum") or direct_minimum or (field if isinstance(field, str) else None)
    recommended_raw = sections.get("recommended") or direct_recommended

    return {
      "minimum": parse_requirement_block(minimum_raw),
      "recommended": parse_requirement_block(recommended_raw),
    }


def has_useful_requirement(req: dict | None) -> bool:
    if not req:
        return False
    return any([
        req.get("os"),
        req.get("cpu"),
        req.get("gpu"),
        req.get("ram_gb") is not None,
        req.get("storage_gb") is not None,
    ])
