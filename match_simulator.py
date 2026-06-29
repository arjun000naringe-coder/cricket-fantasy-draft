import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from llm_client import chat, HEAVY_MODEL
import cricket_engine_v2 as engine  # rehashed engine: regression, over-budget, coupling

SIM_MODEL = "gemma4:31b"

VENUES = {
    "India": ["Wankhede Stadium, Mumbai", "Eden Gardens, Kolkata", "M. Chinnaswamy Stadium, Bangalore", "MA Chidambaram Stadium, Chennai", "Narendra Modi Stadium, Ahmedabad"],
    "Australia": ["Melbourne Cricket Ground", "Sydney Cricket Ground", "The Gabba, Brisbane", "Adelaide Oval", "WACA Ground, Perth"],
    "England": ["Lord's, London", "The Oval, London", "Old Trafford, Manchester", "Edgbaston, Birmingham", "Headingley, Leeds"],
    "South Africa": ["Newlands, Cape Town", "The Wanderers, Johannesburg", "SuperSport Park, Centurion", "Kingsmead, Durban"],
    "Pakistan": ["National Stadium, Karachi", "Gaddafi Stadium, Lahore", "Rawalpindi Cricket Stadium"],
    "Sri Lanka": ["R. Premadasa Stadium, Colombo", "Galle International Stadium", "Pallekele International Cricket Stadium"],
    "West Indies": ["Kensington Oval, Barbados", "Sabina Park, Jamaica", "Queen's Park Oval, Trinidad"],
    "New Zealand": ["Basin Reserve, Wellington", "Hagley Oval, Christchurch", "Eden Park, Auckland"],
    "Bangladesh": ["Sher-e-Bangla Stadium, Dhaka", "Zahur Ahmed Chowdhury Stadium, Chittagong"],
    "UAE": ["Dubai International Cricket Stadium", "Sheikh Zayed Stadium, Abu Dhabi", "Sharjah Cricket Stadium"],
}

SYSTEM_PROMPT = "You are a cricket match simulator and commentator. Simulate realistic cricket matches based on player career statistics. Be accurate with cricket rules and scoring. Make the narrative engaging and dramatic."


def pick_venue(country):
    if country.lower() == "worldwide":
        country = random.choice(list(VENUES.keys()))
    venues = VENUES.get(country, VENUES.get("India"))
    return random.choice(venues)


def format_team_for_prompt(team, game_format):
    lines = []
    for p in team:
        fmt_stats = p.get("formats", {}).get(game_format, {})
        line = f"- {p['name']} ({p.get('country', '?')}, {p.get('role', '?')}, {p.get('bat_hand', '?')}-hand bat)"
        if fmt_stats:
            line += f" | Matches: {fmt_stats.get('matches', '?')}, Runs: {fmt_stats.get('runs', '?')}, Avg: {fmt_stats.get('bat_avg', '?')}, 100s: {fmt_stats.get('hundreds', '?')}, Wkts: {fmt_stats.get('wickets', '?')}, Bowl Avg: {fmt_stats.get('bowl_avg', '?')}"
        else:
            line += " | Stats not available — use your cricket knowledge"
        lines.append(line)
    return "\n".join(lines)


def _teams_block(team1, team2, team1_name, team2_name, game_format):
    return f"""TEAM: {team1_name}
{format_team_for_prompt(team1, game_format)}

TEAM: {team2_name}
{format_team_for_prompt(team2, game_format)}"""


def _print_segment(text):
    print(text)
    print()
    input("  [Press Enter to continue...]")


# ---------------------------------------------------------------------------
# Limited-overs (ODI / T20I) — innings by innings
# ---------------------------------------------------------------------------

def _simulate_limited_overs(team1, team2, team1_name, team2_name, venue, game_format, match_number=None):
    match_label = f"Match {match_number}" if match_number else "Match"
    overs = "50" if game_format == "ODI" else "20"
    fmt_long = "One Day International (50 overs per side)" if game_format == "ODI" else "T20 International (20 overs per side)"
    teams_block = _teams_block(team1, team2, team1_name, team2_name, game_format)

    # --- Step 1: Toss + first innings ---
    prompt_1 = f"""Simulate the toss and FIRST INNINGS ONLY of a {fmt_long} cricket match.

{match_label} at {venue}
Conditions: Consider the typical pitch and weather conditions at this ground.

{teams_block}

Simulate realistically based on career statistics with natural variance.

Provide ONLY the toss and first innings in this EXACT format:

TOSS: <team> won the toss and elected to <bat/bowl>

FIRST INNINGS: <team name> — <total>/<wickets> in <overs> overs
Top scorers:
- <Player>: <runs> (<balls>) [<4s> fours, <6s> sixes]
- <Player>: <runs> (<balls>) [<4s> fours, <6s> sixes]
- <Player>: <runs> (<balls>) [<4s> fours, <6s> sixes]
Key bowlers:
- <Player>: <wickets>/<runs> (<overs> overs)
- <Player>: <wickets>/<runs> (<overs> overs)

INNINGS NARRATIVE:
<1 paragraph describing the key moments of the first innings — batting highlights, bowling spells, turning points, momentum shifts>

Do NOT simulate the second innings yet. Stop after the first innings narrative."""

    first_innings = chat(
        messages=[{"role": "user", "content": prompt_1}],
        system=SYSTEM_PROMPT,
        max_tokens=800,
        model=SIM_MODEL,
    )

    _print_segment(first_innings)

    # --- Step 2: Second innings + result ---
    prompt_2 = f"""Continue the match. Here is what happened in the first innings:

{first_innings}

Now simulate the SECOND INNINGS and provide the match result.

{teams_block}

Provide the second innings and result in this EXACT format:

SECOND INNINGS: <team name> — <total>/<wickets> in <overs> overs
Top scorers:
- <Player>: <runs> (<balls>) [<4s> fours, <6s> sixes]
- <Player>: <runs> (<balls>) [<4s> fours, <6s> sixes]
- <Player>: <runs> (<balls>) [<4s> fours, <6s> sixes]
Key bowlers:
- <Player>: <wickets>/<runs> (<overs> overs)
- <Player>: <wickets>/<runs> (<overs> overs)

INNINGS NARRATIVE:
<1 paragraph describing the chase/defense — pressure moments, key wickets, match-winning performances>

RESULT: <team name> won by <margin>
PLAYER OF THE MATCH: <Player Name> (<brief reason>)"""

    second_innings = chat(
        messages=[
            {"role": "user", "content": prompt_1},
            {"role": "assistant", "content": first_innings},
            {"role": "user", "content": prompt_2},
        ],
        system=SYSTEM_PROMPT,
        max_tokens=800,
        model=SIM_MODEL,
    )

    print(second_innings)

    return {
        "venue": venue,
        "match_number": match_number,
        "result_text": first_innings + "\n\n" + second_innings,
    }


# ---------------------------------------------------------------------------
# Test match — day by day
# ---------------------------------------------------------------------------

def _simulate_test(team1, team2, team1_name, team2_name, venue, match_number=None):
    match_label = f"Match {match_number}" if match_number else "Match"
    teams_block = _teams_block(team1, team2, team1_name, team2_name, "Test")

    messages = []
    day_texts = []

    # --- Day 1 ---
    prompt_day1 = f"""Simulate DAY 1 ONLY of a Test match (5 days, 2 innings per side).

{match_label} at {venue}
Conditions: Consider the typical pitch and weather conditions at this ground.

{teams_block}

Simulate realistically based on career statistics with natural variance. Roughly 90 overs are bowled each day.

Provide Day 1 in this EXACT format:

TOSS: <team> won the toss and elected to <bat/bowl>

DAY 1 SUMMARY:
<team name> — <score>/<wickets> at stumps (or if innings ended, show the completed innings and any progress in next innings)

Key performers:
- <Player>: <runs> (<balls>) or <wickets>/<runs> (<overs> overs)
- <Player>: <runs> (<balls>) or <wickets>/<runs> (<overs> overs)
- <Player>: <runs> (<balls>) or <wickets>/<runs> (<overs> overs)

DAY 1 NARRATIVE:
<1-2 paragraphs of engaging commentary describing the day's play — sessions, momentum, turning points, atmosphere>

MATCH STATE: <concise state — e.g. "Australia 287/4 at stumps, Smith 142* and Head 38*" or "India 310 all out, England 45/1 at stumps">

Do NOT simulate beyond Day 1."""

    messages.append({"role": "user", "content": prompt_day1})

    day1_text = chat(
        messages=messages,
        system=SYSTEM_PROMPT,
        max_tokens=800,
        model=SIM_MODEL,
    )

    day_texts.append(day1_text)
    messages.append({"role": "assistant", "content": day1_text})
    _print_segment(day1_text)

    # --- Days 2-5 ---
    for day_num in range(2, 6):
        prompt_day = f"""Continue the Test match. Simulate DAY {day_num} ONLY.

Pick up exactly where the previous day ended. Roughly 90 overs are bowled each day. Remember this is a 2-innings-per-side match.

Provide Day {day_num} in this EXACT format:

DAY {day_num} SUMMARY:
<current batting team> — <score>/<wickets> (and any completed innings)

Key performers today:
- <Player>: <runs> (<balls>) or <wickets>/<runs> (<overs> overs)
- <Player>: <runs> (<balls>) or <wickets>/<runs> (<overs> overs)

DAY {day_num} NARRATIVE:
<1-2 paragraphs of engaging commentary for today's play>

MATCH STATE: <concise current state — all innings scores and current position>

{"If the match concludes today, add:" if day_num >= 3 else ""}
{"RESULT: <team name> won by <margin> (or match drawn)" if day_num >= 3 else ""}
{"PLAYER OF THE MATCH: <Player Name> (<brief reason>)" if day_num >= 3 else ""}

{"If the match is not yet decided, do NOT declare a result." if day_num < 5 else "The match MUST conclude today — if no outright result, declare a draw."}

Do NOT simulate beyond Day {day_num}."""

        messages.append({"role": "user", "content": prompt_day})

        day_text = chat(
            messages=messages,
            system=SYSTEM_PROMPT,
            max_tokens=800,
            model=SIM_MODEL,
        )

        day_texts.append(day_text)
        messages.append({"role": "assistant", "content": day_text})

        match_over = "RESULT:" in day_text

        if match_over or day_num == 5:
            print(day_text)
        else:
            _print_segment(day_text)

        if match_over:
            break

    full_text = "\n\n".join(day_texts)
    return {
        "venue": venue,
        "match_number": match_number,
        "result_text": full_text,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def simulate_match(team1, team2, team1_name, team2_name, venue_country, game_format, match_number=None):
    venue = pick_venue(venue_country)

    print(f"\n{'─' * 50}")
    print(f"  Match {match_number or ''} — {venue}")
    print(f"  {team1_name} vs {team2_name}")
    print(f"{'─' * 50}\n")

    if game_format == "Test":
        return _simulate_test(team1, team2, team1_name, team2_name, venue, match_number)
    else:
        return _simulate_limited_overs(team1, team2, team1_name, team2_name, venue, game_format, match_number)


def _clean_for_web(text):
    import re
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    text = text.replace("---", "")
    return text.strip()


# ===========================================================================
# Engine-driven narration (authoritative engine decides; LLM only narrates)
# ===========================================================================

def _render_bat_top(inn, n=3):
    rows = sorted(inn["batting"], key=lambda b: b["runs"], reverse=True)[:n]
    return ", ".join(f"{b['name']} {b['runs']}{'' if b['out'] else '*'} ({b['balls']})" for b in rows)


def _render_bowl_top(inn, n=2):
    rows = [b for b in inn["bowling"] if b["wickets"] > 0][:n]
    if not rows:
        rows = inn["bowling"][:1]
    return ", ".join(f"{b['name']} {b['wickets']}/{b['runs']} ({b['overs']} ov)" for b in rows)


def _match_summary_text(m):
    txt = f"RESULT: {m['result_text']}"
    if m.get("potm"):
        txt += f"\nPLAYER OF THE MATCH: {m['potm']['name']} ({m['potm']['reason']})"
    return txt


def _lo_segment_facts(m):
    inn1, inn2 = m["innings"][0], m["innings"][1]
    f1 = "\n".join([
        f"TOSS: {m['toss']}",
        f"{inn1['batting_team']} {inn1['total']}/{inn1['wickets']} ({inn1['overs']} overs)",
        f"Top scorers: {_render_bat_top(inn1)}",
        f"Key bowlers: {_render_bowl_top(inn1)}",
    ])
    f2 = "\n".join([
        f"{inn2['batting_team']} {inn2['total']}/{inn2['wickets']} ({inn2['overs']} overs)",
        f"Top scorers: {_render_bat_top(inn2)}",
        f"Key bowlers: {_render_bowl_top(inn2)}",
        "",
        _match_summary_text(m),
    ])
    return [
        {"label": "First Innings", "facts": f1},
        {"label": "Second Innings & Result", "facts": f2},
    ]


def _test_segment_facts(m):
    out = []
    for c in engine.test_day_cards(m):
        lines = []
        if c["day"] == 1:
            lines.append(f"TOSS: {m['toss']}")
        lines.append("At stumps: " + "; ".join(c["stumps"]))
        if c["top_bat"]:
            lines.append("Top batting today: " + ", ".join(f"{n} {r}" for n, r in c["top_bat"]))
        if c["top_bowl"]:
            lines.append("Top bowling today: " + ", ".join(f"{n} {w} wkts" for n, w in c["top_bowl"]))
        if c["is_last"]:
            lines.append("")
            lines.append(_match_summary_text(m))
        out.append({"label": f"Day {c['day']}", "facts": "\n".join(lines)})
    return out


def _segment_facts(m):
    return _test_segment_facts(m) if m["format"] == "Test" else _lo_segment_facts(m)


def _narrate_segment(label, facts, venue, pitch_desc, game_format):
    prompt = f"""You are a cricket commentator narrating the {label} of a {game_format} match at {venue}.
The pitch: {pitch_desc}.

These are the CONFIRMED facts of this {label} — every score, name and result is final. Do not change, contradict, or add to them:
{facts}

Write ONE sentence of vivid commentary for this {label}. Focus on the key turning point or mood of the day. Do NOT restate scores or stats — those are shown separately. No markdown, no headings — return ONLY the single sentence."""
    try:
        return chat(messages=[{"role": "user", "content": prompt}],
                    system=SYSTEM_PROMPT, max_tokens=80, model=SIM_MODEL).strip()
    except Exception:
        return ""


def _narrate_jobs(jobs, max_workers=6):
    """jobs: list of (key, label, facts, venue, pitch_desc, fmt). Returns {key: text}."""
    out = {}
    if not jobs:
        return out
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_narrate_segment, j[1], j[2], j[3], j[4], j[5]): j[0] for j in jobs}
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                out[key] = fut.result()
            except Exception:
                out[key] = ""
    return out


def _serialize_innings(innings_list):
    out = []
    for inn in innings_list:
        out.append({
            "batting_team": inn["batting_team"],
            "bowling_team": inn["bowling_team"],
            "total": inn["total"],
            "wickets": inn["wickets"],
            "overs": inn["overs"],
            "batting": [{"name": b["name"], "runs": b["runs"], "balls": b["balls"], "out": b["out"]}
                        for b in inn["batting"][:5]],
            "bowling": [{"name": b["name"], "wickets": b["wickets"], "runs": b["runs"], "overs": b["overs"]}
                        for b in inn["bowling"][:4]],
        })
    return out


def _build_day_snapshots(m):
    """Build per-day scorecard snapshots + situation text for Test matches."""
    day_cards = engine.test_day_cards(m)
    innings = m["innings"]
    shown_innings = set()
    snapshots = []
    for c in day_cards:
        stumps = c["stumps"]

        show_tables = []
        for idx in c.get("completed", []):
            if idx not in shown_innings:
                shown_innings.add(idx)
                show_tables.append(idx)
        if c["is_last"]:
            for idx in c.get("in_play", []):
                if idx not in shown_innings:
                    shown_innings.add(idx)
                    show_tables.append(idx)

        situation = _compute_situation(stumps, innings, c["is_last"], m)
        snapshots.append({
            "stumps": stumps,
            "show_innings": sorted(show_tables),
            "situation": situation,
        })
    return snapshots


def _compute_situation(stumps, innings, is_last, m):
    """Derive a human-readable match situation from stumps scores."""
    import re

    def parse_score(s):
        pat = re.match(r"(.+?)\s+(\d+)/(\d+)", s)
        if pat:
            return pat.group(1).strip(), int(pat.group(2)), int(pat.group(3)), False
        pat = re.match(r"(.+?)\s+(\d+)\s+all out", s)
        if pat:
            return pat.group(1).strip(), int(pat.group(2)), 10, True
        pat = re.match(r"(.+?)\s+(\d+)/(\d+)\s+\(declared\)", s)
        if pat:
            return pat.group(1).strip(), int(pat.group(2)), int(pat.group(3)), True
        return None, 0, 0, False

    if is_last and m.get("winner"):
        return ""

    scores = [parse_score(s) for s in stumps]
    scores = [s for s in scores if s[0] is not None]

    if len(scores) == 1:
        return f"{scores[0][0]} {scores[0][1]}/{scores[0][2]} at stumps"

    if len(scores) == 2:
        t1, r1 = scores[0][0], scores[0][1]
        t2, r2, w2 = scores[1][0], scores[1][1], scores[1][2]
        diff = r1 - r2
        if diff > 0:
            return f"{t2} trails by {diff} runs with {10 - w2} wickets remaining"
        elif diff < 0:
            return f"{t2} leads by {-diff} runs with {10 - w2} wickets remaining"
        else:
            return f"Scores level — {t2} {10 - w2} wickets in hand"

    if len(scores) == 3:
        t1_r, t2_r = scores[0][1], scores[1][1]
        t3, r3, w3 = scores[2][0], scores[2][1], scores[2][2]
        lead = t1_r - t2_r + r3
        return f"{t3} leads by {lead} runs with {10 - w3} wickets remaining"

    if len(scores) == 4:
        t1_r, t2_r = scores[0][1], scores[1][1]
        t3_r = scores[2][1]
        t4, r4, w4 = scores[3][0], scores[3][1], scores[3][2]
        target = t1_r - t2_r + t3_r + 1
        needed = target - r4
        if needed > 0:
            return f"{t4} needs {needed} more runs to win with {10 - w4} wickets remaining"
        else:
            return ""

    return ""


def _assemble_match(m, venue, match_number, segment_facts, narrations, key_prefix=None):
    is_test = m.get("format") == "Test"
    day_snapshots = _build_day_snapshots(m) if is_test else []

    segs = []
    for si, seg in enumerate(segment_facts):
        key = (key_prefix, si) if key_prefix is not None else si
        narrative = narrations.get(key, "")
        seg_data = {"label": seg["label"], "narrative": _clean_for_web(narrative) if narrative else ""}
        if is_test and si < len(day_snapshots):
            seg_data["snapshot"] = day_snapshots[si]
        segs.append(seg_data)
    potm = m.get("potm")
    return {
        "venue": venue,
        "match_number": match_number,
        "segments": segs,
        "result_line": m["result_text"],
        "match_summary": _match_summary_text(m),
        "toss": m.get("toss", ""),
        "pitch_desc": m.get("pitch", {}).get("desc", ""),
        "innings": _serialize_innings(m.get("innings", [])),
        "winner": m.get("winner"),
        "margin": m.get("margin", ""),
        "potm": {"name": potm["name"], "reason": potm["reason"]} if potm else None,
        "format": m.get("format", ""),
    }


def _simulate_limited_overs_web(team1, team2, team1_name, team2_name, venue, game_format, match_number=None):
    m = engine.simulate_limited_overs(team1, team2, team1_name, team2_name, venue, game_format)
    facts = _segment_facts(m)
    jobs = [(si, s["label"], s["facts"], venue, m["pitch"]["desc"], game_format)
            for si, s in enumerate(facts)]
    narr = _narrate_jobs(jobs)
    return _assemble_match(m, venue, match_number, facts, narr)


def _simulate_test_web(team1, team2, team1_name, team2_name, venue, match_number=None):
    m = engine.simulate_test(team1, team2, team1_name, team2_name, venue)
    facts = _segment_facts(m)
    jobs = [(si, s["label"], s["facts"], venue, m["pitch"]["desc"], "Test")
            for si, s in enumerate(facts)]
    narr = _narrate_jobs(jobs)
    return _assemble_match(m, venue, match_number, facts, narr)


def simulate_series_web(team1, team2, team1_name, team2_name, venue_country, game_format, num_matches):
    # 1) Run the authoritative engine for every match (instant, in code).
    eng_matches = []      # (match_struct, venue, match_number)
    facts_all = []        # per-match list of {label, facts}
    for i in range(1, num_matches + 1):
        venue = pick_venue(venue_country)
        if game_format == "Test":
            m = engine.simulate_test(team1, team2, team1_name, team2_name, venue)
        else:
            m = engine.simulate_limited_overs(team1, team2, team1_name, team2_name, venue, game_format)
        eng_matches.append((m, venue, i if num_matches > 1 else None))
        facts_all.append(_segment_facts(m))

    # 2) Narrate every segment across every match in one parallel pass —
    #    facts are fixed by the engine, so there is no sequential dependency.
    jobs = []
    for mi, (m, venue, _) in enumerate(eng_matches):
        for si, seg in enumerate(facts_all[mi]):
            jobs.append(((mi, si), seg["label"], seg["facts"], venue, m["pitch"]["desc"], game_format))
    narrations = _narrate_jobs(jobs)

    # 3) Assemble each match.
    matches = []
    for mi, (m, venue, num) in enumerate(eng_matches):
        matches.append(_assemble_match(m, venue, num, facts_all[mi], narrations, key_prefix=mi))

    # 4) Series summary (Fix 2): result + Player of the Series computed in code,
    #    LLM only writes the prose over the real aggregated standings.
    series_summary = None
    if num_matches > 1:
        agg = engine.aggregate_series(team1_name, team2_name, [m for m, _, _ in eng_matches])
        series_summary = _build_series_summary(agg, team1_name, team2_name, game_format, num_matches)

    return {"matches": matches, "series_summary": series_summary}


def _build_series_summary(agg, team1_name, team2_name, game_format, num_matches):
    winner = agg["series_winner"]
    header = (f"SERIES RESULT: {winner} won the series {agg['score_line']}"
              if winner else f"SERIES RESULT: Series drawn {agg['score_line']}")
    pos = agg.get("player_of_series")
    pos_line = ""
    if pos:
        bits = []
        if pos["runs"]:
            bits.append(f"{pos['runs']} runs")
        if pos["wickets"]:
            bits.append(f"{pos['wickets']} wickets")
        pos_line = f"PLAYER OF THE SERIES: {pos['name']} ({', '.join(bits)} across {num_matches} matches)"

    prompt = f"""Write a 2-3 sentence summary of a {num_matches}-match {game_format} series between {team1_name} and {team2_name}.
Confirmed outcome — do not contradict: {header}. {pos_line}
Match wins — {team1_name}: {agg['wins'].get(team1_name, 0)}, {team2_name}: {agg['wins'].get(team2_name, 0)}, draws: {agg['draws']}.
No markdown, no headings. Return ONLY the prose summary."""
    try:
        prose = chat(messages=[{"role": "user", "content": prompt}],
                     system=SYSTEM_PROMPT, max_tokens=220, model=SIM_MODEL).strip()
    except Exception:
        prose = ""
    return _clean_for_web("\n".join(x for x in [header, pos_line, prose] if x))


def simulate_series(team1, team2, team1_name, team2_name, venue_country, game_format, num_matches):
    """CLI entry point — uses the authoritative engine and prints each match."""
    print(f"\n  Simulating {num_matches} match(es)...\n")
    result = simulate_series_web(
        team1, team2, team1_name, team2_name, venue_country, game_format, num_matches
    )
    for m in result["matches"]:
        label = f"Match {m['match_number']}" if m.get("match_number") else "Match"
        print(f"\n{'─' * 50}\n  {label} — {m['venue']}\n{'─' * 50}")
        for seg in m["segments"]:
            print(f"\n  [{seg['label']}]\n{seg['text']}")
        print(f"\n  {m['match_summary']}")
    return result
