#!/usr/bin/env python3
"""
Player database harvester.
Asks Cricket Geek persona for players matching diverse constraints,
then looks each up on ESPN and adds to players.json with full validation.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher

from llm_client import chat
from scraper import load_players, save_players, scrape_and_cache

HARVEST_MODEL = "gemma4:31b"
LOG_FILE = "harvest.log"
ESPN_DELAY = 2  # seconds between ESPN scrapes
LLM_TIMEOUT = 30

CONSTRAINTS = [
    # Batting style / handed
    "Left-handed batsmen",
    "Right-handed batsmen who bowl spin",
    "Left-arm fast bowlers",
    "Right-arm off-spin bowlers",
    "Left-arm orthodox spin bowlers",
    "Leg-spin bowlers",
    "Wicketkeeper-batsmen",

    # Country-specific
    "Players from Bangladesh",
    "Players from Zimbabwe",
    "Players from Afghanistan",
    "Players from Sri Lanka",
    "Players from West Indies",
    "Players from Ireland",
    "Players from Netherlands",
    "Players from Scotland",
    "Players from associate nations (Netherlands, Ireland, Scotland, Zimbabwe, Afghanistan, Nepal, UAE, Oman, Namibia, PNG)",

    # Era-based
    "Players who debuted after 2015",
    "Players who debuted after 2020",
    "Players who debuted between 2005 and 2015",
    "Players active in the 1990s",
    "Players active in the 1980s",

    # Stat-based
    "All-rounders with 2000+ runs and 100+ wickets in their career",
    "Fast bowlers with 150+ wickets",
    "Batsmen with career average above 45",
    "Batsmen with career average between 30 and 40",
    "Bowlers with career economy rate below 3.0",
    "Bowlers with career average below 25",
    "Players with 50+ catches (not wicketkeeper)",

    # Role-based
    "Opening batsmen",
    "Middle-order batsmen (bat at 4, 5, or 6)",
    "Death bowlers and yorker specialists",
    "Genuine pace bowlers (140+ kph)",
    "Part-time bowlers who are primarily batsmen",

    # Venue / conditions
    "Players who have played at Lord's",
    "Players who have played in Australia",
    "Players who have played in subcontinental conditions",
    "Players known for performing in English conditions",

    # Niche / torso
    "Underrated players who never became household names",
    "Players who played fewer than 30 international matches",
    "Journeyman players from the 2010s",
    "Players from the 2023 or 2024 World Cups",
    "Current players who are under 25 years old",
]

FORMATS = ["Test", "ODI", "T20I"]

GEEK_SYSTEM = (
    "You are an obsessive cricket statistician with encyclopedic knowledge spanning "
    "every era, every nation, and every format. You know the deep cuts — not just the "
    "stars but the workhorse seamers, the journeyman spinners, the one-cap wonders."
)

GEEK_PROMPT = (
    "Give me exactly 11 cricketers for a {format} fantasy team who match this constraint:\n"
    "\"{constraint}\"\n\n"
    "Rules:\n"
    "- All 11 must be real cricketers who have played {format} matches\n"
    "- Use full formal names (e.g. 'Kumar Sangakkara' not 'Sanga')\n"
    "- Mix eras and countries — do NOT cluster from one team\n"
    "- Include 3-4 non-obvious picks alongside the well-known ones\n"
    "- Balance the team: openers, middle order, all-rounders, bowlers, keeper\n"
    "- Players already in this list should be EXCLUDED: {exclude}\n\n"
    "Respond with EXACTLY 11 names, one per line, numbered 1-11. Nothing else — "
    "no stats, no reasoning, no commentary, no extra text."
)


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_player_names(constraint, fmt, exclude_names):
    exclude_str = ", ".join(exclude_names[:50]) if exclude_names else "none"
    prompt = GEEK_PROMPT.format(
        format=fmt,
        constraint=constraint,
        exclude=exclude_str,
    )
    try:
        resp = chat(
            messages=[{"role": "user", "content": prompt}],
            system=GEEK_SYSTEM,
            max_tokens=400,
            model=HARVEST_MODEL,
        )
    except Exception as e:
        log(f"  LLM error: {e}")
        return []

    names = []
    for line in resp.strip().splitlines():
        line = line.strip()
        cleaned = re.sub(r'^[\d]+[.\)\-:\s]+', '', line).strip()
        cleaned = re.sub(r'\s*[\(\[].*$', '', cleaned).strip()
        cleaned = cleaned.strip('"\'').strip()
        if cleaned and 2 < len(cleaned) < 50 and not any(w in cleaned.lower() for w in ["constraint", "team", "format", "note", "player"]):
            names.append(cleaned)
    return names[:11]


def validate_player_stats(player_data, fmt):
    if not player_data:
        return False, "no data"
    formats = player_data.get("formats", {})
    if fmt not in formats:
        return False, f"no {fmt} stats"
    stats = formats[fmt]
    matches = stats.get("matches", 0)
    if not matches or int(matches) == 0:
        return False, f"0 {fmt} matches"
    runs = stats.get("runs", 0)
    wickets = stats.get("wickets", 0)
    if (not runs or int(runs) == 0) and (not wickets or int(wickets) == 0):
        return False, "no runs or wickets"
    return True, "ok"


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


def harvest():
    db = load_players()
    existing_names = set(p["name"].lower() for p in db)
    initial_count = len(db)

    added = 0
    skipped_existing = 0
    skipped_not_found = 0
    skipped_bad_stats = 0
    skipped_name_mismatch = 0
    espn_errors = 0

    total_combos = len(CONSTRAINTS) * len(FORMATS)
    log(f"=== HARVEST START === {initial_count} players in DB, {total_combos} constraint/format combos")

    for ci, constraint in enumerate(CONSTRAINTS, 1):
        for fi, fmt in enumerate(FORMATS, 1):
            combo_num = (ci - 1) * len(FORMATS) + fi
            log(f"\n[{combo_num}/{total_combos}] {fmt}: \"{constraint}\"")

            db = load_players()
            existing_names = set(p["name"].lower() for p in db)

            names = get_player_names(constraint, fmt, list(existing_names)[:50])
            if not names:
                log("  No names returned from LLM")
                continue

            log(f"  Got {len(names)} names: {', '.join(names)}")

            for name in names:
                if name.lower() in existing_names:
                    skipped_existing += 1
                    continue

                time.sleep(ESPN_DELAY)

                try:
                    player_data = scrape_and_cache(name, fmt)
                except Exception as e:
                    log(f"  ESPN error for {name}: {e}")
                    espn_errors += 1
                    continue

                if not player_data:
                    log(f"  ✗ {name}: not found on ESPN")
                    skipped_not_found += 1
                    continue

                if not name_matches(name, player_data["name"]):
                    log(f"  ✗ {name}: ESPN returned '{player_data['name']}' (name mismatch)")
                    skipped_name_mismatch += 1
                    continue

                valid, reason = validate_player_stats(player_data, fmt)
                if not valid:
                    log(f"  ✗ {player_data['name']}: {reason}")
                    skipped_bad_stats += 1
                    continue

                log(f"  ✓ {player_data['name']} ({player_data.get('country', '?')}, {player_data.get('role', '?')})")
                existing_names.add(player_data["name"].lower())
                added += 1

            db = load_players()
            existing_names = set(p["name"].lower() for p in db)

    final_count = len(load_players())
    log(f"\n{'='*60}")
    log(f"=== HARVEST COMPLETE ===")
    log(f"  Started with:      {initial_count} players")
    log(f"  Ended with:        {final_count} players")
    log(f"  New players added: {added}")
    log(f"  Skipped (exists):  {skipped_existing}")
    log(f"  Skipped (no ESPN): {skipped_not_found}")
    log(f"  Skipped (bad stats): {skipped_bad_stats}")
    log(f"  Skipped (name mismatch): {skipped_name_mismatch}")
    log(f"  ESPN errors:       {espn_errors}")


if __name__ == "__main__":
    harvest()
