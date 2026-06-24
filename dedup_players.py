#!/usr/bin/env python3
"""
De-duplicate data/players.json.

Two duplicate sources (see investigation):
  1. Exact-name copies created when name-only dedup failed (short input name
     never matched the stored ESPN formal name) and records had no espn_id.
  2. Short<->full name twins for the same player (e.g. 'Harry Brook' vs
     'Harry Cherrington Brook').

Clustering signals (union-find):
  S1  same non-empty espn_id           -> definitely same player
  S2  identical name string            -> exact-dup copies
  S3  name-compatible AND stats-agree  -> short<->full twins (guarded)

The stats fingerprint is the guard: two records only fuzzy-merge if they share
a format with identical (matches, runs, wickets). This is what keeps the two
'Balapuwaduge ... Mendis' players (same surname tokens, different careers) apart.

Default is a DRY RUN (writes nothing). Pass --apply to write, which first backs
up to data/players_backup_pre_dedup.json.
"""

import json
import os
import re
import sys
from difflib import SequenceMatcher

PLAYERS_PATH = os.path.join(os.path.dirname(__file__), "data", "players.json")
BACKUP_PATH = os.path.join(os.path.dirname(__file__), "data", "players_backup_pre_dedup.json")


def norm_tokens(name):
    return re.sub(r"[^a-z ]", " ", name.lower()).split()


def stats_fp(p):
    fp = {}
    for fmt, s in (p.get("formats") or {}).items():
        fp[fmt] = (
            int(s.get("matches", 0) or 0),
            int(s.get("runs", 0) or 0),
            int(s.get("wickets", 0) or 0),
        )
    return fp


def stats_agree(a, b):
    """True if a & b share at least one format with identical (M,R,W)."""
    fa, fb = stats_fp(a), stats_fp(b)
    shared = set(fa) & set(fb)
    return any(fa[f] == fb[f] for f in shared) if shared else False


def name_compatible(a, b):
    """Last name must match; first name equal / prefix / initial / shared 3-char stem."""
    ta, tb = norm_tokens(a["name"]), norm_tokens(b["name"])
    if not ta or not tb or ta[-1] != tb[-1]:
        return False
    fa, fb = ta[0], tb[0]
    if fa == fb:
        return True
    if fa.startswith(fb) or fb.startswith(fa):
        return True
    if len(fa) == 1 or len(fb) == 1:
        return True
    if len(fa) >= 3 and len(fb) >= 3 and fa[:3] == fb[:3]:
        return True
    return False


# --- union-find ---
def make_clusters(players):
    n = len(players)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # S1: same espn_id
    by_id = {}
    for i, p in enumerate(players):
        pid = p.get("espn_id")
        if pid:
            by_id.setdefault(pid, []).append(i)
    for idxs in by_id.values():
        for j in idxs[1:]:
            union(idxs[0], j)

    # S2: identical name
    by_name = {}
    for i, p in enumerate(players):
        by_name.setdefault(p["name"].lower(), []).append(i)
    for idxs in by_name.values():
        for j in idxs[1:]:
            union(idxs[0], j)

    # S3: name-compatible AND stats-agree (guarded fuzzy)  +  record which pairs were
    #     name-compatible but stats-DISAGREE (ambiguous -> reported, not merged)
    fuzzy_merges = []   # (i, j) auto-merged via S3
    rejected = []       # (i, j) name-compatible but stats disagree
    for i in range(n):
        for j in range(i + 1, n):
            if find(i) == find(j):
                continue
            if name_compatible(players[i], players[j]):
                if stats_agree(players[i], players[j]):
                    union(i, j)
                    fuzzy_merges.append((i, j))
                else:
                    rejected.append((i, j))

    clusters = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)
    return clusters, fuzzy_merges, rejected


def score(p):
    """Higher = better surviving record."""
    complete = sum(
        1 for f in ("country", "bat_hand", "role")
        if p.get(f) not in (None, "", "Unknown")
    ) + (1 if p.get("bowl_style") not in (None, "", "Unknown") else 0)
    return (
        0 if p.get("partial_metadata") else 1,   # prefer not-partial
        complete,                                 # prefer complete metadata
        len(p.get("formats") or {}),              # prefer most formats
        1 if p.get("espn_id") else 0,             # prefer has-id
    )


def merge_cluster(players, idxs):
    """Pick winner, fill its gaps from siblings, union formats. Returns merged record + alias names."""
    recs = [players[i] for i in idxs]
    winner = dict(max(recs, key=score))
    aliases = sorted({r["name"] for r in recs if r["name"] != winner["name"]})

    for r in recs:
        if not winner.get("espn_id") and r.get("espn_id"):
            winner["espn_id"] = r["espn_id"]
        for f in ("country", "bat_hand", "role"):
            if winner.get(f) in (None, "", "Unknown") and r.get(f) not in (None, "", "Unknown"):
                winner[f] = r[f]
        # 'N/A' is a placeholder here too: siblings are the same player, so a
        # concrete bowling style (from a twin) should beat ESPN's 'N/A'.
        _bowl_blank = (None, "", "Unknown", "N/A")
        if winner.get("bowl_style") in _bowl_blank and r.get("bowl_style") not in _bowl_blank:
            winner["bowl_style"] = r["bowl_style"]
        for fmt, s in (r.get("formats") or {}).items():
            if fmt not in winner.get("formats", {}):
                winner.setdefault("formats", {})[fmt] = s
    if winner.get("bat_hand") not in (None, "", "Unknown") and winner.get("partial_metadata"):
        winner.pop("partial_metadata", None)
    return winner, aliases


def main():
    apply = "--apply" in sys.argv
    players = json.load(open(PLAYERS_PATH))
    clusters, fuzzy_merges, rejected = make_clusters(players)

    merged = []
    multi = []  # clusters with >1 record, for reporting
    for root, idxs in clusters.items():
        rec, aliases = merge_cluster(players, idxs)
        merged.append(rec)
        if len(idxs) > 1:
            multi.append((rec, idxs, aliases))

    print(f"{'='*70}")
    print(f"DEDUP {'APPLY' if apply else 'DRY-RUN'}")
    print(f"{'='*70}")
    print(f"Records in:  {len(players)}")
    print(f"Records out: {len(merged)}   (removed {len(players) - len(merged)})")
    print(f"Clusters with duplicates: {len(multi)}")
    print(f"Fuzzy short<->full merges (S3): {len(fuzzy_merges)}")
    print()

    # report fuzzy merges explicitly (the part needing eyes)
    if fuzzy_merges:
        print("--- FUZZY short<->full MERGES (name-compatible + stats match) ---")
        for i, j in fuzzy_merges:
            a, b = players[i], players[j]
            print(f"  MERGE: {a['name']!r}  <->  {b['name']!r}")
        print()

    # report ambiguous rejects (the guard working — NOT merged)
    if rejected:
        print("--- NOT merged (name-compatible but stats DIFFER — kept separate) ---")
        seen = set()
        for i, j in rejected:
            key = tuple(sorted((players[i]["name"], players[j]["name"])))
            if key in seen:
                continue
            seen.add(key)
            print(f"  KEEP SEPARATE: {players[i]['name']!r}  vs  {players[j]['name']!r}")
        print()

    # top exact-dup collapses
    print("--- duplicate clusters (kept record <- # dropped) ---")
    for rec, idxs, aliases in sorted(multi, key=lambda x: -len(x[1]))[:40]:
        alias_str = f"  aliases={aliases}" if aliases else ""
        print(f"  {len(idxs)-1:2d} dropped  ->  keep {rec['name']!r} (id={rec.get('espn_id')}){alias_str}")

    if apply:
        json.dump(players, open(BACKUP_PATH, "w"), indent=2, ensure_ascii=False)
        json.dump(merged, open(PLAYERS_PATH, "w"), indent=2, ensure_ascii=False)
        print(f"\nAPPLIED. Backup -> {os.path.basename(BACKUP_PATH)}, wrote {len(merged)} records.")
    else:
        print(f"\n(DRY RUN — nothing written. Re-run with --apply to commit.)")


if __name__ == "__main__":
    main()
