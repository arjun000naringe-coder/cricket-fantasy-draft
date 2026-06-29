"""
Authoritative cricket simulation engine.

Code decides every outcome — innings totals, per-player scorecards, wickets,
results, margins, declarations, follow-ons, draws and Player of the Match —
from player career stats, modulated by venue/pitch conditions. The LLM layer
(in match_simulator) only narrates the scorecards this engine produces, so the
numbers a player sees are always internally consistent.

Granularity: innings/player-level statistical model (not ball-by-ball). Fast,
tunable, and produces full batting + bowling cards per innings.
"""

import random
import re

# ---------------------------------------------------------------------------
# Pitch profiles  (Fix 1 — conditions modify OUTCOMES, not just narrative)
#   pace / spin : multipliers on a bowler's share of wickets by type
#   bat         : scoring-ease multiplier on totals
#   deteriorate : extra spin weighting added per subsequent innings (Test wear)
#   desc        : narrator-facing description of the surface
# ---------------------------------------------------------------------------

_COUNTRY_PITCH = {
    "India":        dict(pace=0.85, spin=1.35, bat=1.05, deteriorate=0.12,
                         desc="dry surface that grips and turns more as the match wears on; spinners are central"),
    "Australia":    dict(pace=1.30, spin=0.85, bat=1.00, deteriorate=0.05,
                         desc="hard, bouncy, true surface with pace and carry; fast bowlers thrive"),
    "England":      dict(pace=1.30, spin=0.80, bat=0.92, deteriorate=0.05,
                         desc="green-tinged surface under overcast skies; seam and swing dominate"),
    "South Africa": dict(pace=1.32, spin=0.80, bat=0.95, deteriorate=0.05,
                         desc="quick, bouncy pitch with steep carry; seamers are dangerous"),
    "Pakistan":     dict(pace=1.00, spin=1.20, bat=1.05, deteriorate=0.10,
                         desc="flat early then slow and dry; spin and reverse swing come into play later"),
    "Sri Lanka":    dict(pace=0.80, spin=1.42, bat=1.00, deteriorate=0.14,
                         desc="dry, humid conditions with sharp turn; spinners dictate terms"),
    "West Indies":  dict(pace=1.20, spin=0.95, bat=0.98, deteriorate=0.07,
                         desc="pace-friendly with variable bounce"),
    "New Zealand":  dict(pace=1.25, spin=0.85, bat=0.95, deteriorate=0.05,
                         desc="seam-friendly surface with a breeze and lateral movement"),
    "Bangladesh":   dict(pace=0.80, spin=1.45, bat=1.00, deteriorate=0.14,
                         desc="slow, low pitch that takes rank turn; spinners dominate"),
    "UAE":          dict(pace=0.90, spin=1.30, bat=1.00, deteriorate=0.12,
                         desc="slow, low and tired surface that aids spin"),
}

# Venue keyword overrides (most specific wins). Keyword matched in venue string.
_VENUE_OVERRIDES = {
    "WACA":        dict(pace=1.45, spin=0.70, bat=1.00, desc="the fastest, bounciest deck in world cricket; express pace rules"),
    "Perth":       dict(pace=1.45, spin=0.70, bat=1.00, desc="raw pace and steep bounce; a fast bowler's paradise"),
    "Gabba":       dict(pace=1.35, spin=0.80, desc="bouncy and quick, especially early"),
    "Galle":       dict(pace=0.68, spin=1.60, bat=1.00, deteriorate=0.17, desc="a spinner's haven that turns square from day two"),
    "Chinnaswamy": dict(pace=0.95, spin=1.15, bat=1.18, desc="a flat, high-scoring batting belter at altitude"),
    "Wankhede":    dict(pace=0.95, spin=1.25, bat=1.08, desc="true bounce early then sharp turn; aids spin later"),
    "Sharjah":     dict(pace=0.85, spin=1.35, bat=0.98, desc="slow, low and well-worn; tailor-made for spin"),
    "Lord's":      dict(pace=1.30, spin=0.82, bat=0.95, desc="the famous slope with seam and swing under cloud"),
}

_SPIN_WORDS = ("spin", "orthodox", "legbreak", "leg break", "offbreak", "off break",
               "off-break", "chinaman", "wrist", "googly", "slow left")
_PACE_WORDS = ("fast", "medium", "seam", "swing", "pace", "quick")


def get_pitch(venue):
    """Resolve a pitch profile from a venue string."""
    base = None
    for kw, prof in _VENUE_OVERRIDES.items():
        if kw.lower() in venue.lower():
            base = dict(_COUNTRY_PITCH.get(_country_for_venue(venue), _COUNTRY_PITCH["India"]))
            base.update(prof)
            return base
    country = _country_for_venue(venue)
    return dict(_COUNTRY_PITCH.get(country, _COUNTRY_PITCH["India"]))


_VENUE_CITY_COUNTRY = {
    "Mumbai": "India", "Kolkata": "India", "Bangalore": "India", "Bengaluru": "India",
    "Chennai": "India", "Ahmedabad": "India", "Delhi": "India", "Wankhede": "India",
    "Eden Gardens": "India", "Chinnaswamy": "India", "Chidambaram": "India", "Modi": "India",
    "Melbourne": "Australia", "Sydney": "Australia", "Gabba": "Australia", "Brisbane": "Australia",
    "Adelaide": "Australia", "WACA": "Australia", "Perth": "Australia",
    "Lord's": "England", "Oval": "England", "Old Trafford": "England", "Manchester": "England",
    "Edgbaston": "England", "Birmingham": "England", "Headingley": "England", "Leeds": "England", "London": "England",
    "Newlands": "South Africa", "Cape Town": "South Africa", "Wanderers": "South Africa",
    "Johannesburg": "South Africa", "Centurion": "South Africa", "Kingsmead": "South Africa", "Durban": "South Africa",
    "Karachi": "Pakistan", "Lahore": "Pakistan", "Rawalpindi": "Pakistan", "Gaddafi": "Pakistan",
    "Colombo": "Sri Lanka", "Galle": "Sri Lanka", "Pallekele": "Sri Lanka", "Premadasa": "Sri Lanka",
    "Barbados": "West Indies", "Jamaica": "West Indies", "Trinidad": "West Indies",
    "Kensington": "West Indies", "Sabina": "West Indies", "Queen's Park": "West Indies",
    "Wellington": "New Zealand", "Christchurch": "New Zealand", "Auckland": "New Zealand",
    "Basin Reserve": "New Zealand", "Hagley": "New Zealand", "Eden Park": "New Zealand",
    "Dhaka": "Bangladesh", "Chittagong": "Bangladesh", "Sher-e-Bangla": "Bangladesh", "Zahur": "Bangladesh",
    "Dubai": "UAE", "Abu Dhabi": "UAE", "Sharjah": "UAE",
}


def _country_for_venue(venue):
    for city, country in _VENUE_CITY_COUNTRY.items():
        if city.lower() in venue.lower():
            return country
    return "India"


# ---------------------------------------------------------------------------
# Player helpers
# ---------------------------------------------------------------------------

def _fmt(player, game_format):
    return player.get("formats", {}).get(game_format, {})


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def bowler_type(player):
    style = (player.get("bowl_style") or "").lower()
    role = (player.get("role") or "").lower()
    text = style + " " + role
    if any(w in text for w in _SPIN_WORDS):
        return "spin"
    if any(w in text for w in _PACE_WORDS):
        return "pace"
    # Fall back by role: a generic 'bowler' with no style -> treat as pace
    return "pace"


def is_bowler(player, game_format):
    role = (player.get("role") or "").lower()
    f = _fmt(player, game_format)
    if "bowl" in role or "all" in role:
        return True
    return _num(f.get("wickets")) > 0 or _num(f.get("bowl_avg")) > 0


def batting_order(team, game_format):
    """Order the XI roughly 1..11 by batting average (specialists up, tail down)."""
    return sorted(team, key=lambda p: _num(_fmt(p, game_format).get("bat_avg")), reverse=True)


def _bowlers(team, game_format):
    bs = [p for p in team if is_bowler(p, game_format)]
    if not bs:                       # degenerate: everyone bowls a bit
        bs = list(team)
    return bs


# ---------------------------------------------------------------------------
# Format tuning
# ---------------------------------------------------------------------------

_FORMAT = {
    "Test": dict(run_rate=3.2, max_overs_per_innings=None),
    "ODI":  dict(run_rate=5.7, max_overs_per_innings=50),
    "T20I": dict(run_rate=8.2, max_overs_per_innings=20),
}


def _bowling_strength(team, game_format, pitch):
    """Average wicket-taking quality of an attack (higher = better), pitch-aware."""
    bs = _bowlers(team, game_format)
    score = 0.0
    for p in bs:
        avg = _num(_fmt(p, game_format).get("bowl_avg")) or 32.0
        eff = 1.0 / max(avg, 12.0)
        eff *= pitch["pace"] if bowler_type(p) == "pace" else pitch["spin"]
        score += eff
    return score / max(len(bs), 1)


def _top_bat_avg(team, game_format, n=7):
    order = batting_order(team, game_format)[:n]
    vals = [_num(_fmt(p, game_format).get("bat_avg")) for p in order]
    return sum(vals) / max(len(vals), 1)


# ---------------------------------------------------------------------------
# Innings simulation
# ---------------------------------------------------------------------------

def _assign_wickets(bowling_team, game_format, pitch, num_wickets, innings_index):
    """Distribute `num_wickets` across the attack, weighted by quality & pitch."""
    bs = _bowlers(bowling_team, game_format)
    weights = []
    wear = 1.0 + pitch.get("deteriorate", 0.0) * innings_index   # spin grows over innings
    for p in bs:
        avg = _num(_fmt(p, game_format).get("bowl_avg")) or 32.0
        w = 1.0 / max(avg, 12.0)
        if bowler_type(p) == "pace":
            w *= pitch["pace"]
        else:
            w *= pitch["spin"] * wear
        weights.append(max(w, 0.01))
    tally = {id(p): 0 for p in bs}
    for _ in range(num_wickets):
        pick = random.choices(bs, weights=weights, k=1)[0]
        tally[id(pick)] += 1
    return bs, tally


def _bat_mean(bat_avg, game_format, pitch):
    base = {"Test": 0.92, "ODI": 0.80, "T20I": 0.72}[game_format]
    return max(2.0, bat_avg) * base * pitch.get("bat", 1.0)


def simulate_innings(batting_team, bowling_team, game_format, pitch,
                     innings_index, target=None, overs_available=None):
    """Simulate one innings, returning a structured scorecard."""
    cfg = _FORMAT[game_format]
    max_overs = cfg["max_overs_per_innings"]
    if overs_available is not None:
        max_overs = overs_available if max_overs is None else min(max_overs, overs_available)

    order = batting_order(batting_team, game_format)
    rr = cfg["run_rate"] * (0.9 + 0.2 * random.random()) * (0.5 + 0.5 * pitch.get("bat", 1.0))

    batting = []
    total = 0
    wickets = 0
    overs_used = 0.0
    chase_done = False

    for i, p in enumerate(order):
        if wickets >= 10:
            break
        if max_overs is not None and overs_used >= max_overs:
            break
        bat_avg = _num(_fmt(p, game_format).get("bat_avg"))
        mean = _bat_mean(bat_avg, game_format, pitch)
        # exponential-ish score with a small duck hazard
        if random.random() < 0.07:
            runs = 0
        else:
            runs = int(random.expovariate(1.0 / max(mean, 3.0)))
        # limited-overs: later batters face fewer balls
        if game_format != "Test":
            runs = int(runs * (1.0 - 0.04 * i))
            runs = max(runs, 0)

        balls = _balls_faced(runs, game_format)
        # overs consumed by this batter's stay
        overs_used += balls / 6.0
        if max_overs is not None and overs_used > max_overs:
            # trim final partial contribution to fit the overs limit
            overspill = overs_used - max_overs
            balls = max(1, int(balls - overspill * 6))
            runs = min(runs, int(balls * rr / 6.0) + 2)
            overs_used = max_overs

        total += runs
        out = True

        # chase completion check
        if target is not None and total >= target:
            total = total  # keep
            out = False
            chase_done = True
            batting.append(_bat_line(p, runs, balls, out))
            break

        # not-out for the last standing batter when innings ends on overs (LO)
        batting.append(_bat_line(p, runs, balls, out))
        wickets += 1

        if max_overs is not None and overs_used >= max_overs:
            wickets -= 1  # the overs ran out; last batter not dismissed
            batting[-1]["out"] = False
            break

    # If we exited because everyone is out, the genuine last man is not out
    if not chase_done and wickets >= 10 and batting:
        # 10 dismissals means 11th is not out (already appended as out if loop added)
        pass

    overs_used = round(min(overs_used, max_overs) if max_overs else overs_used, 1)
    bowlers, wkt_tally = _assign_wickets(bowling_team, game_format, pitch, wickets, innings_index)
    bowling = _bowling_card(bowlers, wkt_tally, total, overs_used, game_format)

    return {
        "batting_team": None,  # filled by caller
        "bowling_team": None,
        "total": total,
        "wickets": wickets,
        "overs": overs_used,
        "declared": False,
        "chase_done": chase_done,
        "batting": batting,
        "bowling": bowling,
    }


def _balls_faced(runs, game_format):
    if game_format == "Test":
        sr = random.uniform(45, 65)
    elif game_format == "ODI":
        sr = random.uniform(75, 105)
    else:
        sr = random.uniform(115, 165)
    return max(1, int(runs / (sr / 100.0)) + random.randint(0, 6))


def _bat_line(p, runs, balls, out):
    return {"name": p["name"], "runs": runs, "balls": balls, "out": out}


def _bowling_card(bowlers, wkt_tally, total, overs, game_format):
    # distribute overs and conceded runs across bowlers who took wickets + a few others
    active = bowlers[: min(len(bowlers), 6 if game_format == "Test" else 5)]
    n = max(len(active), 1)
    card = []
    runs_left = int(total * random.uniform(0.85, 1.0))
    overs_left = overs
    for i, p in enumerate(active):
        share = 1.0 / n
        ov = round(overs * share * random.uniform(0.7, 1.3), 1)
        ov = min(ov, max(overs_left, 0))
        overs_left -= ov
        conceded = int(runs_left * share * random.uniform(0.7, 1.3))
        wk = wkt_tally.get(id(p), 0)
        card.append({"name": p["name"], "overs": ov, "runs": max(conceded, 0), "wickets": wk})
    # ensure every wicket-taker appears
    for p in bowlers:
        if wkt_tally.get(id(p), 0) > 0 and not any(c["name"] == p["name"] for c in card):
            card.append({"name": p["name"], "overs": round(overs * 0.15, 1),
                         "runs": int(total * 0.12), "wickets": wkt_tally[id(p)]})
    card.sort(key=lambda c: c["wickets"], reverse=True)
    return card


# ---------------------------------------------------------------------------
# Match assembly
# ---------------------------------------------------------------------------

def _toss(team1_name, team2_name, game_format, pitch):
    winner = random.choice([team1_name, team2_name])
    # bowl-first bias on seamer/overcast decks, bat-first on flat tracks
    bowl_bias = 0.5
    if pitch.get("pace", 1) > 1.2:
        bowl_bias = 0.62
    if pitch.get("bat", 1) > 1.1:
        bowl_bias = 0.4
    decision = "bowl" if random.random() < bowl_bias else "bat"
    return winner, decision


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
        winner = second[1]
        margin = f"{10 - inn2['wickets']} wickets"
    elif inn2["total"] == inn1["total"]:
        winner, margin = None, "a tie"
    else:
        winner = first[1]
        margin = f"{inn1['total'] - inn2['total']} runs"

    innings = [inn1, inn2]
    result_text = f"{winner} won by {margin}" if winner else "Match tied"
    potm = compute_potm(innings, winner)
    return {
        "format": game_format, "venue": venue, "pitch": pitch,
        "toss": f"{toss_winner} won the toss and elected to {decision}",
        "innings": innings, "winner": winner, "margin": margin,
        "result_text": result_text, "potm": potm,
    }


def simulate_test(team1, team2, team1_name, team2_name, venue):
    pitch = get_pitch(venue)
    toss_winner, decision = _toss(team1_name, team2_name, "Test", pitch)
    if (toss_winner == team1_name) == (decision == "bat"):
        A, An, B, Bn = team1, team1_name, team2, team2_name
    else:
        A, An, B, Bn = team2, team2_name, team1, team1_name

    OVERS_TOTAL = 450  # 5 days * ~90
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
            winner = None  # ran out of time before a 4th innings of note
        else:
            inn4 = play(B, A, Bn, An, 3, target=target)
            innings.append(inn4)
            winner, margin = _test_chase_result(Bn, An, inn4, target, used[0], OVERS_TOTAL)

    result_text = f"{winner} won by {margin}" if winner else "Match drawn"
    potm = compute_potm(innings, winner)
    days = _map_to_days(innings)
    return {
        "format": "Test", "venue": venue, "pitch": pitch,
        "toss": f"{toss_winner} won the toss and elected to {decision}",
        "innings": innings, "winner": winner, "margin": margin,
        "result_text": result_text, "potm": potm, "days": days,
    }


def _test_chase_result(chasing_name, defending_name, inn4, target, overs_used, overs_total):
    if inn4["chase_done"]:
        return chasing_name, f"{10 - inn4['wickets']} wickets"
    if overs_used >= overs_total:
        return None, None  # time ran out -> draw
    if inn4["wickets"] >= 10:
        return defending_name, f"{target - 1 - inn4['total']} runs"
    return None, None  # survived / drawn


def _map_to_days(innings):
    """Slice the innings timeline into ~90-over days for day-by-day reveal."""
    PER_DAY = 90.0
    timeline = []
    for idx, inn in enumerate(innings):
        timeline.append((idx, inn["overs"]))
    days = []
    day_num = 1
    cur_overs = 0.0
    cur_innings = set()
    boundary = PER_DAY
    running = 0.0
    for idx, ov in timeline:
        running += ov
        cur_innings.add(idx)
        while running >= boundary and day_num < 5:
            days.append({"day": day_num, "through_overs": round(boundary, 0),
                         "innings_in_play": sorted(cur_innings)})
            day_num += 1
            boundary += PER_DAY
            cur_innings = {idx}
    days.append({"day": day_num, "through_overs": round(running, 0),
                 "innings_in_play": sorted(cur_innings)})
    # cap at 5 days
    return days[:5]


# ---------------------------------------------------------------------------
# Player of the Match / Series  (Fix 2 — computed, not invented)
# ---------------------------------------------------------------------------

def _impact(runs, wkts):
    return runs + 22 * wkts


def compute_potm(innings, winner):
    agg = {}   # name -> [runs, wkts, team]
    for inn in innings:
        for b in inn["batting"]:
            e = agg.setdefault(b["name"], [0, 0, inn["batting_team"]])
            e[0] += b["runs"]
        for bo in inn["bowling"]:
            e = agg.setdefault(bo["name"], [0, 0, inn["bowling_team"]])
            e[1] += bo["wickets"]
    best, best_score = None, -1
    for name, (runs, wkts, team) in agg.items():
        score = _impact(runs, wkts)
        if winner and team == winner:
            score *= 1.25
        if score > best_score:
            best, best_score = name, score
            best_stat = (runs, wkts)
    if not best:
        return None
    runs, wkts = best_stat
    bits = []
    if runs:
        bits.append(f"{runs} runs")
    if wkts:
        bits.append(f"{wkts} wickets")
    return {"name": best, "reason": " & ".join(bits) or "all-round contribution"}


def test_day_cards(match):
    """Slice a finished Test into up to 5 day cards for the day-by-day reveal.

    Innings totals/overs are interpolated across ~90-over days so each card has a
    believable stumps score and the performers who were active that day.
    """
    innings = match["innings"]
    starts, t = [], 0.0
    for inn in innings:
        starts.append(t)
        t += inn["overs"]
    match_end = t
    PER_DAY = 90.0

    # per-innings dismissal fall-overs (absolute), evenly spaced
    falls = []  # list per innings of [(fall_over_abs, batline), ...]
    for idx, inn in enumerate(innings):
        dism = [b for b in inn["batting"] if b["out"]]
        n = max(len(dism), 1)
        fl = []
        for k, b in enumerate(dism):
            fo = starts[idx] + inn["overs"] * (k + 0.7) / n
            fl.append((fo, b))
        falls.append(fl)

    def innings_state_at(idx, day_end):
        inn = innings[idx]
        s, e = starts[idx], starts[idx] + inn["overs"]
        team = inn["batting_team"]
        if day_end >= e - 0.01:  # innings complete by now
            if inn["wickets"] >= 10:
                return f"{team} {inn['total']} all out"
            if inn.get("chase_done"):
                return f"{team} {inn['total']}/{inn['wickets']}"
            return f"{team} {inn['total']}/{inn['wickets']} (declared)"
        # in progress
        frac = max(0.0, min(1.0, (day_end - s) / max(inn["overs"], 0.1)))
        runs = int(round(inn["total"] * frac))
        wk = sum(1 for fo, _ in falls[idx] if fo <= day_end)
        ov = round(day_end - s, 1)
        return f"{team} {runs}/{wk} ({ov} ov)"

    cards = []
    for d in range(1, 6):
        day_start, day_end = (d - 1) * PER_DAY, d * PER_DAY
        if day_start >= match_end:
            break
        day_end = min(day_end, match_end)
        in_play = [idx for idx, inn in enumerate(innings)
                   if starts[idx] < day_end - 0.01 and starts[idx] + inn["overs"] > day_start + 0.01]
        states = [innings_state_at(idx, day_end) for idx in in_play]

        # performers active in this day window
        bat_today, bowl_today = {}, {}
        for idx in in_play:
            inn = innings[idx]
            for fo, b in falls[idx]:
                if day_start < fo <= day_end + 0.01:
                    bat_today[b["name"]] = bat_today.get(b["name"], 0) + b["runs"]
            # credit bowlers proportionally to wickets falling in window
            window_w = sum(1 for fo, _ in falls[idx] if day_start < fo <= day_end + 0.01)
            tot_w = max(len([1 for fo, _ in falls[idx]]), 1)
            for bo in inn["bowling"]:
                if bo["wickets"]:
                    share = bo["wickets"] * window_w / tot_w
                    if share >= 0.5:
                        bowl_today[bo["name"]] = bowl_today.get(bo["name"], 0) + int(round(share))
        cards.append({
            "day": d,
            "stumps": states,
            "top_bat": sorted(bat_today.items(), key=lambda x: -x[1])[:2],
            "top_bowl": sorted(bowl_today.items(), key=lambda x: -x[1])[:2],
            "is_last": day_end >= match_end - 0.01,
        })
    if cards:
        cards[-1]["is_last"] = True
    return cards


def aggregate_series(team1_name, team2_name, match_results):
    wins = {team1_name: 0, team2_name: 0}
    draws = 0
    agg = {}  # name -> [runs, wkts, team]
    for m in match_results:
        w = m.get("winner")
        if w in wins:
            wins[w] += 1
        else:
            draws += 1
        for inn in m["innings"]:
            for b in inn["batting"]:
                agg.setdefault(b["name"], [0, 0, inn["batting_team"]])[0] += b["runs"]
            for bo in inn["bowling"]:
                agg.setdefault(bo["name"], [0, 0, inn["bowling_team"]])[1] += bo["wickets"]
    if wins[team1_name] > wins[team2_name]:
        series_winner = team1_name
    elif wins[team2_name] > wins[team1_name]:
        series_winner = team2_name
    else:
        series_winner = None
    pos, pos_score = None, -1
    for name, (runs, wkts, team) in agg.items():
        s = _impact(runs, wkts)
        if s > pos_score:
            pos, pos_score, pos_stat = name, s, (runs, wkts)
    score_line = f"{wins[team1_name]}-{wins[team2_name]}" + (f" ({draws} drawn)" if draws else "")
    return {
        "wins": wins, "draws": draws, "series_winner": series_winner,
        "score_line": score_line,
        "player_of_series": {"name": pos, "runs": pos_stat[0], "wickets": pos_stat[1]} if pos else None,
        "totals": agg,
    }
