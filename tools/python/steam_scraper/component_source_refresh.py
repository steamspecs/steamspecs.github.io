from __future__ import annotations

import argparse
import csv
import html
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


PASSMARK_CPU_URL = "https://www.cpubenchmark.net/common_cpus.html"
PASSMARK_GPU_URL = "https://www.videocardbenchmark.net/common_gpus.html"
PASSMARK_CPU_LIST_URL = "https://www.cpubenchmark.net/cpu_list.php"
PASSMARK_GPU_LIST_URL = "https://www.videocardbenchmark.net/gpu_list.php"
TECHPOWERUP_CPU_URL = "https://www.techpowerup.com/cpu-specs/"
PC_PART_DATASET_CPU_URL = "https://raw.githubusercontent.com/docyx/pc-part-dataset/main/data/json/cpu.json"
PC_PART_DATASET_GPU_URL = "https://raw.githubusercontent.com/docyx/pc-part-dataset/main/data/json/video-card.json"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if data:
            self.parts.append(data)

    def get_text(self) -> str:
        text = html.unescape("".join(self.parts))
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return text


class TableExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
        elif tag == "br" and self._current_cell is not None:
            self._current_cell.append("\n")

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            value = html.unescape("".join(self._current_cell)).strip()
            self._current_row.append(re.sub(r"\s+", " ", value))
            self._current_cell = None
        elif tag == "tr" and self._current_table is not None and self._current_row is not None:
            if any(cell.strip() for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = None

    def handle_data(self, data):
        if self._current_cell is not None and data:
            self._current_cell.append(data)


class RefreshSkip(Exception):
    pass


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "steamspecs-component-refresh/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_json(url: str):
    import json
    return json.loads(fetch_text(url))


def html_to_text(value: str) -> str:
    parser = TextExtractor()
    parser.feed(value)
    return parser.get_text()


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def split_brand_and_model(name: str) -> tuple[str | None, str]:
    clean_name = re.sub(r"\s+", " ", name).strip()
    for brand in ["Intel", "AMD", "NVIDIA", "GeForce", "Radeon", "Apple", "Qualcomm"]:
        if clean_name.lower().startswith(brand.lower() + " "):
            return brand if brand not in {"GeForce", "Radeon"} else ("NVIDIA" if brand == "GeForce" else "AMD"), clean_name[len(brand):].strip()
    return None, clean_name


def parse_clock_range_ghz(value: str) -> tuple[float | None, float | None]:
    raw = value.lower().strip()
    divider = 1000 if "mhz" in raw and "ghz" not in raw else 1
    text = raw.replace("ghz", "").replace("mhz", "").strip()
    parts = [part.strip() for part in text.split("to")]
    numbers = []
    for part in parts:
        match = re.search(r"(\d+(?:\.\d+)?)", part)
        if match:
            numbers.append(float(match.group(1)) / divider)
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return numbers[0], numbers[1]


def parse_cores_threads(value: str) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*/\s*(\d+)", value)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"(\d+)c(?:\s*/\s*(\d+)t)?", value.lower())
    if match:
        cores = int(match.group(1))
        threads = int(match.group(2)) if match.group(2) else cores
        return cores, threads
    match = re.search(r"(\d+)", value)
    if match:
        cores = int(match.group(1))
        return cores, cores
    return None, None


def parse_gpu_memory_gb(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*GB", value, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)\s*MB", value, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 1024
    return None


def parse_api_number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", value, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def parse_memory_gb(value) -> float | None:
    if value in (None, ""):
        return None
    raw = str(value).strip().lower().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(gb|gib|mb|mib)?", raw)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or ""
    if unit.startswith("m"):
        return round(amount / 1024.0, 6)
    return amount


def get_nested_value(record: dict, *keys):
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def iter_records(payload):
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(payload, dict):
        for key in ["data", "items", "results", "cpus", "gpus", "video_cards", "processors"]:
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        yield item
                return
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                for item in value:
                    yield item
                return


def parse_passmark_rows(text: str, item_label: str, score_label: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines()]
    rows: list[dict] = []
    pattern = re.compile(
        r"^(?P<name>.+?)\s+\((?P<pct>[\d.]+)%\)\s+(?P<score>[\d,]+)\s+(?P<price>NA|[\d,]+(?:\.\d+)?\*?)$"
    )
    fallback_pattern = re.compile(r"^(?P<name>.+?)\s+(?P<score>[\d,]{3,})\s+(?P<price>NA|[\d,]+(?:\.\d+)?\*?)$")

    for line in lines:
        if not line:
            continue
        if line.startswith("PassMark - ") or line.startswith("Updated "):
            continue
        if line in {item_label, score_label, "Price (USD)", "Price Performance"}:
            continue
        if line.startswith("Common CPUs") or line.startswith("Common Videocards"):
            continue

        match = pattern.match(line)
        if match:
            rows.append({
                "name": match.group("name").strip(),
                "score": match.group("score").replace(",", ""),
            })
            continue

        fallback_match = fallback_pattern.match(line)
        if not fallback_match:
            continue

        name = fallback_match.group("name").strip()
        if len(name) < 4:
            continue
        if name.lower() in {"cpu", "videocard", "common cpus", "common videocards"}:
            continue

        rows.append({
            "name": name,
            "score": fallback_match.group("score").replace(",", ""),
        })

    if not rows:
        raise RuntimeError(f"Could not parse any PassMark rows for {item_label}")

    deduped: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        key = row["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def parse_passmark_chart_html(html_text: str) -> list[dict]:
    pattern = re.compile(
        r'<li id="rk[^"]*".*?<span class="prdname"\s*>(?P<name>.*?)</span>.*?<span class="count">(?P<score>[\d,]+)</span>',
        re.IGNORECASE | re.DOTALL,
    )
    rows: list[dict] = []
    seen: set[str] = set()

    for match in pattern.finditer(html_text):
        name = html.unescape(re.sub(r"<[^>]+>", "", match.group("name"))).strip()
        score = match.group("score").replace(",", "")
        if not name or not score:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"name": name, "score": score})

    return rows


def parse_passmark_table_html(html_text: str) -> list[dict]:
    parser = TableExtractor()
    parser.feed(html_text)

    rows: list[dict] = []
    seen: set[str] = set()

    for table in parser.tables:
        for row in table:
            if len(row) < 2:
                continue
            name = row[0].strip()
            score_text = row[1].strip()
            if not name or not score_text:
                continue
            if name.lower() in {
                "cpu name",
                "videocard name",
                "cpu",
                "videocard",
            }:
                continue
            if not re.fullmatch(r"[\d,]+", score_text):
                continue

            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append({"name": name, "score": score_text.replace(",", "")})

    return rows


def parse_techpowerup_cpu_search_snippet(text: str) -> list[dict]:
    match = re.search(
        r"Name\s+\|\s+Codename\s+\|\s+Cores\s+\|\s+Clock.*?(?=Most Popular Processors|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []

    snippet = match.group(0)
    lines = [line.strip() for line in snippet.splitlines() if line.strip()]
    rows: list[dict] = []
    for line in lines:
        if "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 8:
            continue
        if parts[0].lower() == "name" or set(parts[0]) == {"-"}:
            continue

        name, codename, cores_text, clock_text = parts[0], parts[1], parts[2], parts[3]
        brand, model_name = split_brand_and_model(name)
        cores, threads = parse_cores_threads(cores_text)
        base_ghz, boost_ghz = parse_clock_range_ghz(clock_text)
        rows.append({
            "name": name,
            "brand": brand,
            "family": codename or None,
            "model": model_name,
            "cores": cores,
            "threads": threads,
            "base_ghz": base_ghz,
            "boost_ghz": boost_ghz,
        })

    return rows


def parse_techpowerup_gpu_search_snippet(text: str) -> list[dict]:
    match = re.search(
        r"Name\s+\|\s+Bus\s+\|\s+Memory\s+\|\s+GPU Clock.*?(?=100 most popular GPUs listed|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []

    snippet = match.group(0)
    lines = [line.strip() for line in snippet.splitlines() if line.strip()]
    rows: list[dict] = []
    for line in lines:
        if "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 6:
            continue
        if parts[0].lower() == "name" or set(parts[0]) == {"-"}:
            continue

        name = re.sub(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b.*$", "", parts[0]).strip()
        memory_text = parts[2]
        clock_text = parts[3]
        cores_text = parts[5]
        brand, model_name = split_brand_and_model(name)
        base_ghz, boost_ghz = parse_clock_range_ghz(clock_text.replace("MHz", " MHz"))
        if base_ghz is not None:
            base_ghz = round(base_ghz / 1000, 3) if base_ghz > 100 else base_ghz
        if boost_ghz is not None:
            boost_ghz = round(boost_ghz / 1000, 3) if boost_ghz > 100 else boost_ghz
        cores, _ = parse_cores_threads(cores_text)
        rows.append({
            "name": name,
            "brand": brand,
            "family": None,
            "model": model_name,
            "vram_gb": parse_gpu_memory_gb(memory_text),
            "cores": cores,
            "base_ghz": base_ghz,
            "boost_ghz": boost_ghz,
        })

    return rows


def parse_techpowerup_cpu_html(html_text: str) -> list[dict]:
    parser = TableExtractor()
    parser.feed(html_text)

    rows: list[dict] = []
    seen: set[str] = set()

    for table in parser.tables:
        for row in table:
            if len(row) < 9:
                continue

            name = row[0].strip()
            codename = row[1].strip()
            cores_text = row[2].strip()
            clock_text = row[3].strip()

            if not name or name.lower() == "name":
                continue
            if set(name) == {"-"}:
                continue

            brand, model_name = split_brand_and_model(name)
            cores, threads = parse_cores_threads(cores_text)
            base_ghz, boost_ghz = parse_clock_range_ghz(clock_text)
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)

            rows.append({
                "name": name,
                "brand": brand,
                "family": codename or None,
                "model": model_name,
                "cores": cores,
                "threads": threads,
                "base_ghz": base_ghz,
                "boost_ghz": boost_ghz,
            })

    return rows


def refresh_passmark_cpu_scores(output_path: Path) -> int:
    html_text = fetch_text(PASSMARK_CPU_URL)
    parsed = parse_passmark_chart_html(html_text)
    if not parsed:
        text = html_to_text(html_text)
        parsed = parse_passmark_rows(text, "CPU", "CPU Mark")
    write_csv(output_path, parsed, ["name", "score"])
    return len(parsed)


def refresh_passmark_gpu_scores(output_path: Path) -> int:
    html_text = fetch_text(PASSMARK_GPU_URL)
    parsed = parse_passmark_chart_html(html_text)
    if not parsed:
        text = html_to_text(html_text)
        parsed = parse_passmark_rows(text, "Videocard", "Average G3D Mark")
    write_csv(output_path, parsed, ["name", "score"])
    return len(parsed)


def refresh_passmark_cpu_catalog(output_path: Path) -> int:
    html_text = fetch_text(PASSMARK_CPU_LIST_URL)
    parsed = parse_passmark_table_html(html_text)
    if not parsed:
        text = html_to_text(html_text)
        parsed = parse_passmark_rows(text, "CPU Name", "CPU Mark")
    write_csv(output_path, parsed, ["name", "score"])
    return len(parsed)


def refresh_passmark_gpu_catalog(output_path: Path) -> int:
    html_text = fetch_text(PASSMARK_GPU_LIST_URL)
    parsed = parse_passmark_table_html(html_text)
    if not parsed:
        text = html_to_text(html_text)
        parsed = parse_passmark_rows(text, "Videocard Name", "Passmark G3D Mark")
    write_csv(output_path, parsed, ["name", "score"])
    return len(parsed)


def refresh_techpowerup_cpu_specs(output_path: Path) -> int:
    html_text = fetch_text(TECHPOWERUP_CPU_URL)
    parsed = parse_techpowerup_cpu_html(html_text)
    if not parsed:
        parsed = parse_techpowerup_cpu_search_snippet(html_to_text(html_text))
    if not parsed:
        raise RuntimeError("Could not parse any TechPowerUp CPU rows")
    write_csv(output_path, parsed, ["name", "brand", "family", "model", "cores", "threads", "base_ghz", "boost_ghz"])
    return len(parsed)


def find_header_index(headers: list[str], patterns: list[str]) -> int | None:
    normalized_headers = [re.sub(r"\s+", " ", header.strip().lower()) for header in headers]
    for pattern in patterns:
        for index, header in enumerate(normalized_headers):
            if pattern in header:
                return index
    return None


def refresh_pc_part_cpu_specs(output_path: Path) -> int:
    payload = fetch_json(PC_PART_DATASET_CPU_URL)
    rows: list[dict] = []
    seen: set[str] = set()

    for record in iter_records(payload):
        name = str(get_nested_value(record, "name", "model_name", "product_name", "cpu", "title") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        brand, model_name = split_brand_and_model(name)
        explicit_brand = get_nested_value(record, "brand", "manufacturer", "vendor")
        if explicit_brand:
            brand = str(explicit_brand).strip()

        base_ghz = None
        boost_ghz = None
        for source_value in [
            get_nested_value(record, "base_clock", "base_clock_ghz", "base_frequency", "processor_base_frequency"),
            get_nested_value(record, "clock_speed", "frequency"),
        ]:
            if source_value not in (None, ""):
                base_ghz, _ = parse_clock_range_ghz(str(source_value))
                if base_ghz is not None:
                    break
        source_value = get_nested_value(record, "boost_clock", "boost_clock_ghz", "max_boost_clock", "max_turbo_frequency")
        if source_value not in (None, ""):
            _, boost_ghz = parse_clock_range_ghz(str(source_value))

        rows.append({
            "name": name,
            "brand": brand,
            "family": str(get_nested_value(record, "family", "series", "codename") or "").strip() or None,
            "model": str(get_nested_value(record, "model", "sku", "part_number") or model_name).strip(),
            "cores": get_nested_value(record, "cores", "core_count", "num_cores"),
            "threads": get_nested_value(record, "threads", "thread_count", "num_threads"),
            "base_ghz": base_ghz,
            "boost_ghz": boost_ghz,
            "process_nm": parse_api_number(str(get_nested_value(record, "process_nm", "lithography", "manufacturing_process") or "")),
            "release_year": get_nested_value(record, "release_year", "launch_year"),
        })

    if not rows:
        raise RuntimeError("Could not parse any pc-part-dataset CPU rows")
    write_csv(output_path, rows, ["name", "brand", "family", "model", "cores", "threads", "base_ghz", "boost_ghz", "process_nm", "release_year"])
    return len(rows)


def refresh_pc_part_gpu_specs(output_path: Path) -> int:
    payload = fetch_json(PC_PART_DATASET_GPU_URL)
    rows: list[dict] = []
    seen: set[str] = set()

    for record in iter_records(payload):
        name = str(get_nested_value(record, "name", "model_name", "product_name", "video_card", "title") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        brand, model_name = split_brand_and_model(name)
        explicit_brand = get_nested_value(record, "brand", "manufacturer", "vendor")
        if explicit_brand:
            brand = str(explicit_brand).strip()

        rows.append({
            "name": name,
            "brand": brand,
            "family": str(get_nested_value(record, "family", "series", "architecture") or "").strip() or None,
            "model": str(get_nested_value(record, "model", "sku", "part_number") or model_name).strip(),
            "vram_gb": parse_memory_gb(get_nested_value(record, "memory", "memory_size", "memory_capacity", "vram", "memory_amount")),
            "base_ghz": parse_api_number(str(get_nested_value(record, "base_clock", "gpu_clock", "core_clock") or "")),
            "boost_ghz": parse_api_number(str(get_nested_value(record, "boost_clock", "boost_gpu_clock") or "")),
            "release_year": get_nested_value(record, "release_year", "launch_year"),
            "process_nm": parse_api_number(str(get_nested_value(record, "process_nm", "lithography", "manufacturing_process") or "")),
            "directx": parse_api_number(str(get_nested_value(record, "directx", "directx_support", "api_directx") or "")),
            "opengl": parse_api_number(str(get_nested_value(record, "opengl", "opengl_support", "api_opengl") or "")),
            "shader_model": parse_api_number(str(get_nested_value(record, "shader_model", "shader", "shader_support") or "")),
            "architecture": str(get_nested_value(record, "architecture", "gpu_architecture") or "").strip() or None,
            "bus_interface": str(get_nested_value(record, "bus_interface", "interface", "bus") or "").strip() or None,
            "memory_type": str(get_nested_value(record, "memory_type", "ram_type") or "").strip() or None,
        })

    if not rows:
        raise RuntimeError("Could not parse any pc-part-dataset GPU rows")
    write_csv(output_path, rows, ["name", "brand", "family", "model", "vram_gb", "base_ghz", "boost_ghz", "release_year", "process_nm", "directx", "opengl", "shader_model", "architecture", "bus_interface", "memory_type"])
    return len(rows)


def parse_args():
    parser = argparse.ArgumentParser(description="Refresh component import CSVs from remote sources.")
    parser.add_argument("--imports-dir", default="data/catalog/imports")
    parser.add_argument("--skip-passmark", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    refresh_imports(
        Path(args.imports_dir),
        skip_passmark=args.skip_passmark,
        strict=args.strict,
    )


def refresh_imports(
    imports_dir: Path,
    skip_passmark: bool = False,
    strict: bool = False,
) -> None:
    imports_dir = Path(imports_dir)
    imports_dir.mkdir(parents=True, exist_ok=True)

    refreshed: list[str] = []
    warnings: list[str] = []
    if not skip_passmark:
        sources = [
            ("TechPowerUp CPUs", refresh_techpowerup_cpu_specs, "techpowerup_cpus.csv"),
            ("PC Part Dataset CPUs", refresh_pc_part_cpu_specs, "pc_part_cpus.csv"),
            ("PC Part Dataset GPUs", refresh_pc_part_gpu_specs, "pc_part_gpus.csv"),
            ("PassMark CPU catalog", refresh_passmark_cpu_catalog, "passmark_cpu_catalog.csv"),
            ("PassMark GPU catalog", refresh_passmark_gpu_catalog, "passmark_gpu_catalog.csv"),
            ("PassMark CPUs", refresh_passmark_cpu_scores, "passmark_cpus.csv"),
            ("PassMark GPUs", refresh_passmark_gpu_scores, "passmark_gpus.csv"),
        ]

        for label, fn, filename in sources:
            try:
                count = fn(imports_dir / filename)
                refreshed.append(f"{label}: {count}")
            except RefreshSkip as exc:
                warnings.append(f"{label} refresh skipped: {exc}")
            except Exception as exc:
                existing = imports_dir / filename
                debug_name = filename.replace(".csv", "_debug.html")
                if strict:
                    raise
                try:
                    if "TechPowerUp" in label and "CPU" in label:
                        source_url = TECHPOWERUP_CPU_URL
                    elif "PC Part Dataset" in label and "CPU" in label:
                        source_url = PC_PART_DATASET_CPU_URL
                    elif "PC Part Dataset" in label:
                        source_url = PC_PART_DATASET_GPU_URL
                    elif "CPU catalog" in label:
                        source_url = PASSMARK_CPU_LIST_URL
                    elif "GPU catalog" in label:
                        source_url = PASSMARK_GPU_LIST_URL
                    else:
                        source_url = PASSMARK_CPU_URL if "CPU" in label else PASSMARK_GPU_URL
                    write_text(imports_dir / debug_name, fetch_text(source_url))
                except Exception:
                    pass
                if existing.exists():
                    warnings.append(f"{label} refresh failed, keeping existing {filename}: {exc}. Saved debug HTML to {debug_name}")
                else:
                    warnings.append(f"{label} refresh failed and no local {filename} exists yet: {exc}. Saved debug HTML to {debug_name}")

    if not refreshed:
        print("No component sources were refreshed.")
    else:
        print("Refreshed component source CSVs:")
        for line in refreshed:
            print(f"- {line}")

    for warning in warnings:
        print(f"Warning: {warning}")


if __name__ == "__main__":
    main()
