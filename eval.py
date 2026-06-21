"""
Eval runner: 4 LLM personas play cricket fantasy drafts against each other.

Structure:
  - 4 personas, all 6 pairings (4C2) per format
  - 3 formats (Test, ODI, T20I) = 18 drafts total
  - Drafts saved to eval_results/drafts/ as JSON
  - Simulations run separately from saved drafts
  - 10-minute timeout per draft

Usage:
  python eval.py --drafts          # run drafts only
  python eval.py --sims            # run simulations from saved drafts
  python eval.py                   # run both
  python eval.py --seed 42         # reproducible pairings
"""

import json
import random
import time
import requests
import os
import sys
import subprocess
import signal
from datetime import datetime
from itertools import combinations
from llm_client import chat
import match_simulator
match_simulator._print_segment = lambda text: print(text + "\n")
from match_simulator import simulate_series

API_BASE = "http://localhost:5050"
PERSONA_MODEL = "gemma4:31b"
DRAFT_TIMEOUT = 600  # 10 minutes
MAX_RETRIES_PER_PICK = 5
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "eval_results")
DRAFTS_DIR = os.path.join(RESULTS_DIR, "drafts")

PERSONAS = {
    "casual_observer": {
        "display_name": "Casual Observer",
        "prompt": (
            "You are a casual cricket fan. You watch the occasional World Cup final and know\n"
            "the all-time megastars — the Tendulkars, Kohlis, Warnes, Laras, Dhonis — maybe two\n"
            "dozen names total, and you're fuzzy on the details of all of them. (Flavour, not a\n"
            "list to read off.)\n\n"
            "Each round you're given a constraint. You hear it but don't really know how to apply\n"
            "it — you don't know anyone's actual stats. So you pick the most famous name that comes\n"
            "to mind, vaguely hope it fits, and you're usually wrong. You pick on fame, not fit.\n\n"
            "Never pick a player already taken or one you've picked before. By your 5th or 6th pick\n"
            "you've run out of megastars and start guessing — half-remembered names, misspellings\n"
            "(\"Tendulker\", \"Ponteng\", \"Sanggakara\"), first-name-or-surname-only, names you're not\n"
            "even sure are real. The later it gets, the wilder.\n\n"
            "Respond in EXACTLY this format and nothing else:\n"
            "<think>one short, shaky, fame-based thought — never about real stats</think>\n"
            "<pick>one player name only — no reasoning, no punctuation, no commentary</pick>\n\n"
            "Example (constraint: batsmen with average below 40):\n"
            "<think>Below 40… dunno what anyone averages. Kohli's the best so probably fine?</think>\n"
            "<pick>Virat Kohli</pick>"
        ),
    },
    "cricket_geek": {
        "display_name": "Cricket Geek",
        "prompt": (
            "You are an obsessive cricket statistician. You've watched every Test since 1990 and\n"
            "your recall spans every era and the deep cuts — a Rangana Herath or a Chris Harris\n"
            "comes to mind as readily as the marquee names. You know hundreds of players; do not\n"
            "anchor to any short list.\n\n"
            "You build around the constraint from pick 1. Before each pick, name 3–4 candidates you\n"
            "believe satisfy the constraint, reason about each in stat terms, note which roles your\n"
            "team still needs (top order, finisher, spin, seam, keeper), then commit to the best\n"
            "AVAILABLE fit — deliberately preferring a correct non-obvious pick over a famous one.\n\n"
            "Never pick a player already taken or one you've picked before. Mix eras freely. Use\n"
            "formal names.\n\n"
            "Respond in EXACTLY this format and nothing else:\n"
            "<think>3–4 candidates, brief stat reasoning on each, role gaps, then your choice</think>\n"
            "<pick>one player name only — no reasoning, no punctuation, no commentary</pick>\n\n"
            "Example (constraint: left-arm bowlers from the subcontinent):\n"
            "<think>Left-arm, subcontinent: Vaas (SL, swung it both ways), Zaheer Khan (Ind, reverse),\n"
            "Irfan Pathan, Mitchell Johnson is left-arm but Australian — out. I still need a seamer\n"
            "who can open. Vaas over Zaheer for the new-ball control.</think>\n"
            "<pick>Chaminda Vaas</pick>"
        ),
    },
    "ipl_fan": {
        "display_name": "IPL Fan",
        "prompt": (
            "You started watching through T20 leagues and think red-ball cricket is boring. Your\n"
            "world is the modern franchise churn — the Suryakumars, Bumrahs, Rashids, Russells,\n"
            "Buttlers — and you can rattle off IPL/BBL/franchise names for days. (Flavour, not a\n"
            "menu — draw from the whole T20 universe.)\n\n"
            "You read every constraint through a T20 lens: you reason about strike rate, impact, and\n"
            "death-overs value even when the constraint is about Test averages, and you get annoyed\n"
            "when it seems to reward boring accumulators. Sometimes you pick a player who DOESN'T fit\n"
            "the constraint simply because they're too good in T20 to leave.\n\n"
            "Never pick a player already taken or one you've picked before. Late picks dig into the\n"
            "deep franchise pool — uncapped freelancers, journeymen with no international career.\n\n"
            "Respond in EXACTLY this format and nothing else:\n"
            "<think>impact/strike-rate reasoning — often misapplied to whatever the constraint is</think>\n"
            "<pick>one player name only — no reasoning, no punctuation, no commentary</pick>\n\n"
            "Example (constraint: batsmen with average below 40):\n"
            "<think>Below 40 average? That's a strike-rate guy, that's MY guys. Russell averages nothing\n"
            "in Tests because who cares, he's a matchwinner. Easy.</think>\n"
            "<pick>Andre Russell</pick>"
        ),
    },
    "nineties_nostalgist": {
        "display_name": "90s Nostalgist",
        "prompt": (
            "Cricket peaked in the 90s; the current lot are soft. You stopped watching around 2005.\n"
            "You know hundreds of players from that era — openers, the great fast-bowling quartets,\n"
            "the spin kings — far more than the handful that spring to mind first (Ambrose, Walsh,\n"
            "the Waughs, Warne, Murali, Lara). Draw freely from the whole 90s/early-2000s pool;\n"
            "don't stop at the obvious names.\n\n"
            "You apply the constraint competently — but only within your era — and you grumble when\n"
            "it forces you toward modern players you barely rate. Pick era candidates who fit, reason\n"
            "about them, fill classical team balance (you favour pace). As the draft goes on, go\n"
            "obscure — Franklyn Rose, Phil DeFreitas, Devon Malcolm, Craig McDermott territory.\n\n"
            "Never pick a player already taken or one you've picked before.\n\n"
            "Respond in EXACTLY this format and nothing else:\n"
            "<think>era candidates who fit, brief reasoning, team-balance note, then your choice</think>\n"
            "<pick>one player name only — no reasoning, no punctuation, no commentary</pick>\n\n"
            "Example (constraint: bowlers with average above 30):\n"
            "<think>Above 30 — middling for my era, the greats were all under 25. So a workhorse, not a\n"
            "gun. Streak carried Zimbabwe's attack on his own, averaged a touch high but no support.\n"
            "I've got pace already, he gives me control.</think>\n"
            "<pick>Heath Streak</pick>"
        ),
    },
}


# --- Server management ---

def check_server():
    """Return True if the game server is responding."""
    try:
        resp = requests.get(f"{API_BASE}/", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def start_server():
    """Start the Flask server as a background process. Returns the Popen object."""
    app_path = os.path.join(os.path.dirname(__file__), "app.py")
    proc = subprocess.Popen(
        [sys.executable, app_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(15):
        time.sleep(2)
        if check_server():
            print("  Server started.")
            return proc
    raise RuntimeError("Server failed to start within 30 seconds")


def ensure_server():
    """Check server is alive; start it if not."""
    if check_server():
        return None
    print("  Server is down, starting...")
    return start_server()


# --- Persona LLM ---

def build_persona_context(persona_id, game_format, constraint, my_team, opponent_team, last_result):
    lines = [
        f"Format: {game_format}",
        f"Constraint: {constraint}",
        "",
        f"Your team so far ({len(my_team)}/11):",
    ]
    if my_team:
        for i, p in enumerate(my_team, 1):
            lines.append(f"  {i}. {p}")
    else:
        lines.append("  (empty)")

    lines.append(f"\nOpponent's team ({len(opponent_team)}/11):")
    if opponent_team:
        for i, p in enumerate(opponent_team, 1):
            lines.append(f"  {i}. {p}")
    else:
        lines.append("  (empty)")

    if last_result:
        lines.append(f"\nLast pick result: {last_result}")

    lines.append(f"\nPick #{len(my_team) + 1} — type a player name:")
    return "\n".join(lines)


def _clean_persona_response(raw):
    import re
    text = raw.strip()

    pick_match = re.search(r'<pick>(.*?)</pick>', text, re.DOTALL)
    if pick_match:
        name = pick_match.group(1).strip()
        name = name.strip('"').strip("'").strip('*').strip('.').strip()
        return name

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return text

    NOISE_PHRASES = [
        "the user", "let me", "i'll pick", "i want", "my pick", "i choose",
        "i need", "analyzing", "considering", "looking at", "the constraints",
        "based on", "given the", "for my next", "i should", "i think",
        "<think>",
    ]

    good_lines = []
    for line in lines:
        lower = line.lower()
        if any(phrase in lower for phrase in NOISE_PHRASES):
            continue
        if len(line) > 60:
            continue
        good_lines.append(line)

    if good_lines:
        name = good_lines[-1]
    else:
        for line in reversed(lines):
            if len(line) <= 60:
                name = line
                break
        else:
            name = lines[-1]

    name = re.sub(r'^(pick|answer|player|choice|next)[:\s]+', '', name, flags=re.IGNORECASE)
    name = name.strip('"').strip("'").strip('*').strip('.').strip()
    return name


def _is_garbage_response(name):
    if len(name) > 80:
        return True
    garbage_words = [
        "constraint", "analyze", "fantasy", "draft", "the user", "let me",
        "bowlers", "batsmen", "innings", "wicket", "pick ", "select",
        "strategy", "consider", "looking", "thinking",
    ]
    lower = name.lower()
    if any(w in lower for w in garbage_words):
        return True
    if name and name[0].isdigit() and ". " in name[:4]:
        return True
    return False


def get_persona_pick(persona_id, context):
    persona = PERSONAS[persona_id]
    response = chat(
        messages=[{"role": "user", "content": context}],
        system=persona["prompt"],
        max_tokens=200,
        model=PERSONA_MODEL,
    )
    return _clean_persona_response(response)


# --- API helpers ---

def api_start(player1_name, player2_name, game_format):
    resp = requests.post(f"{API_BASE}/api/start", json={
        "player_names": [player1_name, player2_name],
        "format": game_format,
        "constraint_choice": "random",
    })
    resp.raise_for_status()
    return resp.json()


def api_pick(game_id, cricketer):
    resp = requests.post(f"{API_BASE}/api/pick", json={
        "game_id": game_id,
        "cricketer": cricketer,
    })
    resp.raise_for_status()
    return resp.json()


def api_confirm(game_id, cricketer, candidate):
    resp = requests.post(f"{API_BASE}/api/pick", json={
        "game_id": game_id,
        "cricketer": cricketer,
        "confirmed_player": candidate,
    })
    resp.raise_for_status()
    return resp.json()


def api_force_espn(game_id, cricketer):
    resp = requests.post(f"{API_BASE}/api/pick", json={
        "game_id": game_id,
        "cricketer": cricketer,
        "force_espn": True,
    })
    resp.raise_for_status()
    return resp.json()


def api_teams_raw(game_id):
    resp = requests.post(f"{API_BASE}/api/teams_raw", json={"game_id": game_id})
    resp.raise_for_status()
    return resp.json()


# --- Draft runner ---

class DraftTimeout(Exception):
    pass


def run_draft(persona1_id, persona2_id, game_format, log):
    """Run a single draft. Returns result dict or None on timeout."""
    p1_name = PERSONAS[persona1_id]["display_name"]
    p2_name = PERSONAS[persona2_id]["display_name"]

    header = f"\n{'='*70}\n  {p1_name} vs {p2_name} — {game_format} Draft\n{'='*70}"
    print(header)
    log.append(header)

    ensure_server()

    start_data = api_start(p1_name, p2_name, game_format)
    game_id = start_data["game_id"]
    constraint = start_data["constraint"]

    print(f"  Constraint: {constraint}")
    log.append(f"  Constraint: {constraint}")

    teams = {persona1_id: [], persona2_id: []}
    turn_order = [persona1_id, persona2_id]
    turn_idx = 0
    last_results = {persona1_id: None, persona2_id: None}

    total_picks = 0
    total_attempts = 0
    total_espn_lookups = 0
    total_rejections = 0
    consecutive_api_errors = 0
    draft_start = time.time()

    while total_picks < 22:
        if time.time() - draft_start > DRAFT_TIMEOUT:
            timeout_msg = f"  ⚠ DRAFT TIMED OUT after {DRAFT_TIMEOUT // 60} minutes ({total_picks}/22 picks)"
            print(timeout_msg)
            log.append(timeout_msg)
            break

        current = turn_order[turn_idx]
        opponent = turn_order[1 - turn_idx]

        context = build_persona_context(
            current, game_format, constraint,
            teams[current], teams[opponent],
            last_results[current],
        )

        picked = False
        attempts = 0

        while not picked and attempts < MAX_RETRIES_PER_PICK:
            if time.time() - draft_start > DRAFT_TIMEOUT:
                break

            attempts += 1
            total_attempts += 1

            pick_name = get_persona_pick(current, context)

            if _is_garbage_response(pick_name):
                msg = f"  [{PERSONAS[current]['display_name']}] Pick #{len(teams[current])+1}, attempt {attempts}: \"{pick_name[:60]}\" (garbage)"
                print(msg)
                log.append(msg)
                last_results[current] = "Invalid response — just type a player name, nothing else."
                context = build_persona_context(
                    current, game_format, constraint,
                    teams[current], teams[opponent],
                    last_results[current],
                )
                continue

            entry = f"  [{PERSONAS[current]['display_name']}] Pick #{len(teams[current])+1}, attempt {attempts}: \"{pick_name}\""
            print(entry)
            log.append(entry)

            try:
                result = api_pick(game_id, pick_name)
                consecutive_api_errors = 0
            except Exception as e:
                consecutive_api_errors += 1
                err = f"    API error: {e}"
                print(err)
                log.append(err)

                if consecutive_api_errors >= 3:
                    print("  ⚠ 3 consecutive API errors — restarting server...")
                    log.append("  ⚠ Restarting server after repeated errors")
                    start_server()
                    consecutive_api_errors = 0
                    start_data = api_start(p1_name, p2_name, game_format)
                    game_id = start_data["game_id"]
                    restart_msg = f"  ⚠ New game started (old game state lost). Constraint: {start_data['constraint']}"
                    print(restart_msg)
                    log.append(restart_msg)
                    teams = {persona1_id: [], persona2_id: []}
                    total_picks = 0
                    last_results = {persona1_id: None, persona2_id: None}
                    break

                last_results[current] = f"Error trying \"{pick_name}\": {e}"
                context = build_persona_context(
                    current, game_format, constraint,
                    teams[current], teams[opponent],
                    last_results[current],
                )
                continue

            status = result.get("status")

            if status == "picked":
                player_name = result["player"]["name"]
                msg = f"    ✓ Picked: {player_name}"
                print(msg)
                log.append(msg)
                teams[current].append(player_name)
                last_results[current] = f"Picked {player_name}"
                picked = True
                total_picks += 1

            elif status == "confirm":
                candidate = result.get("candidate", "")
                msg = f"    ? Confirm: {candidate}"
                print(msg)
                log.append(msg)
                try:
                    confirm_result = api_confirm(game_id, pick_name, candidate)
                    if confirm_result.get("status") == "picked":
                        player_name = confirm_result["player"]["name"]
                        msg2 = f"    ✓ Confirmed: {player_name}"
                        print(msg2)
                        log.append(msg2)
                        teams[current].append(player_name)
                        last_results[current] = f"Picked {player_name}"
                        picked = True
                        total_picks += 1
                    else:
                        rej = confirm_result.get("message", "Rejected after confirm")
                        msg2 = f"    ✗ Rejected after confirm: {rej}"
                        print(msg2)
                        log.append(msg2)
                        last_results[current] = rej
                        total_rejections += 1
                        context = build_persona_context(
                            current, game_format, constraint,
                            teams[current], teams[opponent],
                            last_results[current],
                        )
                except Exception as e:
                    err = f"    Confirm error: {e}"
                    print(err)
                    log.append(err)

            elif status == "choose":
                candidates = result.get("candidates", [])
                if candidates:
                    chosen = candidates[0]["name"]
                    msg = f"    ? Multiple matches, picking first: {chosen}"
                    print(msg)
                    log.append(msg)
                    try:
                        confirm_result = api_confirm(game_id, pick_name, chosen)
                        if confirm_result.get("status") == "picked":
                            player_name = confirm_result["player"]["name"]
                            msg2 = f"    ✓ Confirmed: {player_name}"
                            print(msg2)
                            log.append(msg2)
                            teams[current].append(player_name)
                            last_results[current] = f"Picked {player_name}"
                            picked = True
                            total_picks += 1
                        else:
                            rej = confirm_result.get("message", "Rejected")
                            msg2 = f"    ✗ Rejected: {rej}"
                            print(msg2)
                            log.append(msg2)
                            last_results[current] = rej
                            total_rejections += 1
                            context = build_persona_context(
                                current, game_format, constraint,
                                teams[current], teams[opponent],
                                last_results[current],
                            )
                    except Exception as e:
                        err = f"    Confirm error: {e}"
                        print(err)
                        log.append(err)
                else:
                    total_rejections += 1

            elif status == "rejected":
                rej_msg = result.get("message", "Rejected")
                msg = f"    ✗ Rejected: {rej_msg}"
                print(msg)
                log.append(msg)
                total_rejections += 1

                if "not found" in rej_msg.lower() or "hasn't played" in rej_msg.lower():
                    espn_msg = f"    → ESPN lookup for: {pick_name}"
                    print(espn_msg)
                    log.append(espn_msg)
                    total_espn_lookups += 1
                    try:
                        espn_result = api_force_espn(game_id, pick_name)
                        espn_status = espn_result.get("status")
                        if espn_status == "confirm":
                            candidate = espn_result.get("candidate", "")
                            confirm_result = api_confirm(game_id, pick_name, candidate)
                            if confirm_result.get("status") == "picked":
                                player_name = confirm_result["player"]["name"]
                                msg2 = f"    ✓ ESPN found & picked: {player_name}"
                                print(msg2)
                                log.append(msg2)
                                teams[current].append(player_name)
                                last_results[current] = f"Picked {player_name} (via ESPN)"
                                picked = True
                                total_picks += 1
                            else:
                                rej2 = confirm_result.get("message", "Rejected after ESPN")
                                msg2 = f"    ✗ ESPN found but rejected: {rej2}"
                                print(msg2)
                                log.append(msg2)
                                last_results[current] = rej2
                                context = build_persona_context(
                                    current, game_format, constraint,
                                    teams[current], teams[opponent],
                                    last_results[current],
                                )
                        else:
                            espn_rej = espn_result.get("message", "Not found on ESPN")
                            msg2 = f"    ✗ ESPN: {espn_rej}"
                            print(msg2)
                            log.append(msg2)
                            last_results[current] = espn_rej
                            context = build_persona_context(
                                current, game_format, constraint,
                                teams[current], teams[opponent],
                                last_results[current],
                            )
                    except Exception as e:
                        err = f"    ESPN error: {e}"
                        print(err)
                        log.append(err)
                else:
                    last_results[current] = rej_msg
                    context = build_persona_context(
                        current, game_format, constraint,
                        teams[current], teams[opponent],
                        last_results[current],
                    )

        if not picked:
            bail = f"    ⚠ {PERSONAS[current]['display_name']} failed to pick after {MAX_RETRIES_PER_PICK} attempts, skipping slot"
            print(bail)
            log.append(bail)
            teams[current].append("[FAILED]")
            total_picks += 1

        turn_idx = 1 - turn_idx

    elapsed = time.time() - draft_start

    summary_lines = [
        f"\n  --- Draft Summary ({elapsed:.0f}s) ---",
        f"  Total attempts: {total_attempts}",
        f"  Rejections: {total_rejections}",
        f"  ESPN lookups: {total_espn_lookups}",
    ]
    for pid in turn_order:
        summary_lines.append(f"\n  {PERSONAS[pid]['display_name']}'s XI:")
        for i, p in enumerate(teams[pid], 1):
            summary_lines.append(f"    {i:2d}. {p}")

    for line in summary_lines:
        print(line)
        log.append(line)

    # Fetch full team data for simulation
    teams_raw = None
    try:
        raw = api_teams_raw(game_id)
        teams_raw = raw.get("teams")
    except Exception:
        pass

    return {
        "persona1": persona1_id,
        "persona2": persona2_id,
        "format": game_format,
        "constraint": constraint,
        "game_id": game_id,
        "teams_picked": {persona1_id: teams[persona1_id], persona2_id: teams[persona2_id]},
        "teams_raw": teams_raw,
        "total_attempts": total_attempts,
        "rejections": total_rejections,
        "espn_lookups": total_espn_lookups,
        "elapsed_seconds": elapsed,
        "complete": total_picks == 22,
    }


def save_draft(result):
    """Save a draft result to disk."""
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    p1 = result["persona1"]
    p2 = result["persona2"]
    fmt = result["format"]
    filename = f"{fmt}_{p1}_vs_{p2}.json"
    filepath = os.path.join(DRAFTS_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(result, f, indent=2, default=str)
    return filepath


# --- Simulation runner ---

def run_simulations_from_file(filepath, log):
    """Run 3 match simulations from a saved draft file."""
    with open(filepath) as f:
        draft = json.load(f)

    p1 = draft["persona1"]
    p2 = draft["persona2"]
    game_format = draft["format"]
    p1_name = PERSONAS[p1]["display_name"]
    p2_name = PERSONAS[p2]["display_name"]
    teams_raw = draft.get("teams_raw")

    if not teams_raw:
        msg = f"  ✗ No team data for {p1_name} vs {p2_name} ({game_format}), skipping"
        print(msg)
        log.append(msg)
        return None

    team1 = teams_raw.get(p1_name, [])
    team2 = teams_raw.get(p2_name, [])

    if not team1 or not team2:
        msg = f"  ✗ Empty team data for {p1_name} vs {p2_name} ({game_format}), skipping"
        print(msg)
        log.append(msg)
        return None

    sim_header = f"\n  --- Simulating 3-match series: {p1_name} vs {p2_name} ({game_format}) ---"
    print(sim_header)
    log.append(sim_header)

    series_result = simulate_series(
        team1, team2, p1_name, p2_name,
        "worldwide", game_format, num_matches=3,
    )

    if series_result.get("series_summary"):
        summary = f"\n  SERIES SUMMARY:\n  {series_result['series_summary']}"
        print(summary)
        log.append(summary)

    return series_result


# --- Main orchestration ---

def run_drafts(seed=None):
    """Run all drafts and save results to disk."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"eval_drafts_{timestamp}.txt"
    log = []

    persona_ids = list(PERSONAS.keys())
    all_pairings = list(combinations(persona_ids, 2))
    formats = ["Test", "ODI", "T20I"]
    total_drafts = len(all_pairings) * len(formats)

    if seed is not None:
        random.seed(seed)
        random.shuffle(all_pairings)

    print(f"\n Cricket Fantasy Eval — Drafts")
    print(f"  {len(persona_ids)} personas × {len(all_pairings)} pairings × {len(formats)} formats = {total_drafts} drafts")
    print(f"  Persona model: {PERSONA_MODEL}")
    print(f"  Timeout: {DRAFT_TIMEOUT // 60} minutes per draft")
    print(f"  Seed: {seed}")
    print(f"  Log: {log_file}\n")
    log.append(f"Eval drafts: {timestamp}")
    log.append(f"Seed: {seed}")

    completed = 0
    timed_out = 0
    failed = 0

    for fmt in formats:
        fmt_header = f"\n{'#'*70}\n  FORMAT: {fmt}\n{'#'*70}"
        print(fmt_header)
        log.append(fmt_header)

        pairings_info = "  Pairings: " + " | ".join(
            f"{PERSONAS[a]['display_name']} vs {PERSONAS[b]['display_name']}"
            for a, b in all_pairings
        )
        print(pairings_info)
        log.append(pairings_info)

        for p1, p2 in all_pairings:
            try:
                result = run_draft(p1, p2, fmt, log)
                filepath = save_draft(result)
                saved_msg = f"  → Saved: {filepath}"
                print(saved_msg)
                log.append(saved_msg)

                if result["complete"]:
                    completed += 1
                else:
                    timed_out += 1
            except Exception as e:
                err = f"\n  ✗ DRAFT FAILED: {PERSONAS[p1]['display_name']} vs {PERSONAS[p2]['display_name']} {fmt}: {e}"
                print(err)
                log.append(err)
                failed += 1

    final = [
        f"\n{'#'*70}",
        f"  DRAFTS COMPLETE",
        f"{'#'*70}",
        f"  Completed: {completed}/{total_drafts}",
        f"  Timed out: {timed_out}/{total_drafts}",
        f"  Failed: {failed}/{total_drafts}",
        f"  Results saved in: {DRAFTS_DIR}",
    ]
    for line in final:
        print(line)
        log.append(line)

    with open(os.path.join(os.path.dirname(__file__), log_file), "w") as f:
        f.write("\n".join(log))


def run_sims():
    """Run simulations from all saved draft files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"eval_sims_{timestamp}.txt"
    log = []

    if not os.path.exists(DRAFTS_DIR):
        print(f"  No drafts found in {DRAFTS_DIR}. Run --drafts first.")
        return

    draft_files = sorted(f for f in os.listdir(DRAFTS_DIR) if f.endswith(".json"))
    if not draft_files:
        print(f"  No draft files found in {DRAFTS_DIR}.")
        return

    print(f"\n Cricket Fantasy Eval — Simulations")
    print(f"  {len(draft_files)} drafts to simulate")
    print(f"  Log: {log_file}\n")

    for df in draft_files:
        filepath = os.path.join(DRAFTS_DIR, df)
        try:
            run_simulations_from_file(filepath, log)
        except Exception as e:
            err = f"  ✗ Simulation failed for {df}: {e}"
            print(err)
            log.append(err)

    with open(os.path.join(os.path.dirname(__file__), log_file), "w") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    args = sys.argv[1:]

    seed = None
    if "--seed" in args:
        idx = args.index("--seed")
        seed = int(args[idx + 1])
        args = [a for i, a in enumerate(args) if i != idx and i != idx + 1]

    if "--drafts" in args:
        run_drafts(seed=seed)
    elif "--sims" in args:
        run_sims()
    else:
        run_drafts(seed=seed)
        run_sims()
