import json
import re
from llm_client import chat


def generate_prompt(game_format):
    system = """You are a cricket fantasy game host. Generate a single fun constraint/prompt for a cricket fantasy draft game.

Rules for the constraint:
1. RECALLABLE — based on things cricket fans actually remember: country, role, batting/bowling hand, career milestones, averages, memorable achievements. Do NOT use obscure stats like strike rate, economy rate, dot ball percentage.
2. PLAYFUL — make players think and have fun. The constraint should spark debates and tough choices.
3. FEASIBLE — at least 50+ international cricketers should qualify, enough for multiple teams of 11 with real choices. Avoid overly restrictive thresholds that only a handful of players meet.
4. TENSION — the constraint should force interesting trade-offs or flip normal drafting logic. Don't just filter for "good players who are X" — make people rethink what makes a good pick.

The constraint can use AND or OR conditions.

CONSTRAINT ARCHETYPES (vary between these):
- Inverted/underdog: flip the usual logic — e.g. "bowlers with bowling average ABOVE 30 OR batsmen with batting average BELOW 35" forces picking the 'best of the rest'
- Venue/opposition-specific: achievements in or against a specific country — e.g. "players who have scored a century or taken a 5-wicket haul in England"
- Role-bending: force batsmen to justify their bowling or bowlers their batting — e.g. "every player must have at least 1 wicket AND at least 100 runs"
- Region + role combos: combine geography with role constraints — e.g. "spin bowlers from outside Asia OR pace bowlers from the subcontinent"
- Era-specific: target a specific era — e.g. "players who debuted between 2000 and 2015"
- Standard filters are OK too but keep them interesting: country exclusions, handedness, stat thresholds with OR conditions

GOOD examples:
- "Only select players who have scored a century or taken a 5-wicket haul in Australia"
- "Only select bowlers with bowling average above 30 OR batsmen with batting average below 35"
- "Only select players NOT from India, Australia, or England"
- "Only select left-handed batsmen OR left-arm bowlers"
- "Every player must have at least 1 international wicket AND at least 100 international runs"
- "Only select pace bowlers from Asia OR spin bowlers from outside Asia"

BAD examples (avoid these):
- "Only select players who have scored a Test double century" (too few qualify, under 50 players)
- "Only select batsmen with batting average above 50" (too restrictive)
- "Only select players with economy rate below 4.5" (obscure stat)
- "Only select players who have scored at least 5 centuries" (too plain — no tension, just a stat floor)
- "Only select players who have played 50+ matches" (boring filter, no interesting choices)"""

    result = chat(
        messages=[
            {
                "role": "user",
                "content": f'Generate one fun, creative constraint for a {game_format} cricket fantasy draft. It should create interesting tension and tough choices, not just be a simple stat filter.\n\nIMPORTANT: Reply with ONLY the constraint itself — a single sentence starting with "Only select" or "Every player must". No brainstorming, no explanation, no alternatives. Just the one constraint.',
            }
        ],
        system=system,
        max_tokens=200,
    )
    return _extract_constraint(result)


def _extract_constraint(text):
    text = text.strip()
    for line in text.split("\n"):
        line = line.strip().strip('"').strip("'").strip("*")
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        if line.lower().startswith(("only select", "every player")):
            return line
    for line in text.split("\n"):
        line = line.strip().strip('"').strip("'").strip("*")
        if "select" in line.lower() and ("player" in line.lower() or "bowler" in line.lower() or "batsmen" in line.lower()):
            return line
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return lines[-1].strip('"').strip("'") if lines else text


def validate_player_against_constraint(player_data, constraint, game_format):
    player_info = json.dumps(player_data, indent=2)

    result = chat(
        messages=[
            {
                "role": "user",
                "content": f"""Does this player meet the constraint for a {game_format} game?

Constraint: {constraint}

Player data:
{player_info}

Reply with exactly one of:
- "VALID: <brief reason>"
- "INVALID: <brief reason>"
""",
            }
        ],
        system="You are a cricket expert validator. Given a player's stats and a constraint, determine if the player meets the constraint. Be accurate and fair.",
        max_tokens=150,
    )

    for line in result.strip().splitlines():
        line = line.strip()
        if line.upper().startswith("VALID") or line.upper().startswith("INVALID"):
            is_valid = line.upper().startswith("VALID")
            reason = re.sub(r"^(VALID|INVALID):\s*", "", line, flags=re.IGNORECASE)
            return is_valid, reason
    is_valid = "VALID" in result.upper().split("INVALID")[0] if "INVALID" not in result.upper() else False
    reason = result.strip().splitlines()[-1] if result.strip() else ""
    reason = re.sub(r"^(VALID|INVALID):\s*", "", reason, flags=re.IGNORECASE)
    return is_valid, reason


def _extract_final_answer(text):
    import re
    quoted = re.findall(r'"([^"]{15,})"', text)
    if quoted:
        return quoted[-1]
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if lines:
        last = lines[-1].strip('"').strip()
        if len(last) > 10:
            return last
    return text.strip().strip('"')[:200]


def generate_hint(constraint, picked_players, game_format):
    picked_names = [p["name"] for p in picked_players]

    result = chat(
        messages=[
            {
                "role": "user",
                "content": f"""Give a hint for a {game_format} player who fits this constraint:
"{constraint}"

These players are already picked (don't hint at them): {', '.join(picked_names) if picked_names else 'None yet'}

Give ONE short, fun clue. Example: "Think of a Sri Lankan spinner who bamboozled batsmen for two decades"
Do NOT name the player. Reply with ONLY the clue, nothing else.""",
            }
        ],
        system="You are a cricket fantasy game host. Give ONLY a one-sentence hint, no explanation or reasoning.",
        max_tokens=150,
    )
    return _extract_final_answer(result)
