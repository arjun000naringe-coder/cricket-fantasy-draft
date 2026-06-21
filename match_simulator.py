import random
from llm_client import chat, HEAVY_MODEL

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


def _simulate_limited_overs_web(team1, team2, team1_name, team2_name, venue, game_format, match_number=None):
    match_label = f"Match {match_number}" if match_number else "Match"
    overs = "50" if game_format == "ODI" else "20"
    fmt_long = "One Day International (50 overs per side)" if game_format == "ODI" else "T20 International (20 overs per side)"
    teams_block = _teams_block(team1, team2, team1_name, team2_name, game_format)

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
Key bowlers:
- <Player>: <wickets>/<runs> (<overs> overs)
- <Player>: <wickets>/<runs> (<overs> overs)

INNINGS NARRATIVE:
<1 paragraph describing the key moments of the first innings>

Do NOT simulate the second innings yet. Do not use markdown formatting."""

    first_innings = chat(
        messages=[{"role": "user", "content": prompt_1}],
        system=SYSTEM_PROMPT,
        max_tokens=800,
        model=SIM_MODEL,
    )

    prompt_2 = f"""Continue the match. Here is what happened in the first innings:

{first_innings}

Now simulate the SECOND INNINGS and provide the match result.

{teams_block}

Provide the second innings and result in this EXACT format:

SECOND INNINGS: <team name> — <total>/<wickets> in <overs> overs
Top scorers:
- <Player>: <runs> (<balls>) [<4s> fours, <6s> sixes]
- <Player>: <runs> (<balls>) [<4s> fours, <6s> sixes]
Key bowlers:
- <Player>: <wickets>/<runs> (<overs> overs)
- <Player>: <wickets>/<runs> (<overs> overs)

INNINGS NARRATIVE:
<1 paragraph describing the chase/defense — pressure moments, key wickets>

RESULT: <team name> won by <margin>
PLAYER OF THE MATCH: <Player Name> (<brief reason>)

Do not use markdown formatting."""

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

    segments = [
        {"label": "First Innings", "text": _clean_for_web(first_innings)},
        {"label": "Second Innings & Result", "text": _clean_for_web(second_innings)},
    ]

    result_line = ""
    for line in second_innings.splitlines():
        if line.strip().upper().startswith("RESULT:"):
            result_line = line.strip()
            break

    return {"venue": venue, "match_number": match_number, "segments": segments, "result_line": result_line}


def _simulate_test_web(team1, team2, team1_name, team2_name, venue, match_number=None):
    match_label = f"Match {match_number}" if match_number else "Match"
    teams_block = _teams_block(team1, team2, team1_name, team2_name, "Test")

    messages = []
    segments = []

    prompt_day1 = f"""Simulate DAY 1 ONLY of a Test match (5 days, 2 innings per side).

{match_label} at {venue}
Conditions: Consider the typical pitch and weather conditions at this ground.

{teams_block}

Simulate realistically based on career statistics with natural variance. Roughly 90 overs are bowled each day.

Provide Day 1 in this EXACT format:

TOSS: <team> won the toss and elected to <bat/bowl>

DAY 1 SUMMARY:
<team name> — <score>/<wickets> at stumps

Key performers:
- <Player>: <runs> (<balls>) or <wickets>/<runs> (<overs> overs)
- <Player>: <runs> (<balls>) or <wickets>/<runs> (<overs> overs)

DAY 1 NARRATIVE:
<1-2 paragraphs of engaging commentary describing the day's play>

MATCH STATE: <concise state at stumps>

Do NOT simulate beyond Day 1. Do not use markdown formatting."""

    messages.append({"role": "user", "content": prompt_day1})
    day1_text = chat(messages=messages, system=SYSTEM_PROMPT, max_tokens=800, model=SIM_MODEL)
    segments.append({"label": "Day 1", "text": _clean_for_web(day1_text)})
    messages.append({"role": "assistant", "content": day1_text})

    result_line = ""
    for day_num in range(2, 6):
        prompt_day = f"""Continue the Test match. Simulate DAY {day_num} ONLY.

Pick up exactly where the previous day ended. Roughly 90 overs are bowled each day.

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

Do NOT simulate beyond Day {day_num}. Do not use markdown formatting."""

        messages.append({"role": "user", "content": prompt_day})
        day_text = chat(messages=messages, system=SYSTEM_PROMPT, max_tokens=800, model=SIM_MODEL)
        segments.append({"label": f"Day {day_num}", "text": _clean_for_web(day_text)})
        messages.append({"role": "assistant", "content": day_text})

        if "RESULT:" in day_text:
            for line in day_text.splitlines():
                if line.strip().upper().startswith("RESULT:"):
                    result_line = line.strip()
                    break
            break

    return {"venue": venue, "match_number": match_number, "segments": segments, "result_line": result_line}


def simulate_series_web(team1, team2, team1_name, team2_name, venue_country, game_format, num_matches):
    matches = []
    for i in range(1, num_matches + 1):
        venue = pick_venue(venue_country)
        if game_format == "Test":
            result = _simulate_test_web(team1, team2, team1_name, team2_name, venue, i if num_matches > 1 else None)
        else:
            result = _simulate_limited_overs_web(team1, team2, team1_name, team2_name, venue, game_format, i if num_matches > 1 else None)
        matches.append(result)

    series_summary = None
    if num_matches > 1:
        all_text = "\n\n".join(m.get("result_line", "") for m in matches if m.get("result_line"))
        try:
            series_summary = chat(
                messages=[{
                    "role": "user",
                    "content": f"Based on these {num_matches} match results between {team1_name} and {team2_name}:\n\n{all_text}\n\nProvide a brief series summary in this format:\nSERIES RESULT: <team> won the series <X>-<Y> (or drawn)\nPLAYER OF THE SERIES: <name> (<brief reason>)\nSERIES SUMMARY: <1 paragraph summary>\n\nDo not use markdown.",
                }],
                max_tokens=300,
                model=SIM_MODEL,
            )
            series_summary = _clean_for_web(series_summary)
        except Exception:
            series_summary = None

    return {"matches": matches, "series_summary": series_summary}


def simulate_series(team1, team2, team1_name, team2_name, venue_country, game_format, num_matches):
    results = []
    for i in range(1, num_matches + 1):
        print(f"\n  Simulating match {i} of {num_matches}...")
        result = simulate_match(
            team1, team2, team1_name, team2_name,
            venue_country, game_format, i
        )
        results.append(result)

    if num_matches > 1:
        all_results_text = "\n\n---\n\n".join(
            [r["result_text"] for r in results]
        )
        series_summary = chat(
            messages=[
                {
                    "role": "user",
                    "content": f"""Based on these {num_matches} match results between {team1_name} and {team2_name}, provide a brief series summary:

{all_results_text}

Format:
SERIES RESULT: <team> won the series <X>-<Y> (or drawn <X>-<X>)
PLAYER OF THE SERIES: <name> (<brief reason>)
SERIES SUMMARY: <1-2 paragraph summary of the series>""",
                }
            ],
            max_tokens=500,
            model=SIM_MODEL,
        )
    else:
        series_summary = None

    return {"matches": results, "series_summary": series_summary}
