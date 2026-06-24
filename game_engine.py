import re
from scraper import find_player_local, find_player_candidates, load_players, scrape_and_cache
from prompt_generator import validate_player_against_constraint, generate_hint
from constraint_checker import validate_constraint
from llm_client import chat


def _is_valid_player_name(name):
    if not name or len(name) > 50:
        return False
    if re.search(r'[0-9/():\[\]{}]', name):
        return False
    if len(name.split()) > 6:
        return False
    noise = ["innings", "wicket", "bowler", "batsmen", "scored", "average",
             "select", "constraint", "fantasy", "draft", "pick ", "analyze"]
    lower = name.lower()
    if any(w in lower for w in noise):
        return False
    return True


class Game:
    def __init__(self, num_players, player_names, game_format, constraint):
        self.num_players = num_players
        self.player_names = player_names
        self.game_format = game_format
        self.constraint = constraint
        self.teams = {name: [] for name in player_names}
        self.current_turn_index = 0
        self.all_picked = []
        self.hinted_players = []
        self.players_db = load_players()

    @property
    def current_player(self):
        return self.player_names[self.current_turn_index]

    @property
    def current_pick_number(self):
        return len(self.teams[self.current_player]) + 1

    def is_draft_complete(self):
        return all(len(team) == 11 for team in self.teams.values())

    def advance_turn(self):
        self.current_turn_index = (self.current_turn_index + 1) % self.num_players

    def resolve_player(self, cricketer_name):
        name_lower = cricketer_name.strip().lower()

        # Exact match — no confirmation needed
        for p in self.players_db:
            if p["name"].lower() == name_lower:
                return p, True

        # Check nickname — resolve via fuzzy matching on the target name
        from scraper import NICKNAMES
        if name_lower in NICKNAMES:
            nick_target = NICKNAMES[name_lower]
            nick_candidates = find_player_candidates(nick_target, self.players_db)
            if len(nick_candidates) == 1:
                return nick_candidates[0], True
            if len(nick_candidates) > 1:
                return nick_candidates[0], "confirm"

        # Find candidates (fuzzy)
        candidates = find_player_candidates(cricketer_name, self.players_db)

        if len(candidates) == 1:
            p = candidates[0]
            if p["name"].lower() == name_lower:
                return p, True
            return p, "confirm"

        if len(candidates) > 1:
            return candidates, "choose"

        # No local match — try LLM spelling correction
        corrected = self._llm_correct_name(cricketer_name)
        if corrected and corrected.lower() != name_lower:
            from difflib import SequenceMatcher
            corrected_lower = corrected.lower()
            input_words = name_lower.split()
            corrected_words = corrected_lower.split()
            overall_sim = SequenceMatcher(None, name_lower, corrected_lower).ratio()
            words_found = sum(
                1 for w in input_words
                if any(SequenceMatcher(None, w, cw).ratio() > 0.7 for cw in corrected_words)
            )
            is_plausible = overall_sim > 0.4 and words_found >= 1
            if is_plausible:
                candidates = find_player_candidates(corrected, self.players_db)
                if len(candidates) == 1:
                    return candidates[0], "confirm"
                if len(candidates) > 1:
                    return candidates, "choose"
                # Not in local DB either — return corrected name for ESPN lookup
                return corrected, False

        return None, False

    def _llm_correct_name(self, name):
        try:
            result = chat(
                messages=[{
                    "role": "user",
                    "content": f'The user typed "{name}" as a cricketer\'s name in a {self.game_format} fantasy game. If this is misspelled, reply with the corrected full name. If only a surname or partial name was given, reply with the most likely full name for that format. Reply with ONLY the full player name, nothing else.',
                }],
                system="You are a cricket name spellchecker. Reply with only the corrected player name, nothing else.",
                max_tokens=30,
            )
            lines = [l.strip().strip('"').strip("'") for l in result.strip().splitlines() if l.strip()]
            return lines[-1] if lines else result.strip().strip('"').strip("'")
        except Exception:
            return None

    def make_pick(self, cricketer_name, confirmed_player=None):
        if confirmed_player:
            player_data = confirmed_player
        else:
            cleaned = re.sub(r'^[-–•*\d.]+\s*', '', cricketer_name).strip()
            if cleaned != cricketer_name:
                cricketer_name = cleaned
            if not _is_valid_player_name(cricketer_name):
                return False, "That doesn't look like a player name. Try typing a cricketer's name.", None

            name_lower = cricketer_name.strip().lower()
            for picked in self.all_picked:
                if picked["name"].lower() == name_lower:
                    return False, f"{picked['name']} has already been picked by another team.", None

            result, status = self.resolve_player(cricketer_name)

            if status == "confirm":
                return None, None, ("confirm", result)

            if status == "choose":
                return None, None, ("choose", result)

            if status is True:
                player_data = result
            else:
                # Not in local DB — try ESPN scrape with corrected name if available
                espn_name = result if isinstance(result, str) else cricketer_name
                print(f"  Looking up {espn_name} on ESPNcricinfo...")
                player_data = scrape_and_cache(espn_name, self.game_format)
                if player_data:
                    self.players_db = load_players()
                else:
                    return False, f"{cricketer_name} not found in database or on ESPNcricinfo. Check the spelling and try again.", None

        # Check duplicate with resolved name
        for picked in self.all_picked:
            if picked["name"].lower() == player_data["name"].lower():
                return False, f"{player_data['name']} has already been picked.", None

        result = validate_constraint(player_data, self.constraint, self.game_format)
        if result is not None:
            is_valid, reason = result
        else:
            is_valid, reason = validate_player_against_constraint(
                player_data, self.constraint, self.game_format
            )

        if not is_valid:
            fmt = self.game_format
            if self.game_format not in player_data.get("formats", {}):
                return False, f"{player_data['name']} hasn't played any {fmt} matches.", None
            return False, f"{player_data['name']} doesn't meet the constraint. {reason}", None

        prev_player = self.current_player
        self.teams[self.current_player].append(player_data)
        self.all_picked.append(player_data)
        self.advance_turn()
        return True, f"{player_data['name']} added to {prev_player}'s team!", None

    def get_hint(self):
        clue, player = generate_hint(
            self.constraint, self.all_picked, self.game_format,
            players_db=self.players_db, already_hinted=self.hinted_players,
        )
        if player:
            self.hinted_players.append(player)
        return clue

    def get_team_summary(self, player_name):
        team = self.teams[player_name]
        if not team:
            return f"{player_name}'s team: (empty)"

        lines = [f"\n{'='*50}", f"  {player_name}'s Team ({self.game_format})", f"{'='*50}"]
        for i, p in enumerate(team, 1):
            role = p.get("role", "Unknown")
            country = p.get("country", "Unknown")
            fmt_stats = p.get("formats", {}).get(self.game_format, {})
            runs = fmt_stats.get("runs", "?")
            wickets = fmt_stats.get("wickets", "?")
            avg = fmt_stats.get("bat_avg", "?")
            lines.append(f"  {i:2d}. {p['name']:<25s} {role:<15s} {country:<15s} Runs: {runs}  Wkts: {wickets}  Avg: {avg}")
        lines.append(f"{'='*50}")
        return "\n".join(lines)
