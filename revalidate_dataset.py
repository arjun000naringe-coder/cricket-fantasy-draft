#!/usr/bin/env python3
"""
Full dataset re-validation pass (ESPN API restored).

For every player:
  - Ensure an espn_id (look up by name if missing).
  - Re-fetch fresh profile (metadata + all-format stats) via the working API.
  - Refresh metadata fields (country, bat_hand, bowl_style, role).
  - Merge in any genuinely-missing formats (e.g. an ODI record that an
    earlier scrape missed). Real gaps (player never played a format) are left
    alone — statsguru simply returns no row for them.
  - Clear partial_metadata when the API path succeeds (_from_api == True).

Safety:
  - Never wipes an existing record on a failed re-scrape — keeps what we have.
  - Never renames an existing player (keeps dedup/frontend stable).
  - Flags (does NOT auto-merge) any duplicate espn_id revealed by backfill.
"""

import re
import time
from datetime import datetime
from difflib import SequenceMatcher

from scraper import (
    load_players, save_players, search_player_espn,
    fetch_player_profile_espn,
)


def _norm_tokens(s):
    return [t for t in re.sub(r"[^a-z ]", " ", (s or "").lower()).split() if t]


def names_match(stored, fetched):
    """Guard against wrong espn_ids: does the fetched player look like the
    stored player? Some stored IDs point at the wrong person; without this
    gate we'd overwrite a correct record with a different player's stats.

    Rule: surname must match, AND first names must be compatible — either
    equal or sharing a first initial (so 'SR Tendulkar' ~ 'Sachin Tendulkar'
    and 'AB de Villiers' ~ 'Abraham de Villiers' pass, but 'Rohit Sharma' vs
    'Ishant Sharma' is rejected). Falls back to near-identical full strings.
    """
    a, b = _norm_tokens(stored), _norm_tokens(fetched)
    if not a or not b:
        return False
    if a[-1] == b[-1]:                       # surname matches
        fa, fb = a[0], b[0]
        if fa == fb or fa[0] == fb[0]:       # first name equal or shared initial
            return True
    # Fallback: near-identical full strings (handles token reordering/hyphens)
    if SequenceMatcher(None, "".join(a), "".join(b)).ratio() > 0.85:
        return True
    return False

LOG_FILE = "revalidate.log"
DELAY = 1.5            # seconds between players (be kind to ESPN)
RETRY_BACKOFF = [3, 8, 15]  # ESPN intermittently 503s; retry transient failures
FORMATS = ("Test", "ODI", "T20I")


def fetch_with_retry(espn_id, label):
    """Re-fetch a profile, retrying transient failures (ESPN 503s).

    Every player here already exists in the DB with data, so a None result
    means a transient fetch failure, never 'no such player' — safe to retry.
    """
    for attempt, wait in enumerate([0] + RETRY_BACKOFF):
        if wait:
            time.sleep(wait)
        try:
            profile = fetch_player_profile_espn(espn_id)
        except Exception as e:
            profile = None
            if attempt == len(RETRY_BACKOFF):
                log(f"      {label}: error after retries: {e}")
        if profile:
            if attempt:
                log(f"      {label}: recovered on retry {attempt}")
            return profile
    return None


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def stats_present(fmt_stats):
    """A format record counts as 'real' if the player has any matches."""
    return bool(fmt_stats) and int(fmt_stats.get("matches", 0) or 0) > 0


def main():
    players = load_players()
    total = len(players)
    log(f"=== REVALIDATE START === {total} players")

    ids_backfilled = 0
    metadata_fixed = 0
    formats_added = 0
    partial_cleared = 0
    scrape_failed = []
    id_lookup_failed = []
    name_drift = []          # API name differs slightly (informational)
    bad_ids = []             # stored espn_id points at a different player
    dup_ids = {}             # espn_id -> [names]  (collision detection)

    # Build running map of espn_id -> name to catch collisions as we backfill
    id_to_name = {}
    for p in players:
        if p.get("espn_id"):
            id_to_name.setdefault(p["espn_id"], []).append(p["name"])

    for i, p in enumerate(players, 1):
        name = p["name"]
        espn_id = p.get("espn_id")
        is_backfill = not espn_id

        # 1. Backfill missing espn_id via name search (not committed until verified)
        if is_backfill:
            try:
                pid, full_name, _ = search_player_espn(name)
            except Exception as e:
                log(f"  [{i}/{total}] {name}: ID search error: {e}")
                id_lookup_failed.append(name)
                time.sleep(DELAY)
                continue
            if not pid:
                log(f"  [{i}/{total}] {name}: no ESPN match (still no ID)")
                id_lookup_failed.append(name)
                time.sleep(DELAY)
                continue
            espn_id = pid

        # 2. Re-fetch fresh profile (all formats + metadata), with retries
        profile = fetch_with_retry(espn_id, f"[{i}/{total}] {name}")
        if not profile:
            log(f"  [{i}/{total}] {name}: fetch failed after retries (kept existing)")
            scrape_failed.append(name)
            time.sleep(DELAY)
            continue

        from_api = profile.pop("_from_api", False)
        fetched_name = profile.get("name", "")

        # 2b. HARD GATE: does the fetched player match the stored player?
        # Protects against wrong espn_ids overwriting a correct record.
        if not names_match(name, fetched_name):
            log(f"  [{i}/{total}] {name}: ID {espn_id} -> '{fetched_name}' "
                f"({profile.get('country')}) — NAME MISMATCH, record untouched")
            bad_ids.append((name, espn_id, fetched_name, profile.get("country")))
            time.sleep(DELAY)
            continue

        # Verified — now safe to commit a backfilled ID
        if is_backfill:
            p["espn_id"] = espn_id
            ids_backfilled += 1
            log(f"  [{i}/{total}] {name}: backfilled espn_id={espn_id} (verified)")
        id_to_name.setdefault(espn_id, []).append(name)
        if len(id_to_name.get(espn_id, [])) > 1:
            dup_ids[espn_id] = id_to_name[espn_id]

        changed = is_backfill

        # Informational: note minor name drift but DO NOT rename
        if fetched_name and fetched_name != name:
            name_drift.append((name, fetched_name))

        # 3. Refresh metadata (only overwrite with real values)
        for field in ("country", "bat_hand", "role", "bowl_style"):
            new_val = profile.get(field)
            if new_val and new_val != "Unknown" and p.get(field) != new_val:
                p[field] = new_val
                changed = True
        if changed:
            metadata_fixed += 1

        # 4. Merge in real formats that we were missing
        existing_fmts = p.setdefault("formats", {})
        for fmt in FORMATS:
            new_stats = profile.get("formats", {}).get(fmt)
            if stats_present(new_stats):
                if fmt not in existing_fmts:
                    existing_fmts[fmt] = new_stats
                    formats_added += 1
                    changed = True
                    log(f"  [{i}/{total}] {name}: +{fmt} (was missing)")
                else:
                    # Refresh existing format stats with fresh numbers
                    existing_fmts[fmt] = new_stats

        # 5. Clear partial flag when API path succeeded
        if from_api and p.get("partial_metadata"):
            del p["partial_metadata"]
            partial_cleared += 1
            changed = True

        if i % 25 == 0:
            save_players(players)
            log(f"  --- progress {i}/{total} (saved) ---")

        time.sleep(DELAY)

    save_players(players)

    # ---- Final report ----
    log("\n" + "=" * 55)
    log("=== REVALIDATE COMPLETE ===")
    log(f"  Players processed:    {total}")
    log(f"  espn_ids backfilled:  {ids_backfilled}")
    log(f"  metadata refreshed:   {metadata_fixed}")
    log(f"  missing formats added:{formats_added}")
    log(f"  partial flags cleared:{partial_cleared}")
    log(f"  ID lookup failed:     {len(id_lookup_failed)}")
    log(f"  scrape failed:        {len(scrape_failed)}")
    log(f"  WRONG ids (mismatch): {len(bad_ids)}")

    if bad_ids:
        log(f"\n  -- WRONG espn_ids: point to a different player ({len(bad_ids)}) --")
        log(f"     (record left untouched; needs manual ID fix)")
        for stored, pid, fetched, country in bad_ids:
            log(f"     '{stored}' -> id {pid} = '{fetched}' ({country})")
    if id_lookup_failed:
        log(f"\n  -- No ESPN ID found ({len(id_lookup_failed)}): --")
        for n in id_lookup_failed:
            log(f"     {n}")
    if scrape_failed:
        log(f"\n  -- Scrape failed, kept existing ({len(scrape_failed)}): --")
        for n in scrape_failed:
            log(f"     {n}")
    if dup_ids:
        log(f"\n  -- DUPLICATE espn_ids (needs manual review) ({len(dup_ids)}): --")
        for pid, names in dup_ids.items():
            log(f"     {pid}: {names}")
    if name_drift:
        log(f"\n  -- Name drift (API name != stored, NOT renamed) ({len(name_drift)}): --")
        for stored, api in name_drift[:40]:
            log(f"     '{stored}' vs API '{api}'")


if __name__ == "__main__":
    main()
