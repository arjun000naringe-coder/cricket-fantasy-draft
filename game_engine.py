from scraper import find_player_local, find_player_candidates, load_players, scrape_and_cache
from prompt_generator import validate_player_against_constraint, generate_hint
from llm_client import chat


class Game:
    def __init__(self, num_players, player_names, game_format, constraint):
        self.num_players = num_players
        self.player_names = player_names
        self.game_format = game_format
        self.constraint = constraint
        self.teams = {name: [] for name in player_names}
        self.current_turn_index = 0
        self.all_picked = []
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

        # Check nickname — exact nickname hit = no confirmation needed
        from scraper import NICKNAMES
        if name_lower in NICKNAMES:
            nick_target = NICKNAMES[name_lower].lower()
            for p in self.players_db:
                if p["name"].lower() == nick_target:
                    return p, True

        # Find candidates (fuzzy)
        candidates = find_player_candidates(cricketer_name, self.players_db)

        if len(candidates) == 1:
            p = candidates[0]
            if p["name"].lower() == name_lower:
                return p, True
            return p, "confirm"

        if len(candidates) > 1:
            return candidates, "choose"

        # No local match — try LLM spelling correction, then ESPN
        corrected = self._llm_correct_name(cricketer_name)
        if corrected and corrected.lower() != name_lower:
            from difflib import SequenceMatcher
            similarity = SequenceMatcher(None, name_lower, corrected.lower()).ratio()
            if similarity > 0.5:
                candidates = find_player_candidates(corrected, self.players_db)
                if len(candidates) == 1:
                    return candidates[0], "confirm"
                if len(candidates) > 1:
                    return candidates, "choose"

        return None, False

    def _llm_correct_name(self, name):
        try:
            result = chat(
                messages=[{
                    "role": "user",
                    "content": f'The user typed "{name}" as a cricketer\'s name. If this is misspelled, reply with ONLY the corrected full name. If it\'s already correct or you\'re unsure, reply with ONLY the name as-is. No explanation.',
                }],
                system="You are a cricket name spellchecker. Reply with only the corrected player name, nothing else.",
                max_tokens=30,
            )
            lines = [l.strip().strip('"').strip("'") for l in result.strip().splitlines() if l.strip()]
            return lines[-1] if lines else result.strip().strip('"').strip("'")
        except Exception:
            return None

    def _llm_player_metadata(self, name):
        try:
            result = chat(
                messages=[{
                    "role": "user",
                    "content": f'For the cricketer "{name}", provide: country, role (Batsman/Bowler/All-rounder/Wicket-keeper), batting hand (Left/Right), bowling style. Reply in EXACTLY this format:\ncountry: <country>\nrole: <role>\nbat_hand: <Left or Right>\nbowl_style: <style or N/A>',
                }],
                system="You are a cricket knowledge expert. Reply with only the requested fields, nothing else.",
                max_tokens=60,
            )
            meta = {}
            for line in result.strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    meta[key.strip().lower().replace(" ", "_")] = val.strip()
            return meta
        except Exception:
            return {}

    def make_pick(self, cricketer_name, confirmed_player=None):
        if confirmed_player:
            player_data = confirmed_player
        else:
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
                # Not in local DB — try ESPN scrape
                print(f"  Looking up {cricketer_name} on ESPNcricinfo...")
                player_data = scrape_and_cache(cricketer_name, self.game_format)
                if player_data:
                    self.players_db = load_players()
                else:
                    is_valid, reason = validate_player_against_constraint(
                        {"name": cricketer_name, "note": "Player not found in database, using LLM knowledge"},
                        self.constraint,
                        self.game_format,
                    )
                    if not is_valid:
                        return False, f"Could not verify {cricketer_name}. {reason}", None
                    metadata = self._llm_player_metadata(cricketer_name)
                    player_data = {
                        "name": cricketer_name,
                        "country": metadata.get("country", "Unknown"),
                        "role": metadata.get("role", "Unknown"),
                        "bat_hand": metadata.get("bat_hand", "Unknown"),
                        "bowl_style": metadata.get("bowl_style", "Unknown"),
                        "formats": {},
                    }
                    print(f"  Note: {cricketer_name} stats are approximate (not found on ESPN).")

        # Check duplicate with resolved name
        for picked in self.all_picked:
            if picked["name"].lower() == player_data["name"].lower():
                return False, f"{player_data['name']} has already been picked.", None

        if player_data.get("formats", {}).get(self.game_format):
            is_valid, reason = validate_player_against_constraint(
                player_data, self.constraint, self.game_format
            )
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
        return generate_hint(
            self.constraint, self.all_picked, self.game_format
        )

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
