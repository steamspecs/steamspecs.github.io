import argparse
import datetime as dt
import html as htmllib
import json
import os
import random
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PARTNER_ISTORE_GETAPPLIST = "https://partner.steam-api.com/IStoreService/GetAppList/v1/"
STORE_API_APPDETAILS = "https://store.steampowered.com/api/appdetails"

LABEL_RE = re.compile(r"^\s*([^:]{1,80})\s*:\s*(.+?)\s*$", re.IGNORECASE)

def http_get_json(url: str, timeout: int = 30) -> Any:
    req = Request(url, headers={"User-Agent": "steam-req-crawler/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def sleep_jitter(base: float, jitter: float) -> None:
    time.sleep(base + random.random() * jitter)

def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

def connect_db(db_path: str) -> sqlite3.Connection:
    ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS apps (
            appid INTEGER PRIMARY KEY,
            name TEXT,
            last_modified INTEGER,
            price_change_number INTEGER,
            type TEXT,
            platforms_json TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS requirements (
            appid INTEGER NOT NULL,
            platform TEXT NOT NULL,              -- pc, mac, linux
            level TEXT NOT NULL,                 -- minimum, recommended

            os_text TEXT,
            cpu_text TEXT,
            gpu_text TEXT,
            notes_text TEXT,

            ram_gb REAL,
            vram_gb REAL,
            storage_gb REAL,

            dx_version REAL,
            opengl_version REAL,
            vulkan INTEGER,                      -- 1 if mentioned

            raw_html TEXT,
            parsed_json TEXT,
            updated_at TEXT,

            PRIMARY KEY (appid, platform, level),
            FOREIGN KEY (appid) REFERENCES apps(appid)
        );

        CREATE INDEX IF NOT EXISTS idx_apps_last_modified ON apps(last_modified);
        CREATE INDEX IF NOT EXISTS idx_req_platform_level ON requirements(platform, level);
        """
    )
    conn.commit()

def load_json_file(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f) or default

def atomic_write_json(path: str, obj: Any) -> None:
    ensure_parent_dir(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)

def fetch_applist_page(
    publisher_key: str,
    last_appid: int,
    include_games: bool,
    include_dlc: bool,
    max_results: int = 50000,
) -> Dict[str, Any]:
    payload = {
        "include_games": include_games,
        "include_dlc": include_dlc,
        "include_software": False,
        "include_videos": False,
        "include_hardware": False,
        "max_results": max_results,
        "last_appid": last_appid,
    }
    qs = urlencode(
        {
            "key": publisher_key,
            "input_json": json.dumps(payload, separators=(",", ":")),
        }
    )
    return http_get_json(f"{PARTNER_ISTORE_GETAPPLIST}?{qs}")

def fetch_appdetails_batch(appids: List[int], cc: str, lang: str) -> Dict[str, Any]:
    qs = urlencode(
        {
            "appids": ",".join(str(a) for a in appids),
            "cc": cc,
            "l": lang,
        }
    )
    return http_get_json(f"{STORE_API_APPDETAILS}?{qs}")

def strip_tags_to_lines(requirements_html: str) -> List[str]:
    if not requirements_html:
        return []
    s = requirements_html
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</li\s*>", "\n", s)
    s = re.sub(r"(?i)<strong>\s*([^<]+?)\s*</strong>", r"\1", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    s = htmllib.unescape(s)

    lines: List[str] = []
    for line in s.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines

def parse_requirements_fields(requirements_html: Optional[str]) -> Dict[str, Any]:
    if not requirements_html:
        return {"fields": {}, "notes": [], "raw_html": None}

    lines = strip_tags_to_lines(requirements_html)
    fields: Dict[str, str] = {}
    notes: List[str] = []

    for line in lines:
        m = LABEL_RE.match(line)
        if m:
            label = m.group(1).strip().lower()
            value = m.group(2).strip()
            fields[label] = value
        else:
            notes.append(line)

    return {"fields": fields, "notes": notes, "raw_html": requirements_html}

def normalize_labels(fields: Dict[str, str]) -> Dict[str, str]:
    out = dict(fields)

    if "hard drive" in out and "storage" not in out:
        out["storage"] = out["hard drive"]
    if "hdd" in out and "storage" not in out:
        out["storage"] = out["hdd"]

    if "cpu" in out and "processor" not in out:
        out["processor"] = out["cpu"]

    if "video card" in out and "graphics" not in out:
        out["graphics"] = out["video card"]
    if "video" in out and "graphics" not in out:
        out["graphics"] = out["video"]

    if "ram" in out and "memory" not in out:
        out["memory"] = out["ram"]

    return out

def parse_gb(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    t = text.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*gb", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*mb", t)
    if m:
        return float(m.group(1)) / 1024.0
    return None

def parse_vram_gb(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    t = text.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*gb\s*vram", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*gb.*(vram|video memory|video ram)", t)
    if m:
        return float(m.group(1))
    return None

def parse_dx_version(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    t = text.lower()
    m = re.search(r"directx\s*(?:version\s*)?(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1))
    return None

def parse_opengl_version(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    t = text.lower()
    m = re.search(r"opengl\s*(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1))
    return None

def fields_to_normalized_row(parsed: Dict[str, Any]) -> Dict[str, Any]:
    fields = normalize_labels(parsed.get("fields") or {})
    notes = parsed.get("notes") or []
    raw_html = parsed.get("raw_html")

    os_text = fields.get("os")
    cpu_text = fields.get("processor")
    gpu_text = fields.get("graphics")
    memory_text = fields.get("memory")
    storage_text = fields.get("storage")

    combined_for_api = " ".join([gpu_text or "", fields.get("directx") or "", " ".join(notes)]).strip()

    ram_gb = parse_gb(memory_text)
    vram_gb = parse_vram_gb(gpu_text)
    storage_gb = parse_gb(storage_text)

    dx_version = parse_dx_version(combined_for_api)
    opengl_version = parse_opengl_version(combined_for_api)
    vulkan = 1 if re.search(r"\bvulkan\b", combined_for_api.lower()) else 0

    extra_notes_parts: List[str] = []
    if "additional notes" in fields:
        extra_notes_parts.append(fields["additional notes"])
    extra_notes_parts.extend(notes)
    notes_text = "\n".join([p for p in extra_notes_parts if p]).strip() or None

    return {
        "os_text": os_text,
        "cpu_text": cpu_text,
        "gpu_text": gpu_text,
        "notes_text": notes_text,
        "ram_gb": ram_gb,
        "vram_gb": vram_gb,
        "storage_gb": storage_gb,
        "dx_version": dx_version,
        "opengl_version": opengl_version,
        "vulkan": vulkan,
        "raw_html": raw_html,
        "parsed_json": json.dumps(parsed, ensure_ascii=False),
    }

def upsert_apps_and_get_changed(conn: sqlite3.Connection, apps: List[Dict[str, Any]]) -> List[int]:
    changed: List[int] = []
    cur = conn.cursor()
    now = dt.datetime.utcnow().isoformat()

    for a in apps:
        appid = int(a.get("appid"))
        name = a.get("name")
        last_modified = int(a.get("last_modified") or 0)
        price_change_number = a.get("price_change_number")
        if price_change_number is not None:
            price_change_number = int(price_change_number)

        row = cur.execute("SELECT last_modified FROM apps WHERE appid=?", (appid,)).fetchone()

        if row is None:
            cur.execute(
                """
                INSERT INTO apps(appid, name, last_modified, price_change_number, updated_at)
                VALUES(?,?,?,?,?)
                """,
                (appid, name, last_modified, price_change_number, now),
            )
            changed.append(appid)
        else:
            old_last_modified = int(row[0] or 0)
            if last_modified and last_modified != old_last_modified:
                cur.execute(
                    """
                    UPDATE apps
                    SET name=?, last_modified=?, price_change_number=?, updated_at=?
                    WHERE appid=?
                    """,
                    (name, last_modified, price_change_number, now, appid),
                )
                changed.append(appid)

    conn.commit()
    return changed

def upsert_requirements_row(conn: sqlite3.Connection, appid: int, platform: str, level: str, raw_html: Optional[str]) -> None:
    parsed = parse_requirements_fields(raw_html)
    norm = fields_to_normalized_row(parsed)
    now = dt.datetime.utcnow().isoformat()

    conn.execute(
        """
        INSERT INTO requirements(
            appid, platform, level,
            os_text, cpu_text, gpu_text, notes_text,
            ram_gb, vram_gb, storage_gb,
            dx_version, opengl_version, vulkan,
            raw_html, parsed_json, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(appid, platform, level) DO UPDATE SET
            os_text=excluded.os_text,
            cpu_text=excluded.cpu_text,
            gpu_text=excluded.gpu_text,
            notes_text=excluded.notes_text,
            ram_gb=excluded.ram_gb,
            vram_gb=excluded.vram_gb,
            storage_gb=excluded.storage_gb,
            dx_version=excluded.dx_version,
            opengl_version=excluded.opengl_version,
            vulkan=excluded.vulkan,
            raw_html=excluded.raw_html,
            parsed_json=excluded.parsed_json,
            updated_at=excluded.updated_at
        """,
        (
            appid, platform, level,
            norm["os_text"], norm["cpu_text"], norm["gpu_text"], norm["notes_text"],
            norm["ram_gb"], norm["vram_gb"], norm["storage_gb"],
            norm["dx_version"], norm["opengl_version"], norm["vulkan"],
            norm["raw_html"], norm["parsed_json"], now,
        ),
    )

def update_details_for_appids(
    conn: sqlite3.Connection,
    appids: List[int],
    cc: str,
    lang: str,
    batch_size: int,
    sleep_base: float,
    sleep_jitter_val: float,
) -> None:
    def chunks(seq: List[int], n: int):
        for i in range(0, len(seq), n):
            yield seq[i:i+n]

    cur = conn.cursor()

    for batch in chunks(appids, batch_size):
        try:
            data = fetch_appdetails_batch(batch, cc=cc, lang=lang)
        except HTTPError as e:
            if e.code == 429:
                time.sleep(60)
                continue
            time.sleep(20)
            continue
        except (URLError, TimeoutError):
            time.sleep(15)
            continue

        now = dt.datetime.utcnow().isoformat()

        for appid in batch:
            entry = data.get(str(appid), {})
            if not entry.get("success"):
                continue

            d = entry.get("data") or {}
            app_type = d.get("type")
            platforms = d.get("platforms")

            cur.execute(
                """
                UPDATE apps
                SET name=?, type=?, platforms_json=?, updated_at=?
                WHERE appid=?
                """,
                (
                    d.get("name"),
                    app_type,
                    json.dumps(platforms, ensure_ascii=False) if platforms is not None else None,
                    now,
                    appid,
                ),
            )

            pc = d.get("pc_requirements") or {}
            mac = d.get("mac_requirements") or {}
            linux = d.get("linux_requirements") or {}

            upsert_requirements_row(conn, appid, "pc", "minimum", pc.get("minimum"))
            upsert_requirements_row(conn, appid, "pc", "recommended", pc.get("recommended"))

            upsert_requirements_row(conn, appid, "mac", "minimum", mac.get("minimum"))
            upsert_requirements_row(conn, appid, "mac", "recommended", mac.get("recommended"))

            upsert_requirements_row(conn, appid, "linux", "minimum", linux.get("minimum"))
            upsert_requirements_row(conn, appid, "linux", "recommended", linux.get("recommended"))

        conn.commit()
        sleep_jitter(sleep_base, sleep_jitter_val)

def run_incremental_crawl(
    conn: sqlite3.Connection,
    publisher_key: str,
    checkpoint_path: str,
    include_games: bool,
    include_dlc: bool,
    cc: str,
    lang: str,
    details_batch_size: int,
    sleep_base: float,
    sleep_jitter_val: float,
    max_pages: Optional[int],
) -> Dict[str, Any]:
    checkpoint = load_json_file(checkpoint_path, {"last_appid": 0})
    last_appid = int(checkpoint.get("last_appid", 0))

    page_count = 0
    total_indexed = 0
    total_changed = 0

    while True:
        if max_pages is not None and page_count >= max_pages:
            break

        try:
            page = fetch_applist_page(
                publisher_key=publisher_key,
                last_appid=last_appid,
                include_games=include_games,
                include_dlc=include_dlc,
                max_results=50000,
            )
        except Exception:
            time.sleep(30)
            continue

        apps = (page.get("response") or {}).get("apps") or []
        if not apps:
            break

        page_count += 1
        total_indexed += len(apps)

        changed = upsert_apps_and_get_changed(conn, apps)
        total_changed += len(changed)

        if changed:
            update_details_for_appids(
                conn=conn,
                appids=changed,
                cc=cc,
                lang=lang,
                batch_size=details_batch_size,
                sleep_base=sleep_base,
                sleep_jitter_val=sleep_jitter_val,
            )

        last_appid = int(apps[-1].get("appid") or last_appid)
        atomic_write_json(checkpoint_path, {"last_appid": last_appid, "updated_at": dt.datetime.utcnow().isoformat()})

        print(f"Pages {page_count} | Indexed {total_indexed} | New or changed {total_changed} | Next last_appid {last_appid}")
        sleep_jitter(sleep_base, sleep_jitter_val)

    return {
        "pages": page_count,
        "indexed": total_indexed,
        "changed": total_changed,
        "checkpoint_last_appid": last_appid,
        "finished_utc": dt.datetime.utcnow().isoformat() + "Z",
    }

def git_commit_and_push(repo_dir: str, rel_paths: List[str], message: str) -> None:
    repo = Path(repo_dir).resolve()

    def run(cmd: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=str(repo), check=True, capture_output=True, text=True)

    run(["git", "rev-parse", "--is-inside-work-tree"])

    for p in rel_paths:
        subprocess.run(["git", "add", p], cwd=str(repo), check=True)

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    if not status.stdout.strip():
        print("Git: no changes to commit")
        return

    subprocess.run(["git", "commit", "-m", message], cwd=str(repo), check=True)
    subprocess.run(["git", "push"], cwd=str(repo), check=True)
    print("Git: pushed")

def main() -> None:
    ap = argparse.ArgumentParser()

    ap.add_argument("--repo-dir", default=".", help="Path to the git repo root")
    ap.add_argument("--db", default="data/steam_requirements.sqlite", help="SQLite DB path inside repo")
    ap.add_argument("--checkpoint", default="data/applist_checkpoint.json", help="Checkpoint path inside repo")
    ap.add_argument("--state", default="data/last_run.json", help="Run state file inside repo")

    ap.add_argument("--include-games", action="store_true", default=True)
    ap.add_argument("--include-dlc", action="store_true", default=True)

    ap.add_argument("--cc", default="us")
    ap.add_argument("--lang", default="en")

    ap.add_argument("--details-batch-size", type=int, default=50)
    ap.add_argument("--sleep-base", type=float, default=0.4)
    ap.add_argument("--sleep-jitter", type=float, default=0.2)

    ap.add_argument("--max-pages", type=int, default=None, help="For testing only")

    ap.add_argument("--crawl-and-push", action="store_true", help="Run crawl, update state, git commit and push")
    ap.add_argument("--commit-message", default=None)

    args = ap.parse_args()

    publisher_key = os.environ.get("STEAM_PUBLISHER_KEY")
    if not publisher_key:
        raise SystemExit("Missing STEAM_PUBLISHER_KEY environment variable")

    repo_dir = str(Path(args.repo_dir).resolve())
    db_path = str(Path(repo_dir) / args.db)
    checkpoint_path = str(Path(repo_dir) / args.checkpoint)
    state_path = str(Path(repo_dir) / args.state)

    conn = connect_db(db_path)
    init_db(conn)

    if args.crawl_and_push:
        started = dt.datetime.utcnow().isoformat() + "Z"
        print(f"Run started {started}")

        result = run_incremental_crawl(
            conn=conn,
            publisher_key=publisher_key,
            checkpoint_path=checkpoint_path,
            include_games=args.include_games,
            include_dlc=args.include_dlc,
            cc=args.cc,
            lang=args.lang,
            details_batch_size=args.details_batch_size,
            sleep_base=args.sleep_base,
            sleep_jitter_val=args.sleep_jitter,
            max_pages=args.max_pages,
        )

        state_obj = {
            "started_utc": started,
            "finished_utc": result["finished_utc"],
            "pages": result["pages"],
            "indexed": result["indexed"],
            "changed": result["changed"],
            "checkpoint_last_appid": result["checkpoint_last_appid"],
        }
        atomic_write_json(state_path, state_obj)

        msg = args.commit_message or f"Update Steam requirements DB {dt.date.today().isoformat()}"
        rel_db = os.path.relpath(db_path, repo_dir)
        rel_cp = os.path.relpath(checkpoint_path, repo_dir)
        rel_state = os.path.relpath(state_path, repo_dir)

        git_commit_and_push(repo_dir=repo_dir, rel_paths=[rel_db, rel_cp, rel_state], message=msg)

    conn.close()

if __name__ == "__main__":
    main()
