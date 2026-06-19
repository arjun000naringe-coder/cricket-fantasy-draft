from flask import Flask, render_template, request, jsonify
from game_engine import Game
from constraints import get_random_constraint
from prompt_generator import generate_prompt
from llm_client import chat

app = Flask(__name__)

games = {}

ROLE_ORDER = {"Batsman": 0, "Wicket-keeper": 1, "All-rounder": 2, "Bowler": 3}


def _format_stats_card(player, game_format):
    fmt = player.get("formats", {}).get(game_format, {})
    if not fmt:
        return None

    role = player.get("role", "Unknown")
    lines = []

    if role in ("Batsman", "Wicket-keeper", "All-rounder"):
        lines.append(f"🏏 {fmt.get('matches', '?')} matches · {fmt.get('runs', '?')} runs · avg {fmt.get('bat_avg', '?')} · {fmt.get('hundreds', '?')} 100s · {fmt.get('fifties', '?')} 50s · HS {fmt.get('highest_score', '?')}")

    if role in ("Bowler", "All-rounder"):
        lines.append(f"⚾ {fmt.get('wickets', '?')} wickets · avg {fmt.get('bowl_avg', '?')} · best {fmt.get('best_bowling', '?')} · {fmt.get('five_wickets', '?')} × 5W")

    if role == "Bowler" and not any("runs" in l for l in lines):
        if fmt.get("runs", 0):
            lines.append(f"🏏 {fmt.get('runs', '?')} runs · avg {fmt.get('bat_avg', '?')}")

    return "\n".join(lines)


def _extract_commentary(text):
    import re
    quoted = re.findall(r'"([^"]{15,})"', text)
    if quoted:
        return quoted[-1]
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if lines:
        last = lines[-1].strip('"').strip()
        if len(last) > 10:
            return last
    return text.strip().strip('"')[:150]


def _generate_pick_commentary(player, game_format, constraint):
    fmt_stats = player.get("formats", {}).get(game_format, {})
    try:
        result = chat(
            messages=[{
                "role": "user",
                "content": f'The player just drafted {player["name"]} ({player.get("country", "?")}, {player.get("role", "?")}) in a {game_format} fantasy game with constraint: "{constraint}". Stats: {fmt_stats}. Write ONE short, fun, debate-sparking sentence about this pick. Be opinionated — praise bold picks, question safe ones, reference rivalries or iconic moments. No more than 25 words. Reply with ONLY the sentence, nothing else.',
            }],
            system="You are a cricket fantasy draft commentator. Be witty, opinionated, and fun. Reply with ONLY one sentence, no explanation or reasoning.",
            max_tokens=60,
        )
        return _extract_commentary(result)
    except Exception:
        return ""


def _order_team(team):
    return sorted(team, key=lambda p: ROLE_ORDER.get(p.get("role", "Unknown"), 5))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_game():
    data = request.json
    num_players = data.get("num_players", 1)
    player_names = data.get("player_names", [])
    if not player_names:
        player_names = [data.get("player_name", "Player 1").strip() or "Player 1"]
    num_players = len(player_names)
    game_format = data.get("format", "T20I")
    constraint_choice = data.get("constraint_choice", "random")

    if constraint_choice == "random":
        constraint = get_random_constraint(game_format)
    elif constraint_choice == "ai":
        constraint = generate_prompt(game_format)
    else:
        constraint = data.get("custom_constraint", "").strip()
        if not constraint:
            constraint = get_random_constraint(game_format)

    game = Game(num_players, player_names, game_format, constraint)
    game_id = str(id(game))
    games[game_id] = game

    return jsonify({
        "game_id": game_id,
        "constraint": constraint,
        "format": game_format,
        "player_names": player_names,
        "current_turn": game.current_player,
    })


@app.route("/api/pick", methods=["POST"])
def make_pick():
    data = request.json
    game_id = data.get("game_id")
    cricketer = data.get("cricketer", "").strip()
    confirmed_index = data.get("confirmed_index")
    confirmed_player = data.get("confirmed_player")

    game = games.get(game_id)
    if not game:
        return jsonify({"error": "Game not found. Start a new game."}), 404

    def _pick_success_response(picked_player, game):
        stats = _format_stats_card(picked_player, game.game_format)
        commentary = _generate_pick_commentary(picked_player, game.game_format, game.constraint)
        prev_player = game.player_names[(game.current_turn_index - 1) % game.num_players]
        return jsonify({
            "status": "picked",
            "player": _player_summary(picked_player, game.game_format),
            "stats": stats,
            "commentary": commentary,
            "picked_for": prev_player,
            "current_turn": game.current_player,
            "pick_number": len(game.teams[prev_player]),
            "next_pick": len(game.teams[game.current_player]) + 1,
            "draft_complete": game.is_draft_complete(),
        })

    if confirmed_player:
        for p in game.players_db:
            if p["name"] == confirmed_player:
                success, message, action = game.make_pick(cricketer, confirmed_player=p)
                if success:
                    return _pick_success_response(p, game)
                else:
                    return jsonify({"status": "rejected", "message": message})
        return jsonify({"status": "rejected", "message": "Player not found."})

    if not cricketer:
        return jsonify({"status": "rejected", "message": "Type a cricketer's name to pick them."})

    success, message, action = game.make_pick(cricketer)

    if action:
        action_type, action_data = action
        if action_type == "confirm":
            return jsonify({
                "status": "confirm",
                "message": f"Did you mean <b>{action_data['name']}</b> ({action_data.get('country', '?')}, {action_data.get('role', '?')})?",
                "candidate": action_data["name"],
            })
        elif action_type == "choose":
            candidates = []
            for p in action_data:
                candidates.append({
                    "name": p["name"],
                    "country": p.get("country", "?"),
                    "role": p.get("role", "?"),
                })
            return jsonify({
                "status": "choose",
                "message": "Multiple matches found. Which one?",
                "candidates": candidates,
            })

    if success:
        picked = game.all_picked[-1]
        return _pick_success_response(picked, game)
    else:
        return jsonify({"status": "rejected", "message": message})


def _player_summary(player, game_format):
    return {
        "name": player.get("name"),
        "country": player.get("country", "?"),
        "role": player.get("role", "?"),
        "bat_hand": player.get("bat_hand", "?"),
        "bowl_style": player.get("bowl_style", "N/A"),
    }


@app.route("/api/hint", methods=["POST"])
def get_hint():
    data = request.json
    game_id = data.get("game_id")
    game = games.get(game_id)
    if not game:
        return jsonify({"error": "Game not found."}), 404

    hint = game.get_hint()
    return jsonify({"hint": hint})


def _build_team_data(player_name, game):
    team = game.teams[player_name]
    ordered = _order_team(team)
    players = []
    for i, p in enumerate(ordered, 1):
        fmt = p.get("formats", {}).get(game.game_format, {})
        players.append({
            "number": i,
            "name": p["name"],
            "country": p.get("country", "?"),
            "role": p.get("role", "?"),
            "runs": fmt.get("runs", "-"),
            "bat_avg": fmt.get("bat_avg", "-"),
            "wickets": fmt.get("wickets", "-"),
            "bowl_avg": fmt.get("bowl_avg", "-"),
        })
    return {
        "team_name": f"{player_name}'s XI",
        "format": game.game_format,
        "count": len(team),
        "players": players,
    }


@app.route("/api/team", methods=["POST"])
def get_team():
    data = request.json
    game_id = data.get("game_id")
    game = games.get(game_id)
    if not game:
        return jsonify({"error": "Game not found."}), 404

    if game.num_players == 1:
        return jsonify(_build_team_data(game.player_names[0], game))
    else:
        teams = [_build_team_data(name, game) for name in game.player_names]
        return jsonify({"teams": teams, "format": game.game_format})


@app.route("/api/reroll_constraint", methods=["POST"])
def reroll_constraint():
    data = request.json
    game_format = data.get("format", "T20I")
    constraint = get_random_constraint(game_format)
    return jsonify({"constraint": constraint})


if __name__ == "__main__":
    app.run(debug=True, port=5050)
