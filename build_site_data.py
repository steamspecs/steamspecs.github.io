#!/usr/bin/env python3
import json
import os
import sqlite3
from pathlib import Path

DB_PATH = "data/steam_requirements.sqlite"
OUT_DIR = Path("site/data")
SHARDS_DIR = OUT_DIR / "shards"

# How many apps per shard file
SHARD_SIZE = 2000

def ensure_dirs():
    SHARDS_DIR.mkdir(parents=True, exist_ok=True)

def connect_db():
    return sqlite3.connect(DB_PATH)

def row_to_req(row):
    # requirements table columns in our schema
    return {
        "os": row["os_text"],
        "cpu": row["cpu_text"],
        "gpu": row["gpu_text"],
        "ram_gb": row["ram_gb"],
        "vram_gb": row["vram_gb"],
        "storage_gb": row["storage_gb"],
        "directx": row["dx_version"],
        "opengl": row["opengl_version"],
        "vulkan": bool(row["vulkan"]) if row["vulkan"] is not None else False,
        "notes": row["notes_text"],
        "raw_html": row["raw_html"],
    }

def main():
    ensure_dirs()
    if not os.path.exists(DB_PATH):
        raise SystemExit(f"DB not found at {DB_PATH}")

    conn = connect_db()
    conn.row_factory = sqlite3.Row

    # Build a compact index of all apps
    apps = conn.execute(
        """
        SELECT appid, name, type, platforms_json, last_modified, updated_at
        FROM apps
        ORDER BY appid
        """
    ).fetchall()

    # Preload requirements in a dict keyed by appid for fast assembly
    req_rows = conn.execute(
        """
        SELECT *
        FROM requirements
        ORDER BY appid
        """
    ).fetchall()

    req_by_appid = {}
    for r in req_rows:
        appid = int(r["appid"])
        req_by_appid.setdefault(appid, {}).setdefault(r["platform"], {})[r["level"]] = row_to_req(r)

    index = []
    shard = []
    shard_id = 0
    count = 0

    for a in apps:
        appid = int(a["appid"])
        name = a["name"]
        app_type = a["type"]
        has_reqs = appid in req_by_appid

        index.append({
            "appid": appid,
            "name": name,
            "type": app_type,
            "has_requirements": has_reqs
        })

        shard.append({
            "appid": appid,
            "name": name,
            "type": app_type,
            "requirements": req_by_appid.get(appid)  # pc/mac/linux with minimum/recommended
        })

        count += 1
        if len(shard) >= SHARD_SIZE:
            out_path = SHARDS_DIR / f"shard_{shard_id:05d}.json"
            out_path.write_text(json.dumps(shard, ensure_ascii=False), encoding="utf-8")
            shard_id += 1
            shard = []

    if shard:
        out_path = SHARDS_DIR / f"shard_{shard_id:05d}.json"
        out_path.write_text(json.dumps(shard, ensure_ascii=False), encoding="utf-8")

    (OUT_DIR / "index.json").write_text(json.dumps({
        "version": 1,
        "shard_size": SHARD_SIZE,
        "total_apps": len(index),
        "total_shards": shard_id + (1 if shard else 0),
        "apps": index
    }, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote index.json with {len(index)} apps")
    print(f"Wrote {shard_id + (1 if shard else 0)} shard files to {SHARDS_DIR}")

if __name__ == "__main__":
    main()