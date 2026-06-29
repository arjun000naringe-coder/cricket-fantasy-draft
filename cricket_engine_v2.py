"""
Fixed simulation engine (Fix 1 + Fix 2 + opposition coupling).

Separate from cricket_engine.py — NOT merged. Reuses the original's pitch
profiles, day mapping, POTM and series aggregation verbatim; overrides only the
batting/bowling simulation to add:

  Fix 1  — Bayesian regression of bat_avg / bowl_avg toward pool means.
  Couple — batting mean depends on the opposition attack (damped by BETA).
  Fix 2  — role-based bowler eligibility, an over budget, and a bowling card
           whose wickets/overs/runs are derived from records (not random noise).

See MATCH_ENGINE_REHASH_SPEC.md for the full design and rule ledger.
"""

import random

from cricket_engine import (
    get_pitch, _fmt, _num, bowler_type, _balls_faced, _bat_line, _FORMAT,
    _toss, _test_chase_result, compute_potm, aggregate_series, test_day_cards,
    _map_to_days,
)

# ---------------------------------------------------------------------------
# Fix 1 — regression
# ---------------------------------------------------------------------------

# Role-conditioned priors: regress toward the player's ROLE mean, not a global
# one (so a specialist bowler's batting isn't inflated toward the batsman mean).
#   [fmt]['bat'|'bowl'][role]  — role: bat (incl keeper) / all / bowl.
_POOL_BY_ROLE = {
    "Test": {"bat":  {"bat": 40.4, "all": 32.9, "bowl": 12.3},
             "bowl": {"bat": 43.1, "all": 35.7, "bowl": 30.8}},
    "ODI":  {"bat":  {"bat": 37.1, "all": 28.5, "bowl": 12.9},
             "bowl": {"bat": 41.9, "all": 34.0, "bowl": 29.3}},
    "T20I": {"bat":  {"bat": 27.9, "all": 22.4, "bowl": 11.4},
             "bowl": {"bat": 28.1, "all": 25.2, "bowl": 23.3}},
}
# League-average front-line bowler — coupling anchor + economy reference.
_LEAGUE_BOWL = {"Test": 30.8, "ODI": 29.3, "T20I": 23.3}

_K_BAT, _K_BOWL = 15, 25         # confidence constants (innings / wickets)
_BETA = 0.5                      # coupling strength (rule 21)


def _role_cat(player):
    r = (player.get("role") or "").lower()
    return "all" if "all" in r else ("bowl" if "bowl" in r else "bat")


def _prior(fmt, skill, player):
    return _POOL_BY_ROLE.get(fmt, _POOL_BY_ROLE["Test"])[skill][_role_cat(player)]


def _adj_bat(player, fmt):
    f = _fmt(player, fmt)
    raw = _num(f.get("bat_avg"))
    mean = _prior(fmt, "bat", player)
    if raw <= 0:
        return mean
    n = _num(f.get("innings_bat")) or _num(f.get("matches"))
    return (n * raw + _K_BAT * mean) / (n + _K_BAT)


def _adj_bowl(player, fmt):
    f = _fmt(player, fmt)
    raw = _num(f.get("bowl_avg"))
    mean = _prior(fmt, "bowl", player)
    if raw <= 0:
        return mean
    n = _num(f.get("wickets"))
    return (n * raw + _K_BOWL * mean) / (n + _K_BOWL)


# ---------------------------------------------------------------------------
# Fix 2 — eligibility / tiers / over budget
# ---------------------------------------------------------------------------

def _bowl_load(player, fmt):
    f = _fmt(player, fmt)
    m = _num(f.get("matches"))
    return (_num(f.get("wickets")) / m) if m > 0 else 0.0


def bowl_tier(player, fmt):
    """'front' (designated), 'part' (occasional), or None (does not bowl)."""
    role = (player.get("role") or "").lower()
    load = _bowl_load(player, fmt)
    if "bowl" in role:
        return "front"
    if "all" in role and load >= 1.0:
        return "front"
    if load >= 0.3:
        return "part"
    return None


def _pitch_mult(player, pitch):
    return pitch["pace"] if bowler_type(player) == "pace" else pitch["spin"]


def _quality(player, fmt, pitch):
    return (1.0 / max(_adj_bowl(player, fmt), 12.0)) * _pitch_mult(player, pitch)


_PART_WEIGHT = 0.2     # a part-timer bowls ~1/5 the overs of a front-liner


def _allocate(weights, total, cap):
    """Capped water-filling: split `total` among ids ∝ weight, none over `cap`;
    overflow from capped bowlers spills to the rest so the sum stays = total."""
    alloc = {k: 0.0 for k in weights}
    active = [k for k in weights if weights[k] > 0]
    remaining = total
    while active and remaining > 1e-6:
        wsum = sum(weights[k] for k in active)
        capped = [k for k in active if alloc[k] + remaining * weights[k] / wsum > cap + 1e-9]
        if capped:
            for k in capped:
                remaining -= (cap - alloc[k])
                alloc[k] = cap
            active = [k for k in active if k not in capped]
        else:
            for k in active:
                alloc[k] += remaining * weights[k] / wsum
            remaining = 0.0
    return alloc


def _over_budget(bowling_team, fmt, pitch, overs):
    """id(player) -> overs. Overs are set by TIER (stamina/rotation), not skill:
    front-liners bowl roughly equally; part-timers get ~1/5 of a front-liner's
    load; pure non-bowlers get none. Skill and pitch enter only via wickets."""
    tiers = {id(p): bowl_tier(p, fmt) for p in bowling_team}
    eligible = [p for p in bowling_team if tiers[id(p)] is not None]
    if not eligible:                                   # no one bowls (all pure bats)
        eligible = list(bowling_team)                  # degenerate: share equally
        weights = {id(p): 1.0 for p in eligible}
    else:
        weights = {id(p): (1.0 if tiers[id(p)] == "front" else _PART_WEIGHT)
                   for p in eligible}
    # Cap at 40% of the innings, but relax if too few bowlers to cover the innings
    # otherwise (e.g. a side that picked no specialist bowlers must bowl them more).
    cap = max(0.40 * overs, overs / len(eligible))
    return _allocate(weights, overs, cap)


# ---------------------------------------------------------------------------
# Coupling — batting mean depends on the opposition attack
# ---------------------------------------------------------------------------

def _attack_strength(bowling_team, fmt, pitch):
    fronts = [p for p in bowling_team if bowl_tier(p, fmt) == "front"]
    if not fronts:
        fronts = [p for p in bowling_team if bowl_tier(p, fmt) is not None]
    if not fronts:
        return None
    return sum(_quality(p, fmt, pitch) for p in fronts) / len(fronts)


def _coupling_multiplier(bowling_team, fmt, pitch):
    a = _attack_strength(bowling_team, fmt, pitch)
    if not a:
        return 1.0
    league = (1.0 / _LEAGUE_BOWL.get(fmt, _LEAGUE_BOWL["Test"])) * ((pitch["pace"] + pitch["spin"]) / 2.0)
    return (league / a) ** _BETA


_BASE = {"Test": 1.0, "ODI": 0.80, "T20I": 0.72}


def _bat_mean(adj_avg, fmt, pitch, mult):
    return max(2.0, adj_avg) * _BASE[fmt] * pitch.get("bat", 1.0) * mult


# ---------------------------------------------------------------------------
# Player ordering
# ---------------------------------------------------------------------------

def batting_order(team, fmt):
    return sorted(team, key=lambda p: _adj_bat(p, fmt), reverse=True)


# ---------------------------------------------------------------------------
# Bowling card (Fix 2 — derived, not random)
# ---------------------------------------------------------------------------

def _assign_wickets(bowling_team, fmt, pitch, num_wickets, budget):
    elig = [p for p in bowling_team if budget.get(id(p), 0) > 0]
    if not elig:
        elig = list(bowling_team)
        budget = {id(p): 1.0 for p in elig}
    weights = [max(budget[id(p)] * (1.0 / max(_adj_bowl(p, fmt), 12.0)) * _pitch_mult(p, pitch), 1e-6)
               for p in elig]
    caps = {id(p): max(1, round(budget[id(p)] / 3.0)) for p in elig}
    tally = {id(p): 0 for p in elig}
    for _ in range(num_wickets):
        avail = [(p, w) for p, w in zip(elig, weights) if tally[id(p)] < caps[id(p)]]
        if not avail:
            avail = list(zip(elig, weights))
        ps = [a[0] for a in avail]
        ws = [a[1] for a in avail]
        pick = random.choices(ps, weights=ws, k=1)[0]
        tally[id(pick)] += 1
    return elig, tally, budget


def _bowling_card(elig, fmt, pitch, total, tally, budget):
    pool_bowl = _LEAGUE_BOWL.get(fmt, _LEAGUE_BOWL["Test"])
    ew = {}
    for p in elig:
        econ = (_adj_bowl(p, fmt) / pool_bowl) ** 0.3
        ew[id(p)] = budget[id(p)] * econ
    s = sum(ew.values()) or 1.0
    runs_pool = int(total * 0.95)
    card = []
    for p in elig:
        card.append({
            "name": p["name"],
            "overs": round(budget[id(p)], 1),
            "runs": max(int(runs_pool * ew[id(p)] / s), 0),
            "wickets": tally.get(id(p), 0),
        })
    card.sort(key=lambda c: c["wickets"], reverse=True)
    return card


# ---------------------------------------------------------------------------
# Innings simulation (coupled)
# ---------------------------------------------------------------------------

def simulate_innings(batting_team, bowling_team, game_format, pitch,
                     innings_index, target=None, overs_available=None):
    cfg = _FORMAT[game_format]
    max_overs = cfg["max_overs_per_innings"]
    if overs_available is not None:
        max_overs = overs_available if max_overs is None else min(max_overs, overs_available)

    order = batting_order(batting_team, game_format)
    rr = cfg["run_rate"] * (0.9 + 0.2 * random.random()) * (0.5 + 0.5 * pitch.get("bat", 1.0))
    mult = _coupling_multiplier(bowling_team, game_format, pitch)   # opposition coupling

    batting, total, wickets, overs_used, chase_done = [], 0, 0, 0.0, False

    for i, p in enumerate(order):
        if wickets >= 10:
            break
        if max_overs is not None and overs_used >= max_overs:
            break
        adj = _adj_bat(p, game_format)
        mean = _bat_mean(adj, game_format, pitch, mult)
        if random.random() < 0.07:
            runs = 0
        else:
            runs = int(random.expovariate(1.0 / max(mean, 3.0)))
        if game_format != "Test":
            runs = max(int(runs * (1.0 - 0.04 * i)), 0)

        balls = _balls_faced(runs, game_format)
        overs_used += balls / 6.0
        if max_overs is not None and overs_used > max_overs:
            overspill = overs_used - max_overs
            balls = max(1, int(balls - overspill * 6))
            runs = min(runs, int(balls * rr / 6.0) + 2)
            overs_used = max_overs

        total += runs
        if target is not None and total >= target:
            batting.append(_bat_line(p, runs, balls, False))
            chase_done = True
            break

        batting.append(_bat_line(p, runs, balls, True))
        wickets += 1
        if max_overs is not None and overs_used >= max_overs:
            wickets -= 1
            batting[-1]["out"] = False
            break

    overs_used = round(min(overs_used, max_overs) if max_overs else overs_used, 1)
    budget = _over_budget(bowling_team, game_format, pitch, max(overs_used, 1.0))
    elig, tally, budget = _assign_wickets(bowling_team, game_format, pitch, wickets, budget)
    bowling = _bowling_card(elig, game_format, pitch, total, tally, budget)

    return {
        "batting_team": None, "bowling_team": None,
        "total": total, "wickets": wickets, "overs": overs_used,
        "declared": False, "chase_done": chase_done,
        "batting": batting, "bowling": bowling,
    }


# ---------------------------------------------------------------------------
# Match assembly (copied structure; calls THIS module's simulate_innings)
# ---------------------------------------------------------------------------

def simulate_limited_overs(team1, team2, team1_name, team2_name, venue, game_format):
    pitch = get_pitch(venue)
    toss_winner, decision = _toss(team1_name, team2_name, game_format, pitch)
    if (toss_winner == team1_name) == (decision == "bat"):
        first, second = (team1, team1_name), (team2, team2_name)
    else:
        first, second = (team2, team2_name), (team1, team1_name)

    inn1 = simulate_innings(first[0], second[0], game_format, pitch, 0)
    inn1["batting_team"], inn1["bowling_team"] = first[1], second[1]
    target = inn1["total"] + 1
    inn2 = simulate_innings(second[0], first[0], game_format, pitch, 1, target=target)
    inn2["batting_team"], inn2["bowling_team"] = second[1], first[1]

    if inn2["chase_done"]:
        winner, margin = second[1], f"{10 - inn2['wickets']} wickets"
    elif inn2["total"] == inn1["total"]:
        winner, margin = None, "a tie"
    else:
        winner, margin = first[1], f"{inn1['total'] - inn2['total']} runs"

    innings = [inn1, inn2]
    result_text = f"{winner} won by {margin}" if winner else "Match tied"
    return {
        "format": game_format, "venue": venue, "pitch": pitch,
        "toss": f"{toss_winner} won the toss and elected to {decision}",
        "innings": innings, "winner": winner, "margin": margin,
        "result_text": result_text, "potm": compute_potm(innings, winner),
    }


def simulate_test(team1, team2, team1_name, team2_name, venue):
    pitch = get_pitch(venue)
    toss_winner, decision = _toss(team1_name, team2_name, "Test", pitch)
    if (toss_winner == team1_name) == (decision == "bat"):
        A, An, B, Bn = team1, team1_name, team2, team2_name
    else:
        A, An, B, Bn = team2, team2_name, team1, team1_name

    OVERS_TOTAL = 450
    used = [0.0]

    def play(bat, bowl, batn, bowln, idx, target=None):
        remaining = OVERS_TOTAL - used[0]
        inn = simulate_innings(bat, bowl, "Test", pitch, idx, target=target,
                               overs_available=max(remaining, 0))
        inn["batting_team"], inn["bowling_team"] = batn, bowln
        used[0] += inn["overs"]
        return inn

    inn1 = play(A, B, An, Bn, 0)
    inn2 = play(B, A, Bn, An, 1)
    innings = [inn1, inn2]

    lead = inn1["total"] - inn2["total"]
    winner = margin = None
    follow_on = lead >= 200 and random.random() < 0.6 and used[0] < OVERS_TOTAL * 0.55

    if follow_on:
        inn3 = play(B, A, Bn, An, 2)
        innings.append(inn3)
        if inn2["total"] + inn3["total"] < inn1["total"]:
            winner = An
            margin = f"an innings and {inn1['total'] - inn2['total'] - inn3['total']} runs"
        else:
            target = inn2["total"] + inn3["total"] - inn1["total"] + 1
            inn4 = play(A, B, An, Bn, 3, target=target)
            innings.append(inn4)
            winner, margin = _test_chase_result(An, Bn, inn4, target, used[0], OVERS_TOTAL)
    else:
        inn3 = play(A, B, An, Bn, 2)
        innings.append(inn3)
        target = inn1["total"] + inn3["total"] - inn2["total"] + 1
        if used[0] >= OVERS_TOTAL:
            winner = None
        else:
            inn4 = play(B, A, Bn, An, 3, target=target)
            innings.append(inn4)
            winner, margin = _test_chase_result(Bn, An, inn4, target, used[0], OVERS_TOTAL)

    result_text = f"{winner} won by {margin}" if winner else "Match drawn"
    return {
        "format": "Test", "venue": venue, "pitch": pitch,
        "toss": f"{toss_winner} won the toss and elected to {decision}",
        "innings": innings, "winner": winner, "margin": margin,
        "result_text": result_text, "potm": compute_potm(innings, winner),
        "days": _map_to_days(innings),
    }
