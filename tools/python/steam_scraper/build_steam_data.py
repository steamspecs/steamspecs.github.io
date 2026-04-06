from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import argparse
import json
from pathlib import Path
import shutil
import time
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from steam_scraper.component_matcher import annotate_requirement_components, load_catalogs
from steam_scraper.requirements_parser import clean_text, has_useful_requirement, parse_requirements_field


APP_LIST_URL = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails?appids={appid}&l=english&cc=us"
DEFAULT_CONCURRENCY = 4
DEFAULT_SHARD_SIZE = 2000


@dataclass
class Args:
    concurrency: int
    shard_size: int
    cache_dir: Path
    output_dir: Path
    offset: int
    limit: int | None
    only_build: bool
    refresh: bool
    appids: list[int] | None
    catalog_dir: Path


def parse_args() -> Args:
    parser = argparse.ArgumentParser(description="Scrape Steam requirements and build shard data.")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--shard-size", type=int, default=DEFAULT_SHARD_SIZE)
    parser.add_argument("--cache-dir", default=".cache/steam")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--appids", type=str, help="Comma-separated app ids")
    parser.add_argument("--catalog-dir", default="data/catalog")
    parser.add_argument("--only-build", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    ns = parser.parse_args()

    appids = None
    if ns.appids:
        appids = [int(part.strip()) for part in ns.appids.split(",") if part.strip().isdigit()]

    return Args(
        concurrency=max(1, ns.concurrency),
        shard_size=max(1, ns.shard_size),
        cache_dir=Path(ns.cache_dir),
        output_dir=Path(ns.output_dir),
        offset=max(0, ns.offset),
        limit=ns.limit,
        only_build=ns.only_build,
        refresh=ns.refresh,
        appids=appids,
        catalog_dir=Path(ns.catalog_dir),
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def fetch_json(url: str):
    request = Request(url, headers={"User-Agent": "steamspecs-python-scraper/1.0"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_json_with_retry(url: str, attempts: int = 4):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return fetch_json(url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt == attempts:
                break
            time.sleep(0.8 * attempt)
    raise last_error


def get_app_list(cache_dir: Path, refresh: bool):
    cache_file = cache_dir / "app-list.json"
    if cache_file.exists() and not refresh:
        return read_json(cache_file)

    data = fetch_json_with_retry(APP_LIST_URL)
    write_json(cache_file, data)
    return data


def get_app_details(appid: int, cache_dir: Path, refresh: bool):
    cache_file = cache_dir / "appdetails" / f"{appid}.json"
    if cache_file.exists() and not refresh:
        return read_json(cache_file)

    data = fetch_json_with_retry(APP_DETAILS_URL.format(appid=appid))
    write_json(cache_file, data)
    return data


def normalize_requirement_set(field, catalogs: dict[str, list[dict]]):
    parsed = parse_requirements_field(field)
    return {
        "minimum": annotate_requirement_components(parsed["minimum"], catalogs),
        "recommended": annotate_requirement_components(parsed["recommended"], catalogs),
    }


def normalize_app_record(appid: int, payload, catalogs: dict[str, list[dict]]):
    entry = payload.get(str(appid)) or payload.get(appid)
    data = entry.get("data") if isinstance(entry, dict) else None
    if not data:
        return None

    requirements = {
        "pc": normalize_requirement_set(data.get("pc_requirements"), catalogs),
        "mac": normalize_requirement_set(data.get("mac_requirements"), catalogs),
        "linux": normalize_requirement_set(data.get("linux_requirements"), catalogs),
    }

    has_requirements = any(
        has_useful_requirement(levels["minimum"]) or has_useful_requirement(levels["recommended"])
        for levels in requirements.values()
    )

    return {
        "appid": int(appid),
        "name": clean_text(data.get("name")),
        "type": clean_text(data.get("type")),
        "requirements": requirements if has_requirements else None,
    }


def build_index(apps: list[dict], shard_size: int) -> dict:
    highest_appid = apps[-1]["appid"] if apps else 0
    return {
        "version": 2,
        "shard_size": shard_size,
        "total_apps": len(apps),
        "total_shards": (highest_appid // shard_size) + 1 if apps else 0,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "apps": [
            {
                "appid": app["appid"],
                "name": app["name"],
                "type": app["type"],
                "has_requirements": bool(app["requirements"]),
            }
            for app in apps
        ],
    }


def write_dataset(apps: list[dict], output_dir: Path, shard_size: int) -> None:
    shards_dir = output_dir / "shards"
    ensure_dir(shards_dir)

    if shards_dir.exists():
        for shard_file in shards_dir.glob("shard_*.json"):
            shard_file.unlink()

    shard_map: dict[int, list[dict]] = {}
    for app in apps:
        shard_id = app["appid"] // shard_size
        shard_map.setdefault(shard_id, []).append(app)

    for shard_id, shard_apps in shard_map.items():
        write_json(shards_dir / f"shard_{shard_id:05d}.json", shard_apps)

    write_json(output_dir / "index.json", build_index(apps, shard_size))


def collect_cached_apps(cache_dir: Path, catalogs: dict[str, list[dict]], selected_appids: Iterable[int] | None = None) -> list[dict]:
    details_dir = cache_dir / "appdetails"
    if not details_dir.exists():
        return []

    allowed = set(selected_appids) if selected_appids is not None else None
    apps: list[dict] = []

    for file_path in sorted(details_dir.glob("*.json")):
        appid = int(file_path.stem)
        if allowed is not None and appid not in allowed:
            continue

        payload = read_json(file_path)
        record = normalize_app_record(appid, payload, catalogs)
        if record:
            apps.append(record)

    apps.sort(key=lambda app: app["appid"])
    return apps


def scrape_app_details(appids: list[int], args: Args) -> None:
    completed = 0

    def worker(appid: int) -> int:
        get_app_details(appid, args.cache_dir, args.refresh)
        return appid

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(worker, appid) for appid in appids]
        for future in as_completed(futures):
            future.result()
            completed += 1
            if completed % 25 == 0 or completed == len(appids):
                print(f"Fetched {completed}/{len(appids)} app detail payloads")


def remove_cache(cache_dir: Path) -> None:
    if cache_dir.exists():
        shutil.rmtree(cache_dir)


def main() -> None:
    args = parse_args()
    ensure_dir(args.cache_dir)
    catalogs = load_catalogs(args.catalog_dir)

    selected_appids = args.appids

    if not args.only_build:
        app_list = get_app_list(args.cache_dir, args.refresh)
        apps = app_list.get("applist", {}).get("apps", [])

        if selected_appids:
            sliced = [app for app in apps if app.get("appid") in selected_appids]
        else:
            end = args.offset + args.limit if args.limit is not None else None
            sliced = apps[args.offset:end]

        selected_appids = [int(app["appid"]) for app in sliced]
        print(f"Preparing to scrape {len(selected_appids)} Steam apps")
        scrape_app_details(selected_appids, args)

    normalized_apps = collect_cached_apps(args.cache_dir, catalogs, selected_appids)
    write_dataset(normalized_apps, args.output_dir, args.shard_size)
    print(f"Wrote {len(normalized_apps)} apps to {args.output_dir}")


if __name__ == "__main__":
    main()
