#!/usr/bin/env python3
"""Generate the static player dataset by asking Claude for batches of players."""
import anthropic
import json
import os

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "players.json")

BATCH_PROMPTS = [
    "Generate 25 legendary batsmen from the 1990s-2020s (Tendulkar, Lara, Ponting, Kallis, Kohli, Smith, Williamson, Root, Babar Azam, AB de Villiers, Hayden, Sehwag, Dravid, Sangakkara, Jayawardene, Younis Khan, Inzamam, Amla, Laxman, Chanderpaul, Flower, Hussey, Clarke, Warner, Aravinda de Silva)",
    "Generate 25 legendary bowlers from the 1990s-2020s (Warne, Muralitharan, McGrath, Akram, Waqar, Ambrose, Walsh, Donald, Steyn, Anderson, Broad, Bumrah, Cummins, Starc, Rabada, Southee, Boult, Malinga, Vaas, Harbhajan, Kumble, Saqlain, Shoaib Akhtar, Brett Lee, Zaheer Khan)",
    "Generate 25 all-rounders and wicket-keepers (Stokes, Flintoff, Sobers era excluded, Jadeja, Shakib, Holder, Ashwin, Lyon, Moeen Ali, Kapil Dev 1990s stats, Cairns, Vettori, Afridi, Razzaq — WKs: Dhoni, Gilchrist, Boucher, Sangakkara WK stats, Healy, McCullum, Buttler, Bairstow, Rizwan, QdK, Pant, Watling)",
    "Generate 25 modern era stars and rising players (Labuschagne, Conway, Shubman Gill, Crawley, Head, Iyer, Surya Kumar Yadav, Hardik Pandya, Archer, Shaheen Afridi, Naseem Shah, Mitchell Marsh, Glenn Maxwell, David Miller, Hetmyer, Pooran, Rashid Khan, Nortje, Hasaranga, Siraj, Shami, Rizwan, Fakhar Zaman, Mushfiqur Rahim, Tamim Iqbal)",
    "Generate 25 more players to round out the dataset - mix of countries especially West Indies, Zimbabwe, Bangladesh, Afghanistan, Sri Lanka. Include: Gayle, Pollard, Russell, Sammy, Bravo, Nkrumah Bonner, Atapattu, Jayasuriya, Dilshan, Mathews, Mushfiqur, Mahmudullah, Mashrafe, Brendon Taylor, Andy Flower, Heath Streak, Grant Flower, Rashid Khan if not already included, Mujeeb, Nabi, Karunaratne, Thirimanne, Perera, Chaminda Vaas if not already, Rangana Herath",
]

SYSTEM = """You are a cricket statistics database. Generate player data as a JSON array.

Each player object MUST have this EXACT structure:
{
  "name": "Full Name",
  "country": "Country",
  "role": "Batsman" or "Bowler" or "All-rounder" or "Wicket-keeper",
  "bat_hand": "Right" or "Left",
  "bowl_style": "e.g. Right-arm fast, Left-arm orthodox, Leg break" or "N/A",
  "formats": {
    "Test": {
      "matches": 200, "innings_bat": 329, "runs": 15921, "bat_avg": 53.78,
      "hundreds": 51, "fifties": 68, "highest_score": "248*",
      "innings_bowl": 74, "wickets": 46, "bowl_avg": 54.17,
      "best_bowling": "3/10", "five_wickets": 0, "catches": 115, "stumpings": 0
    },
    "ODI": { ...same structure... },
    "T20I": { ...same structure... }
  }
}

Rules:
- Only include format entries for formats the player actually played
- Use reasonably accurate career statistics (these are well-known players)
- All players must have played at least one international match after 1990
- For bowling stats of pure batsmen, set wickets to 0 and bowl_avg to 0
- Return ONLY a valid JSON array, no markdown, no explanation"""


def generate_batch(client, prompt):
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def main():
    client = anthropic.Anthropic()
    all_players = []
    seen_names = set()

    for i, prompt in enumerate(BATCH_PROMPTS, 1):
        print(f"Generating batch {i}/{len(BATCH_PROMPTS)}...")
        try:
            batch = generate_batch(client, prompt)
            for player in batch:
                name = player["name"]
                if name not in seen_names:
                    seen_names.add(name)
                    all_players.append(player)
                    print(f"  + {name} ({player.get('country', '?')})")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  Error in batch {i}: {e}")
            continue

    print(f"\nTotal: {len(all_players)} unique players")

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w") as f:
        json.dump(all_players, f, indent=2)
    print(f"Saved to {DATA_PATH}")


if __name__ == "__main__":
    main()
