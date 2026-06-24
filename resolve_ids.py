#!/usr/bin/env python3
"""
Short-name id re-resolution + id-correctness validation.

Migration's id backfill searched players by their long *formal* name, which
ESPN search often can't resolve ("Bapu Krishnarao Venkatesh Prasad" finds
nothing; "Venkatesh Prasad" does). This pass:

  1. MISSING ids: for each id-less record, search focused 2-word forms derived
     from the formal name (adjacent token pairs, first+last, last-two), collect
     candidate ids, and accept one ONLY if its statsguru career stats match the
     record's stored stats (orthogonal signal -> wrong id impossible). On a
     confirmed match, also pull shortName to fix the formal name.

  2. INCORRECT ids: for each record that already has an id, re-fetch that id's
     statsguru stats and confirm they match the stored stats. Mismatches are
     flagged as suspect ids (and a re-resolution is attempted for a better one).

Default = compute (network, writes plan to resolve_plan.json, prints a report;
players.json untouched). --apply commits from the plan with a backup.
"""

import json
import os
import sys
import time

import requests

from scraper import (
    load_players, save_players, _search_espn_html, _fetch_statsguru_allround,
    HEADERS,
)

PLAYERS_PATH = os.path.join(os.path.dirname(__file__), "data", "players.json")
BACKUP_PATH = os.path.join(os.path.dirname(__file__), "data", "players_backup_pre_resolve.json")
PLAN_PATH = os.path.join(os.path.dirname(__file__), "resolve_plan.json")
API = "https://site.web.api.espn.com/apis/common/v3/sports/cricket/cricinfo/athletes/{}"
DELAY = 1.2
MAX_CANDS = 14


def fetch_shortname(pid):
    try:
        r = requests.get(API.format(pid), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            a = r.json().get("athlete", {})
            return a.get("shortName") or a.get("displayName") or a.get("fullName")
    except (requests.RequestException, ValueError):
        pass
    return None


def stored_fp(p):
    return {f: (int(s.get("matches", 0) or 0), int(s.get("runs", 0) or 0), int(s.get("wickets", 0) or 0))
            for f, s in (p.get("formats") or {}).items()}


def cand_fp(allround):
    return {f: (int(s.get("matches", 0) or 0), int(s.get("runs", 0) or 0), int(s.get("wickets", 0) or 0))
            for f, s in (allround or {}).items()}


def stats_match(stored, cand):
    """True if the candidate is the same player. Uses the stored record's
    biggest format as a fingerprint: matches must agree (candidate may be a bit
    fresher, never fewer) and career runs must be close. Statsguru is the same
    source the stored stats came from, so a correct id re-fetches near-identically."""
    if not stored or not cand:
        return False
    sig = max(stored, key=lambda f: stored[f][0])
    if stored[sig][0] == 0 or sig not in cand:
        return False
    sm, sr, _ = stored[sig]
    cm, cr, _ = cand[sig]
    matches_ok = cm >= sm and (cm - sm) <= max(3, round(sm * 0.15))
    runs_ok = abs(cr - sr) <= max(30, round(sr * 0.08))
    return matches_ok and runs_ok


def candidate_queries(name):
    toks = name.split()
    qs = []
    if len(toks) >= 2:
        qs.append(f"{toks[0]} {toks[-1]}")     # first + last
        qs.append(f"{toks[-2]} {toks[-1]}")    # last two
        for i in range(len(toks) - 1):         # adjacent pairs (catches buried short names)
            qs.append(f"{toks[i]} {toks[i+1]}")
    seen, out = set(), []
    for q in qs:
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


def resolve(stored_record):
    """Search short forms, return (pid, shortName) of the stats-confirmed match, or (None, None)."""
    sfp = stored_fp(stored_record)
    tried_ids = set()
    for q in candidate_queries(stored_record["name"]):
        cands = _search_espn_html(q)
        time.sleep(DELAY)
        for pid, _, _ in cands[:MAX_CANDS]:
            if pid in tried_ids:
                continue
            tried_ids.add(pid)
            allround = _fetch_statsguru_allround(pid)
            time.sleep(DELAY)
            if stats_match(sfp, cand_fp(allround)):
                return pid, fetch_shortname(pid)
            if len(tried_ids) >= MAX_CANDS:
                break
    return None, None


def compute():
    players = load_players()
    plan = []
    n = len(players)
    for i, p in enumerate(players):
        entry = {"idx": i, "name": p["name"], "old_id": p.get("espn_id"),
                 "new_id": p.get("espn_id"), "new_name": p["name"], "status": "ok"}
        sfp = stored_fp(p)
        pid = p.get("espn_id")
        if pid:
            # validate existing id
            cand = cand_fp(_fetch_statsguru_allround(pid))
            time.sleep(DELAY)
            if stats_match(sfp, cand):
                entry["status"] = "id_ok"
            else:
                # existing id looks wrong -> try to find a correct one
                rid, rname = resolve(p)
                if rid and rid != pid:
                    entry.update(status="id_corrected", new_id=rid)
                    if rname:
                        entry["new_name"] = rname
                else:
                    entry["status"] = "id_suspect_unresolved"
        else:
            rid, rname = resolve(p)
            if rid:
                entry.update(status="id_resolved", new_id=rid)
                if rname:
                    entry["new_name"] = rname
            else:
                entry["status"] = "still_no_id"
        plan.append(entry)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{n}", flush=True)
    json.dump(plan, open(PLAN_PATH, "w"), indent=2, ensure_ascii=False)
    report(plan)


def report(plan):
    from collections import Counter
    c = Counter(e["status"] for e in plan)
    print("\n" + "=" * 64)
    print("RESOLVE DRY-RUN (plan -> resolve_plan.json)")
    print("=" * 64)
    for k in ("id_ok", "id_resolved", "id_corrected", "id_suspect_unresolved", "still_no_id"):
        print(f"  {k:24s}: {c.get(k,0)}")
    print("\n-- newly RESOLVED missing ids --")
    for e in [e for e in plan if e["status"] == "id_resolved"]:
        rn = f"   rename-> {e['new_name']!r}" if e["new_name"] != e["name"] else ""
        print(f"   {e['name']!r:46s} +id={e['new_id']}{rn}")
    corrected = [e for e in plan if e["status"] == "id_corrected"]
    if corrected:
        print("\n-- INCORRECT ids replaced --")
        for e in corrected:
            print(f"   {e['name']!r}: {e['old_id']} -> {e['new_id']}")
    suspect = [e for e in plan if e["status"] == "id_suspect_unresolved"]
    if suspect:
        print(f"\n-- id stats-MISMATCH, no better id found ({len(suspect)}) --")
        for e in suspect:
            print(f"   {e['name']!r} (id={e['old_id']})")
    print("\n(DRY RUN — players.json untouched. Re-run with --apply to commit.)")


def apply():
    plan = json.load(open(PLAN_PATH))
    players = load_players()
    if len(plan) != len(players):
        sys.exit("Plan/players length mismatch — recompute first.")
    json.dump(players, open(BACKUP_PATH, "w"), indent=2, ensure_ascii=False)
    ids_set = ids_fixed = renames = 0
    for e in plan:
        p = players[e["idx"]]
        if e["new_id"] and e["new_id"] != p.get("espn_id"):
            if e["status"] == "id_corrected":
                ids_fixed += 1
            else:
                ids_set += 1
            p["espn_id"] = e["new_id"]
        if e["new_name"] != p["name"]:
            p["name"] = e["new_name"]
            renames += 1
    save_players(players)
    print(f"APPLIED: {ids_set} missing ids resolved, {ids_fixed} wrong ids fixed, "
          f"{renames} names shortened. Backup -> {os.path.basename(BACKUP_PATH)}")


if __name__ == "__main__":
    if "--apply" in sys.argv:
        apply()
    elif "--summary" in sys.argv:
        report(json.load(open(PLAN_PATH)))
    else:
        compute()
