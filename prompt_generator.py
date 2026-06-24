import json
import random
import re
from llm_client import chat

# Hints use the same fast, reliable model as match simulation.
HINT_MODEL = "gemma4:31b"

# Name particles that aren't identifying on their own, so they don't count
# as a "leak" if they appear in a clue.
_NAME_STOPWORDS = {"de", "van", "der", "al", "ul", "bin", "del", "da", "di", "le", "la"}


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
    quoted = re.findall(r'"([^"]{15,})"', text)
    if quoted:
        return quoted[-1]
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if lines:
        last = lines[-1].strip('"').strip()
        if len(last) > 10:
            return last
    return text.strip().strip('"')[:200]


# Phrases that signal the model "thinking out loud" instead of giving a clue.
_REASONING_TELLS = (
    "let me", "i like", "i'll", "i will", "finalize", "let's", "here's",
    "here is", "option", "constraint:", "player:", "clue:", "hint:", "okay",
    "sure,", "as an", "i think", "i need", "first,",
)


def _looks_like_reasoning(clue):
    low = clue.lower()
    return any(t in low for t in _REASONING_TELLS)


def _name_tokens(name):
    """Identifying tokens of a name (drops initials and particles like 'de')."""
    toks = re.sub(r"[^a-z ]", " ", name.lower()).split()
    return [t for t in toks if len(t) > 2 and t not in _NAME_STOPWORDS]


def _clue_leaks_name(clue, name):
    low = clue.lower()
    return any(re.search(rf"\b{re.escape(t)}\b", low) for t in _name_tokens(name))


def _candidate_line(p, game_format):
    fmt = p.get("formats", {}).get(game_format, {})
    bits = [f"{fmt.get('matches', 0)}m", f"{fmt.get('runs', 0)}r"]
    if fmt.get("bat_avg"):
        bits.append(f"avg{fmt['bat_avg']}")
    if fmt.get("wickets"):
        bits.append(f"{fmt['wickets']}w")
    if fmt.get("hundreds"):
        bits.append(f"{fmt['hundreds']}x100")
    return f"{p['name']} ({p.get('country', '?')}, {p.get('role', '?')}) — {' '.join(bits)}"


def _fallback_hint(candidates, game_format):
    """Instant, no-LLM safe clue grounded in a real in-pool player."""
    p = random.choice(candidates)
    role = (p.get("role") or "cricketer").lower()
    country = p.get("country") or "the international stage"
    article = "an" if role[:1] in "aeiou" else "a"
    return (f"Think of {article} {role} from {country} who made their mark in {game_format} cricket.",
            p["name"])


def generate_hint(constraint, picked_players, game_format, players_db=None,
                  already_hinted=None):
    """Return (clue, player_name).

    One gemma call, grounded in real players from our DB so the hint always
    points to someone the user can actually pick. We ask the model to reveal
    its chosen player on a hidden line so we can (a) prevent repeats across a
    session and (b) deterministically reject clues that leak the name — both
    with zero extra latency.
    """
    picked_names = {p["name"].lower() for p in picked_players}
    hinted_names = {n.lower() for n in (already_hinted or [])}
    avoid = picked_names | hinted_names

    # Candidate pool: players with stats in this format, not already used.
    pool = [
        p for p in (players_db or [])
        if game_format in p.get("formats", {})
        and p["name"].lower() not in avoid
    ]
    if not pool:
        # Degenerate case (no DB / everyone used): fall back to old behaviour.
        return _legacy_hint(constraint, picked_players, game_format), None

    sample = random.sample(pool, min(45, len(pool)))
    by_name = {p["name"].lower(): p for p in sample}
    listing = "\n".join(_candidate_line(p, game_format) for p in sample)

    user_msg = f"""From the player list below, secretly pick ONE player who clearly satisfies the constraint, then write a single playful one-sentence clue pointing to them.

Format: {game_format}
Constraint: {constraint}

Players (choose ONLY from this list):
{listing}

Rules for the clue:
- Exactly ONE sentence, fun and evocative.
- Do NOT write the player's name or surname.
- Do NOT use a unique nickname, signature celebration, or one-of-a-kind stat that instantly gives them away (no "Haryana Hurricane", "helicopter shot", "sword celebration", exact wicket/run totals).
- Hint through general traits: country, role, playing style, era.

Output EXACTLY two lines and nothing else:
PLAYER: <exact name copied from the list>
CLUE: <the one-sentence clue>"""

    for _ in range(2):  # one retry on a bad/leaky/invalid response
        result = chat(
            messages=[{"role": "user", "content": user_msg}],
            system="You are a cricket fantasy game host. Follow the output format exactly. Never add commentary or reasoning.",
            max_tokens=120,
            model=HINT_MODEL,
        )
        player, clue = _parse_player_clue(result)
        if not clue or _looks_like_reasoning(clue):
            continue
        chosen = by_name.get((player or "").lower())
        if not chosen:
            continue  # picked someone outside the list — reject
        if _clue_leaks_name(clue, chosen["name"]):
            continue  # name leaked — reject and retry
        return clue, chosen["name"]

    # All attempts failed validation — return a safe grounded fallback.
    return _fallback_hint(sample, game_format)


def _parse_player_clue(text):
    player, clue = None, None
    for line in text.strip().splitlines():
        line = line.strip().strip('"').strip("*").strip()
        m = re.match(r"(?i)^player\s*[:\-]\s*(.+)$", line)
        if m:
            player = m.group(1).strip().strip('"')
            continue
        m = re.match(r"(?i)^clue\s*[:\-]\s*(.+)$", line)
        if m:
            clue = m.group(1).strip().strip('"')
    return player, clue


def _legacy_hint(constraint, picked_players, game_format):
    picked_names = [p["name"] for p in picked_players]
    result = chat(
        messages=[{
            "role": "user",
            "content": f"""Give a hint for a {game_format} player who fits this constraint:
"{constraint}"

These players are already picked (don't hint at them): {', '.join(picked_names) if picked_names else 'None yet'}

Give ONE short, fun clue. Do NOT name the player. Reply with ONLY the clue, nothing else.""",
        }],
        system="You are a cricket fantasy game host. Give ONLY a one-sentence hint, no explanation or reasoning.",
        max_tokens=120,
        model=HINT_MODEL,
    )
    return _extract_final_answer(result)
