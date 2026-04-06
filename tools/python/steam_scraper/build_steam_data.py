from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import argparse
import json
from pathlib import Path
import time
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from steam_scraper.component_matcher import annotate_requirement_components, load_catalogs
from steam_scraper.requirements_parser import clean_text, has_useful_requirement, parse_requirements_field


APP_LIST_URLS = [
    "https://api.steampowered.com/ISteamApps/GetAppList/v0002/",
    "https://api.steampowered.com/ISteamApps/GetAppList/v2/",
]
APP_LIST_MIRROR_URLS = [
    "https://raw.githubusercontent.com/jsnli/steamappidlist/master/data/games_appid.json",
    "https://raw.githubusercontent.com/jsnli/steamappidlist/master/data/dlc_appid.json",
    "https://raw.githubusercontent.com/jsnli/steamappidlist/master/data/software_appid.json",
]
APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails?appids={appid}&l=english&cc=us"
DEFAULT_CONCURRENCY = 4
DEFAULT_SHARD_SIZE = 2000
DEFAULT_DISCOVER_WINDOW = 2000
DEFAULT_DISCOVER_MISS_LIMIT = 400
ALLOWED_TYPES = {"game", "dlc", "software"}


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
    seed_index: Path
    discover: bool
    discover_window: int
    discover_miss_limit: int


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
    parser.add_argument("--seed-index", default="data/index.json")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--discover-window", type=int, default=DEFAULT_DISCOVER_WINDOW)
    parser.add_argument("--discover-miss-limit", type=int, default=DEFAULT_DISCOVER_MISS_LIMIT)
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
        seed_index=Path(ns.seed_index),
        discover=ns.discover,
        discover_window=max(1, ns.discover_window),
        discover_miss_limit=max(1, ns.discover_miss_limit),
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def load_discovery_state(cache_dir: Path) -> dict:
    state_file = cache_dir / "discovery-state.json"
    if not state_file.exists():
        return {
            "last_checked_appid": None,
            "last_found_appid": None,
            "consecutive_misses": 0,
        }
    return read_json(state_file)


def save_discovery_state(cache_dir: Path, state: dict) -> None:
    write_json(cache_dir / "discovery-state.json", state)


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
    raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error


def load_seed_app_list(seed_index: Path):
    if not seed_index.exists():
        return None

    seed = read_json(seed_index)
    apps = seed.get("apps")
    if not isinstance(apps, list):
        return None

    return {
        "applist": {
            "apps": [
                {
                    "appid": app.get("appid"),
                    "name": app.get("name"),
                }
                for app in apps
                if app.get("appid") is not None
            ]
        }
    }


def merge_app_lists(*lists) -> dict:
    apps_by_id = {}

    for payload in lists:
        for app in payload.get("applist", {}).get("apps", []):
            appid = app.get("appid")
            if appid is None:
                continue
            apps_by_id[int(appid)] = {
                "appid": int(appid),
                "name": app.get("name"),
            }

    merged_apps = sorted(apps_by_id.values(), key=lambda item: item["appid"])
    return {"applist": {"apps": merged_apps}}


def load_mirror_app_list():
    payloads = []
    errors = []

    for url in APP_LIST_MIRROR_URLS:
        try:
            payload = fetch_json_with_retry(url)
            if isinstance(payload, list):
                payloads.append({
                    "applist": {
                        "apps": [
                            {
                                "appid": app.get("appid"),
                                "name": app.get("name"),
                            }
                            for app in payload
                            if isinstance(app, dict) and app.get("appid") is not None
                        ]
                    }
                })
            else:
                errors.append(f"Unexpected mirror payload shape from {url}")
        except RuntimeError as error:
            errors.append(str(error))

    if payloads:
        return merge_app_lists(*payloads)

    return None, errors


def get_app_list(cache_dir: Path, refresh: bool, seed_index: Path | None = None):
    cache_file = cache_dir / "app-list.json"
    if cache_file.exists() and not refresh:
        return read_json(cache_file)

    errors = []
    for url in APP_LIST_URLS:
        try:
            data = fetch_json_with_retry(url)
            write_json(cache_file, data)
            return data
        except RuntimeError as error:
            errors.append(str(error))

    mirror_result = load_mirror_app_list()
    if isinstance(mirror_result, dict):
        print("Falling back to GitHub app list mirror")
        write_json(cache_file, mirror_result)
        return mirror_result

    seed_data = load_seed_app_list(seed_index) if seed_index else None
    if seed_data:
        print(f"Falling back to seed app list from {seed_index}")
        write_json(cache_file, seed_data)
        return seed_data

    mirror_errors = mirror_result[1] if isinstance(mirror_result, tuple) else []
    raise RuntimeError(
        "Failed to fetch Steam app list from all known endpoints:\n"
        + "\n".join(errors + mirror_errors)
    )


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

    app_type = clean_text(data.get("type"))
    if app_type not in ALLOWED_TYPES:
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
        "type": app_type,
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

def discover_new_appids(base_appids: list[int], args: Args, catalogs: dict[str, list[dict]]) -> list[int]:
    if not args.discover:
        return []

    state = load_discovery_state(args.cache_dir)
    known_ids = set(int(appid) for appid in base_appids)
    highest_known = max(known_ids) if known_ids else 0
    start_appid = max(highest_known + 1, (state.get("last_checked_appid") or highest_known) + 1)

    print(
        f"Starting discovery scan at appid {start_appid} "
        f"(window={args.discover_window}, miss_limit={args.discover_miss_limit})"
    )

    discovered_ids: list[int] = []
    consecutive_misses = 0

    for appid in range(start_appid, start_appid + args.discover_window):
        payload = get_app_details(appid, args.cache_dir, False)
        record = normalize_app_record(appid, payload, catalogs)

        state["last_checked_appid"] = appid

        if record:
            discovered_ids.append(appid)
            known_ids.add(appid)
            consecutive_misses = 0
            state["last_found_appid"] = appid
            state["consecutive_misses"] = 0
            if len(discovered_ids) <= 10 or len(discovered_ids) % 25 == 0:
                print(f"Discovered appid {appid}: {record['name']} ({record['type']})")
        else:
            consecutive_misses += 1
            state["consecutive_misses"] = consecutive_misses
            if consecutive_misses >= args.discover_miss_limit:
                print(f"Stopping discovery after {consecutive_misses} consecutive misses at appid {appid}")
                save_discovery_state(args.cache_dir, state)
                return discovered_ids

        save_discovery_state(args.cache_dir, state)

    print(f"Finished discovery window with {len(discovered_ids)} newly discovered apps")
    return discovered_ids


def main() -> None:
    args = parse_args()
    ensure_dir(args.cache_dir)
    catalogs = load_catalogs(args.catalog_dir)

    selected_appids = args.appids

    if not args.only_build:
        app_list = get_app_list(args.cache_dir, args.refresh, args.seed_index)
        apps = app_list.get("applist", {}).get("apps", [])

        if selected_appids:
            sliced = [app for app in apps if app.get("appid") in selected_appids]
        else:
            end = args.offset + args.limit if args.limit is not None else None
            sliced = apps[args.offset:end]

        selected_appids = [int(app["appid"]) for app in sliced]

        if args.discover and args.appids is None and args.limit is None:
            discovered_ids = discover_new_appids(selected_appids, args, catalogs)
            selected_appids.extend(appid for appid in discovered_ids if appid not in selected_appids)

        print(f"Preparing to scrape {len(selected_appids)} Steam apps")
        scrape_app_details(selected_appids, args)

    normalized_apps = collect_cached_apps(args.cache_dir, catalogs, selected_appids)
    write_dataset(normalized_apps, args.output_dir, args.shard_size)
    print(f"Wrote {len(normalized_apps)} apps to {args.output_dir}")


if __name__ == "__main__":
    main()
