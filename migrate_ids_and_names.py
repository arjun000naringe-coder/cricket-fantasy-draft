#!/usr/bin/env python3
"""
One-time migration after dedup:
  1. Backfill espn_id for every record missing one (ESPN HTML search by name).
  2. Rename every record to ESPN's `shortName` (the clean common form,
     e.g. 'Isaac Vivian Alexander Richards' -> 'Viv Richards').

Two phases so the slow network pass runs once:
  - default (compute): reads players.json, fetches ids + shortNames, writes a
    plan to migration_plan.json, prints a dry-run summary. Touches NOTHING else.
  - --apply: reads migration_plan.json, backs up players.json to
    data/players_backup_pre_rename.json, applies id backfills + renames.
"""

import json
import os
import sys
import time
from collections import Counter

import requests

from scraper import HEADERS, search_player_espn

def _surname(name):
    toks = [t for t in name.lower().replace(".", " ").split() if t]
    return toks[-1] if toks else ""


def rename_safe(old, new, had_id):
    """Guard against wrong-id backfill corrupting a record.

    - Pure shortening (new tokens are a subset of old, e.g. 'Eoin Morgan' from
      'Eoin Joseph Gerard Morgan') is always safe — legitimate shortenings only
      DROP tokens, never add them.
    - A rename that ADDS a token not present in the formal name introduces a new
      identity, i.e. a different player. We only trust that for PRE-VALIDATED
      ids (already had an id), and only as a same-surname nickname
      ('Isaac Vivian Alexander Richards' -> 'Viv Richards').
    - For BACKFILLED ids (search could have matched the wrong player) we require
      a strict subset, so a shared common name can't slip a different player
      through ('Mohammad Javed Miandad Khan' -/-> 'Mohammad Faizan Khan',
      'Simi Singh' -/-> 'Simranjeet Singh')."""
    if not new:
        return False
    ot, nt = set(old.lower().split()), set(new.lower().split())
    if nt <= ot:
        return True
    # new name adds a token not in the formal name -> different identity.
    if had_id and _surname(old) == _surname(new):
        return True   # trust nickname on a pre-validated id
    return False


PLAYERS_PATH = os.path.join(os.path.dirname(__file__), "data", "players.json")
BACKUP_PATH = os.path.join(os.path.dirname(__file__), "data", "players_backup_pre_rename.json")
PLAN_PATH = os.path.join(os.path.dirname(__file__), "migration_plan.json")
API = "https://site.web.api.espn.com/apis/common/v3/sports/cricket/cricinfo/athletes/{}"
DELAY = 1.5


def fetch_shortname(pid):
    try:
        r = requests.get(API.format(pid), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            a = r.json().get("athlete", {})
            return a.get("shortName") or a.get("displayName") or a.get("fullName")
    except (requests.RequestException, ValueError):
        pass
    return None


def find_id(name):
    # Reuse the scraper's full search chain: HTML, then first+last fallback for
    # 3+ word formal names, then the autocomplete API. ESPN search often returns
    # nothing for a long formal name but resolves a shorter form.
    pid, _, _ = search_player_espn(name)
    return pid


def compute():
    players = json.load(open(PLAYERS_PATH))
    plan = []          # one entry per record: {idx, old_name, new_name, old_id, new_id, status}
    n = len(players)
    for i, p in enumerate(players):
        entry = {"idx": i, "old_name": p["name"], "old_id": p.get("espn_id"),
                 "new_name": p["name"], "new_id": p.get("espn_id"), "status": "ok"}
        pid = p.get("espn_id")
        if not pid:
            pid = find_id(p["name"])
            time.sleep(DELAY)
            if pid:
                entry["new_id"] = pid
            else:
                entry["status"] = "no_id_found"
        if pid:
            sn = fetch_shortname(pid)
            time.sleep(DELAY)
            if sn:
                entry["new_name"] = sn
            else:
                entry["status"] = "no_shortname"
        plan.append(entry)
        if (i + 1) % 25 == 0:
            print(f"  computed {i+1}/{n}", flush=True)
    json.dump(plan, open(PLAN_PATH, "w"), indent=2, ensure_ascii=False)
    summarize(plan, players)


def summarize(plan, players):
    ids_backfilled = sum(1 for e in plan if not e["old_id"] and e["new_id"])
    still_no_id = [e for e in plan if not e["new_id"]]
    renames = [e for e in plan if e["new_name"] != e["old_name"]]
    new_names = [e["new_name"] for e in plan]
    collisions = {nm: c for nm, c in Counter(new_names).items() if c > 1}

    print("\n" + "=" * 64)
    print("MIGRATION DRY-RUN  (plan saved to migration_plan.json)")
    print("=" * 64)
    print(f"Records:                 {len(plan)}")
    print(f"espn_id backfilled:      {ids_backfilled}")
    print(f"still missing id:        {len(still_no_id)}  {[e['old_name'] for e in still_no_id][:8]}")
    print(f"records renamed:         {len(renames)}")
    print(f"post-rename name clashes:{len(collisions)}  {dict(list(collisions.items())[:8])}")
    suspicious = [e for e in renames if not rename_safe(e["old_name"], e["new_name"], bool(e["old_id"]))]
    print(f"SUSPICIOUS renames (surname changed -> will be SKIPPED): {len(suspicious)}")
    for e in suspicious:
        tag = "  [backfilled id]" if not e["old_id"] and e["new_id"] else "  [had id]"
        print(f"    {e['old_name']!r} -> {e['new_name']!r}{tag}")
    print("\n--- sample (accepted) renames ---")
    for e in [r for r in renames if rename_safe(r["old_name"], r["new_name"], bool(r["old_id"]))][:25]:
        tag = "  (+id)" if not e["old_id"] and e["new_id"] else ""
        print(f"  {e['old_name']!r:46s} -> {e['new_name']!r}{tag}")
    print("\n(DRY RUN — players.json untouched. Run with --apply to commit.)")


def apply():
    plan = json.load(open(PLAN_PATH))
    players = json.load(open(PLAYERS_PATH))
    if len(plan) != len(players):
        sys.exit("Plan/players length mismatch — recompute first.")
    json.dump(players, open(BACKUP_PATH, "w"), indent=2, ensure_ascii=False)
    ids_set = renames = skipped = id_unconfirmed = 0
    for e in plan:
        p = players[e["idx"]]
        backfilled = e["new_id"] and not e["old_id"]
        rename_wanted = e["new_name"] != p["name"]
        # Guard: a rename must keep the surname. If a backfilled id produced a
        # surname-incompatible name, the search matched the wrong player — drop
        # both the rename and the suspect id.
        if rename_wanted and not rename_safe(e["old_name"], e["new_name"], bool(e["old_id"])):
            skipped += 1
            continue
        if e["new_id"] and not p.get("espn_id"):
            # A backfilled id is only trustworthy if its identity was confirmed:
            # a shortName came back (status ok) and passed the rename guard above.
            if backfilled and e.get("status") != "ok":
                id_unconfirmed += 1
            else:
                p["espn_id"] = e["new_id"]; ids_set += 1
        if rename_wanted:
            p["name"] = e["new_name"]; renames += 1
    print(f"  (backfilled ids left unset, unconfirmed: {id_unconfirmed})")
    json.dump(players, open(PLAYERS_PATH, "w"), indent=2, ensure_ascii=False)
    print(f"APPLIED: {ids_set} ids set, {renames} renames, {skipped} skipped (surname guard). "
          f"Backup -> {os.path.basename(BACKUP_PATH)}")


if __name__ == "__main__":
    if "--apply" in sys.argv:
        apply()
    elif "--summary" in sys.argv:
        summarize(json.load(open(PLAN_PATH)), json.load(open(PLAYERS_PATH)))
    else:
        compute()
