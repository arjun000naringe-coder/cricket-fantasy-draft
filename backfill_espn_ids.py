#!/usr/bin/env python3
"""
One-time backfill: add espn_id and partial_metadata flags to existing players.
For players with Unknown metadata, marks them partial.
For all players, looks up their ESPN ID from the HTML search.
"""

import time
import sys
from scraper import (
    load_players, save_players, _search_espn_html,
    _pick_best_candidate, _clean_search_name,
)


def backfill():
    players = load_players()
    total = len(players)
    updated = 0
    partial_flagged = 0

    for i, p in enumerate(players, 1):
        changed = False

        # Flag partial metadata
        if p.get("country") == "Unknown" or p.get("bat_hand") == "Unknown":
            if not p.get("partial_metadata"):
                p["partial_metadata"] = True
                partial_flagged += 1
                changed = True

        # Backfill ESPN ID
        if not p.get("espn_id"):
            name = _clean_search_name(p["name"])
            candidates = _search_espn_html(name)
            if candidates:
                pid, _ = _pick_best_candidate(candidates, name)
                if pid:
                    p["espn_id"] = pid
                    changed = True
                    print(f"  [{i}/{total}] {p['name']} -> espn_id={pid}")
            time.sleep(1)

        if changed:
            updated += 1

        if i % 50 == 0:
            save_players(players)
            print(f"  Progress: {i}/{total}, updated={updated}")

    save_players(players)
    print(f"\nDone: {updated} players updated, {partial_flagged} flagged partial")


if __name__ == "__main__":
    backfill()
