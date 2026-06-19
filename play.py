#!/usr/bin/env python3
from game_engine import Game
from prompt_generator import generate_prompt
from constraints import get_random_constraint
from match_simulator import simulate_series, VENUES


def print_banner():
    print("""
╔══════════════════════════════════════════════════╗
║         CRICKET FANTASY DRAFT GAME               ║
║         ────────────────────────────              ║
║         Draft your dream XI and battle!           ║
╚══════════════════════════════════════════════════╝
""")


def get_game_setup():
    print("── GAME SETUP ──\n")

    while True:
        try:
            num_players = int(input("How many players? (2-6): ").strip())
            if 2 <= num_players <= 6:
                break
            print("Please enter a number between 2 and 6.")
        except ValueError:
            print("Please enter a valid number.")

    names = []
    for i in range(1, num_players + 1):
        name = input(f"Player {i} name: ").strip()
        if not name:
            name = f"Player {i}"
        names.append(name)

    print("\nFormats: 1) Test  2) ODI  3) T20I")
    while True:
        fmt = input("Select format (1/2/3): ").strip()
        if fmt in ("1", "Test"):
            game_format = "Test"
            break
        elif fmt in ("2", "ODI"):
            game_format = "ODI"
            break
        elif fmt in ("3", "T20I", "T20"):
            game_format = "T20I"
            break
        print("Please select 1, 2, or 3.")

    return num_players, names, game_format


def get_constraint(game_format):
    print("\n── CONSTRAINT ──")
    print("1) Pick a random constraint (instant)")
    print("2) Generate a fresh constraint with AI (slower)")
    print("3) I have my own constraint")

    while True:
        choice = input("Choice (1/2/3): ").strip()
        if choice == "1":
            constraint = get_random_constraint(game_format)
            print(f'\n  Constraint: "{constraint}"')
            ok = input("\nHappy with this? (y/n): ").strip().lower()
            if ok == "n":
                constraint = get_random_constraint(game_format)
                print(f'\n  Constraint: "{constraint}"')
            return constraint
        elif choice == "2":
            print("\nGenerating a fun constraint...")
            constraint = generate_prompt(game_format)
            print(f'\n  Constraint: "{constraint}"')
            ok = input("\nHappy with this? (y/n): ").strip().lower()
            if ok == "n":
                print("Generating another...")
                constraint = generate_prompt(game_format)
                print(f'\n  Constraint: "{constraint}"')
            return constraint
        elif choice == "3":
            constraint = input("Enter your constraint: ").strip()
            if constraint:
                return constraint
            print("Please enter a constraint.")
        else:
            print("Please enter 1, 2, or 3.")


def run_draft(game):
    print(f"\n{'='*50}")
    print(f"  DRAFT START — {game.game_format}")
    print(f'  Constraint: "{game.constraint}"')
    print(f"  Round-robin order: {', '.join(game.player_names)}")
    print(f"{'='*50}\n")

    while not game.is_draft_complete():
        current = game.current_player
        pick_num = game.current_pick_number
        team_size = len(game.teams[current])

        if team_size == 0 or (team_size % game.num_players == 0 and pick_num > 1):
            if pick_num <= 11:
                print(f"\n── Round {team_size + 1} ──")

        print(f"\n  {current}'s turn (Pick {pick_num}/11)")

        while True:
            entry = input(f"  {current}, enter a cricketer (or 'hint'): ").strip()

            if not entry:
                print("  You must pick a player. Type 'hint' for a clue.")
                continue

            if entry.lower() == "hint":
                print(f"\n  Hint: {game.get_hint()}\n")
                continue

            success, message, action = game.make_pick(entry)

            if action:
                action_type, data = action
                confirmed_player = None

                if action_type == "confirm":
                    ans = input(f"  Did you mean {data['name']}? (y/n): ").strip().lower()
                    if ans == "y":
                        confirmed_player = data
                    else:
                        print("  Try again with a different name.")
                        continue

                elif action_type == "choose":
                    print("  Multiple matches found:")
                    for i, p in enumerate(data, 1):
                        print(f"    {i}) {p['name']} ({p.get('country', '?')}, {p.get('role', '?')})")
                    print(f"    0) None of these")
                    pick = input("  Which one? ").strip()
                    try:
                        idx = int(pick)
                        if 1 <= idx <= len(data):
                            confirmed_player = data[idx - 1]
                        else:
                            print("  Try again with a different name.")
                            continue
                    except ValueError:
                        print("  Try again with a different name.")
                        continue

                if confirmed_player:
                    success, message, _ = game.make_pick(entry, confirmed_player=confirmed_player)
                    if success:
                        print(f"  >> {message}")
                        break
                    else:
                        print(f"  !! {message}")
                        print("  Try again.")
                continue

            if success:
                print(f"  >> {message}")
                break
            else:
                print(f"  !! {message}")
                print("  Try again.")

    print("\n\n" + "=" * 50)
    print("  DRAFT COMPLETE!")
    print("=" * 50)

    for name in game.player_names:
        print(game.get_team_summary(name))


def get_simulation_setup():
    print("\n── MATCH SIMULATION SETUP ──\n")

    print("Available venue countries:")
    countries = list(VENUES.keys()) + ["Worldwide"]
    for i, c in enumerate(countries, 1):
        print(f"  {i}) {c}")

    while True:
        choice = input(f"Select venue country (1-{len(countries)}): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(countries):
                venue_country = countries[idx]
                break
        except ValueError:
            for c in countries:
                if choice.lower() == c.lower():
                    venue_country = c
                    break
            else:
                print("Please select a valid option.")
                continue
            break
        print("Please select a valid option.")

    while True:
        try:
            num_matches = int(input("How many matches to simulate? (1-5): ").strip())
            if 1 <= num_matches <= 5:
                break
            print("Please enter between 1 and 5.")
        except ValueError:
            print("Please enter a valid number.")

    return venue_country, num_matches


def run_simulation(game, venue_country, num_matches):
    player_names = game.player_names

    if game.num_players == 2:
        matchups = [(player_names[0], player_names[1])]
    else:
        matchups = []
        for i in range(len(player_names)):
            for j in range(i + 1, len(player_names)):
                matchups.append((player_names[i], player_names[j]))

    for p1, p2 in matchups:
        print(f"\n{'=' * 50}")
        print(f"  {p1} vs {p2}")
        print(f"  Format: {game.game_format} | Matches: {num_matches}")
        print(f"{'=' * 50}")

        result = simulate_series(
            game.teams[p1], game.teams[p2],
            f"{p1}'s XI", f"{p2}'s XI",
            venue_country, game.game_format, num_matches
        )

        if result.get("series_summary"):
            print(f"\n{'═' * 50}")
            print("  SERIES SUMMARY")
            print(f"{'═' * 50}")
            print(result["series_summary"])


def main():
    print_banner()

    num_players, names, game_format = get_game_setup()
    constraint = get_constraint(game_format)

    game = Game(num_players, names, game_format, constraint)
    run_draft(game)

    venue_country, num_matches = get_simulation_setup()
    run_simulation(game, venue_country, num_matches)

    print(f"\n{'=' * 50}")
    print("  GAME OVER — Thanks for playing!")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    main()
