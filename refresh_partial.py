#!/usr/bin/env python3
"""
Daily job: refresh players with partial_metadata flag.
Attempts to fetch full metadata from ESPN API for any player marked partial.
Clears the flag once all metadata fields are complete.
Also backfills ESPN IDs for players that don't have one yet.
"""

import time
import sys
from datetime import datetime
from scraper import (
    load_players, save_players,
    _fetch_player_metadata_espn, _search_espn_html,
    _pick_best_candidate, _clean_search_name,
    HEADERS,
)
import requests

LOG_FILE = "refresh_partial.log"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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


def refresh_partial_players():
    players = load_players()
    partial = [p for p in players if p.get("partial_metadata")]
    if not partial:
        log("No partial players to refresh.")
        return 0

    log(f"Refreshing {len(partial)} partial players...")
    fixed = 0

    for p in partial:
        espn_id = p.get("espn_id")
        if not espn_id:
            log(f"  {p['name']}: no ESPN ID, skipping")
            continue

        meta = _fetch_player_metadata_espn(espn_id)
        if not meta or not meta.get("_from_api"):
            log(f"  {p['name']}: API still failing")
            continue

        changed = False
        for field in ("country", "bat_hand"):
            if meta.get(field) and meta[field] != "Unknown":
                if p.get(field) != meta[field]:
                    p[field] = meta[field]
                    changed = True
        if meta.get("bowl_style") not in ("Unknown", None, "N/A"):
            if p.get("bowl_style") != meta["bowl_style"]:
                p["bowl_style"] = meta["bowl_style"]
                changed = True
        if meta.get("name") and meta["name"] != p["name"]:
            log(f"  {p['name']}: API name is '{meta['name']}', keeping existing")

        # API succeeded — data is now trustworthy, clear the flag
        if p.get("partial_metadata"):
            del p["partial_metadata"]
            changed = True

        if changed:
            fixed += 1
            log(f"  ✓ {p['name']}: country={p['country']}, bat={p['bat_hand']}, bowl={p['bowl_style']}")
        else:
            log(f"  - {p['name']}: no change")

        time.sleep(1)

    save_players(players)
    return fixed


def backfill_missing_ids():
    players = load_players()
    missing = [p for p in players if not p.get("espn_id")]
    if not missing:
        log("All players have ESPN IDs.")
        return 0

    log(f"Backfilling ESPN IDs for {len(missing)} players...")
    found = 0

    for i, p in enumerate(missing, 1):
        name = _clean_search_name(p["name"])
        candidates = _search_espn_html(name)
        if candidates:
            pid, _ = _pick_best_candidate(candidates, name)
            if pid:
                p["espn_id"] = pid
                found += 1
        time.sleep(1)

        if i % 50 == 0:
            save_players(players)
            log(f"  Progress: {i}/{len(missing)}, found={found}")

    save_players(players)
    return found


def main():
    log("=== DAILY REFRESH START ===")

    if not is_api_up():
        log("ESPN API is down. Skipping partial metadata refresh, will still try ID backfill.")
    else:
        log("ESPN API is up.")
        fixed = refresh_partial_players()
        log(f"Fixed {fixed} partial players.")

    found = backfill_missing_ids()
    log(f"Backfilled {found} ESPN IDs.")

    players = load_players()
    partial = sum(1 for p in players if p.get("partial_metadata"))
    no_id = sum(1 for p in players if not p.get("espn_id"))
    log(f"=== DONE === {len(players)} total, {partial} still partial, {no_id} still missing ESPN ID")


if __name__ == "__main__":
    main()
