#!/usr/bin/env python3
"""
Retry ESPN lookups for players missed during harvest.
Checks if the ESPN API is back, then processes the missed list.
"""

import os
import re
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher

import requests

from scraper import (
    load_players, scrape_and_cache, search_player_espn,
    _fetch_player_metadata_espn, HEADERS,
)

RETRY_LIST = os.path.join(os.path.dirname(__file__), "harvest_retry_names.txt")
LOG_FILE = os.path.join(os.path.dirname(__file__), "harvest_retry.log")
ESPN_DELAY = 2
CHECK_INTERVAL = 900  # 15 minutes
FORMATS = ["Test", "ODI", "T20I"]


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def is_api_up():
    url = "https://site.web.api.espn.com/apis/common/v3/sports/cricket/cricinfo/athletes/253802"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def name_matches(requested, returned):
    req = requested.lower().strip()
    ret = returned.lower().strip()
    if req == ret:
        return True
    overall = SequenceMatcher(None, req, ret).ratio()
    req_words = req.split()
    ret_words = ret.split()
    words_found = sum(
        1 for w in req_words
        if any(SequenceMatcher(None, w, rw).ratio() > 0.7 for rw in ret_words)
    )
    return overall > 0.35 and words_found >= 1


def validate_stats(player_data, fmt):
    if not player_data:
        return False
    formats = player_data.get("formats", {})
    if fmt not in formats:
        return False
    stats = formats[fmt]
    matches = stats.get("matches", 0)
    if not matches or int(matches) == 0:
        return False
    return True


def run_retries():
    if not os.path.exists(RETRY_LIST):
        log(f"No retry list at {RETRY_LIST}")
        return

    names = [n.strip() for n in open(RETRY_LIST).readlines() if n.strip()]
    db = load_players()
    existing = set(p["name"].lower() for p in db)

    added = 0
    skipped = 0
    not_found = 0

    log(f"=== RETRY START === {len(names)} names to process, {len(db)} in DB")

    for i, name in enumerate(names, 1):
        if name.lower() in existing:
            skipped += 1
            continue

        for fmt in FORMATS:
            time.sleep(ESPN_DELAY)
            try:
                player_data = scrape_and_cache(name, fmt)
            except Exception as e:
                log(f"  Error for {name}/{fmt}: {e}")
                continue

            if player_data:
                if not name_matches(name, player_data["name"]):
                    continue
                if not validate_stats(player_data, fmt):
                    continue
                log(f"  ✓ [{i}/{len(names)}] {player_data['name']} ({player_data.get('country','?')}, {fmt})")
                existing.add(player_data["name"].lower())
                added += 1
                break
        else:
            not_found += 1

        if i % 50 == 0:
            db = load_players()
            log(f"  Progress: {i}/{len(names)}, added={added}, DB={len(db)}")

    final = len(load_players())
    log(f"=== RETRY COMPLETE === added={added}, skipped={skipped}, not_found={not_found}, DB={final}")


def main():
    log("Waiting for ESPN API to come back up...")
    while True:
        if is_api_up():
            log("ESPN API is UP! Starting retries.")
            run_retries()
            return
        else:
            log(f"ESPN API still down. Checking again in {CHECK_INTERVAL // 60} minutes.")
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
