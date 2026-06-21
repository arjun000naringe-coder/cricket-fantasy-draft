import requests
from bs4 import BeautifulSoup
import json
import os
import re
from difflib import SequenceMatcher

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "players.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

FORMAT_LABELS = {
    "Test": "Test matches",
    "ODI": "One-Day Internationals",
    "T20I": "Twenty20 Internationals",
}


def load_players():
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r") as f:
            return json.load(f)
    return []


def save_players(players):
    with open(DATA_PATH, "w") as f:
        json.dump(players, f, indent=2)


NICKNAMES = {
    "msd": "MS Dhoni", "dhoni": "MS Dhoni",
    "abd": "AB de Villiers", "de villiers": "AB de Villiers",
    "vk": "Virat Kohli", "kohli": "Virat Kohli",
    "rohit": "Rohit Sharma", "hitman": "Rohit Sharma",
    "sachin": "Sachin Tendulkar", "tendulkar": "Sachin Tendulkar",
    "ponting": "Ricky Ponting",
    "warne": "Shane Warne",
    "murali": "Muttiah Muralitharan", "muralitharan": "Muttiah Muralitharan",
    "mcgrath": "Glenn McGrath",
    "wasim": "Wasim Akram", "akram": "Wasim Akram",
    "steyn": "Dale Steyn",
    "gayle": "Chris Gayle", "gail": "Chris Gayle", "universe boss": "Chris Gayle",
    "bumrah": "Jasprit Bumrah",
    "cummins": "Pat Cummins",
    "stokes": "Ben Stokes",
    "kallis": "Jacques Kallis",
    "gilchrist": "Adam Gilchrist", "gilly": "Adam Gilchrist",
    "lara": "Brian Lara",
    "dravid": "Rahul Dravid", "the wall": "Rahul Dravid",
    "sehwag": "Virender Sehwag",
    "smith": "Steve Smith",
    "williamson": "Kane Williamson",
    "root": "Joe Root",
    "babar": "Babar Azam",
    "warner": "David Warner",
    "ashwin": "Ravichandran Ashwin",
    "jadeja": "Ravindra Jadeja",
    "shakib": "Shakib Al Hasan",
    "starc": "Mitchell Starc",
    "rabada": "Kagiso Rabada",
    "rashid": "Rashid Khan",
    "pant": "Rishabh Pant",
    "buttler": "Jos Buttler",
    "maxwell": "Glenn Maxwell",
    "amla": "Hashim Amla",
    "sangakkara": "Kumar Sangakkara", "sanga": "Kumar Sangakkara",
    "jayawardene": "Mahela Jayawardene",
    "malinga": "Lasith Malinga",
    "kumble": "Anil Kumble",
    "harbhajan": "Harbhajan Singh",
    "anderson": "James Anderson", "jimmy": "James Anderson",
    "broad": "Stuart Broad",
    "flintoff": "Andrew Flintoff", "freddie": "Andrew Flintoff",
    "pollard": "Kieron Pollard",
    "russell": "Andre Russell",
    "bravo": "Dwayne Bravo",
    "afridi": "Shahid Afridi", "boom boom": "Shahid Afridi",
    "jayasuriya": "Sanath Jayasuriya",
    "dilshan": "Tillakaratne Dilshan",
    "de kock": "Quinton de Kock", "qdk": "Quinton de Kock",
    "du plessis": "Faf du Plessis", "faf": "Faf du Plessis",
    "hazlewood": "Josh Hazlewood",
    "shami": "Mohammed Shami",
    "siraj": "Mohammed Siraj",
    "sky": "Suryakumar Yadav", "surya": "Suryakumar Yadav",
    "hardik": "Hardik Pandya",
    "gill": "Shubman Gill",
    "punter": "Ricky Ponting",
    "tugga": "Steve Waugh",
    "pup": "Michael Clarke",
    "gaz": "Nathan Lyon",
    "binga": "Brett Lee",
    "huss": "Mike Hussey", "hussey": "Mike Hussey", "mr cricket": "Mike Hussey",
    "dizzy": "Jason Gillespie",
    "pigeon": "Glenn McGrath",
    "haydos": "Matthew Hayden", "hayden": "Matthew Hayden",
    "starcy": "Mitchell Starc",
    "davey": "David Warner",
    "maxi": "Glenn Maxwell",
    "smithy": "Steve Smith",
    "mitch": "Mitchell Johnson",
    "inzy": "Inzamam-ul-Haq", "inzamam": "Inzamam-ul-Haq",
    "akhtar": "Shoaib Akhtar", "shoaib": "Shoaib Akhtar",
    "waqar": "Waqar Younis",
    "kapil": "Kapil Dev",
    "ganguly": "Sourav Ganguly", "dada": "Sourav Ganguly",
    "zaheer": "Zaheer Khan",
    "lee": "Brett Lee",
    "imran": "Imran Khan",
}


def find_player_local(name, players=None):
    if players is None:
        players = load_players()
    name_lower = name.strip().lower()

    for p in players:
        if p["name"].lower() == name_lower:
            return p

    if name_lower in NICKNAMES:
        full_name = NICKNAMES[name_lower].lower()
        for p in players:
            if p["name"].lower() == full_name:
                return p

    for p in players:
        parts = p["name"].lower().split()
        if name_lower in parts:
            return p

    candidates = []
    for p in players:
        full_ratio = SequenceMatcher(None, name_lower, p["name"].lower()).ratio()
        if full_ratio > 0.75:
            candidates.append((p, full_ratio))

    if candidates:
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]

    return None


def _find_player_local_strict(name, players):
    """Like find_player_local but requires last-name match for fuzzy results."""
    name_lower = name.strip().lower()
    input_parts = name_lower.split()
    input_last = input_parts[-1] if input_parts else ""

    for p in players:
        if p["name"].lower() == name_lower:
            return p

    if name_lower in NICKNAMES:
        full_name = NICKNAMES[name_lower].lower()
        for p in players:
            if p["name"].lower() == full_name:
                return p

    for p in players:
        parts = p["name"].lower().split()
        if name_lower in parts:
            return p

    candidates = []
    for p in players:
        pname_lower = p["name"].lower()
        pname_parts = pname_lower.split()
        p_last = pname_parts[-1] if pname_parts else ""

        full_ratio = SequenceMatcher(None, name_lower, pname_lower).ratio()
        if full_ratio > 0.75:
            last_ratio = SequenceMatcher(None, input_last, p_last).ratio()
            if last_ratio > 0.8:
                candidates.append((p, full_ratio))

    if candidates:
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]

    return None


def find_player_candidates(name, players=None, max_results=3):
    if players is None:
        players = load_players()
    name_lower = name.strip().lower()

    if name_lower in NICKNAMES:
        full_name = NICKNAMES[name_lower].lower()
        for p in players:
            if p["name"].lower() == full_name:
                return [p]

    scored = []
    input_parts = name_lower.split()
    input_last = input_parts[-1] if input_parts else ""

    for p in players:
        pname = p["name"].lower()

        if pname == name_lower:
            return [p]

        if pname.startswith(name_lower) or name_lower.startswith(pname):
            scored.append((p, 0.95))
            continue

        if name_lower in pname or pname in name_lower:
            scored.append((p, 0.90))
            continue

        score = 0
        pname_parts = pname.split()
        p_last = pname_parts[-1] if pname_parts else ""

        full_ratio = SequenceMatcher(None, name_lower, pname).ratio()
        score = max(score, full_ratio)

        matching_parts = 0
        for ipart in input_parts:
            best_part_score = 0
            for ppart in pname_parts:
                pr = SequenceMatcher(None, ipart, ppart).ratio()
                best_part_score = max(best_part_score, pr)
            if best_part_score > 0.75:
                matching_parts += 1
                score = max(score, best_part_score * 0.9)

        if matching_parts >= 2:
            score = max(score, 0.85)

        if score > 0.7:
            if len(input_parts) > 1:
                last_sim = SequenceMatcher(None, input_last, p_last).ratio()
                first_sim = SequenceMatcher(None, input_parts[0], pname_parts[0]).ratio() if pname_parts else 0
                if last_sim < 0.6:
                    continue
                if last_sim < 0.85 and first_sim < 0.6:
                    continue
            scored.append((p, score))

    scored.sort(key=lambda x: -x[1])
    return [p for p, _ in scored[:max_results]]


def _search_player_espn_api(name):
    """Fallback: search via ESPN's autocomplete API."""
    url = f"https://site.web.api.espn.com/apis/common/v3/sports/cricket/cricinfo/athletes?query={requests.utils.quote(name)}&limit=5"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        athletes = data.get("items", data.get("athletes", []))
        if not athletes:
            return None, None
        search_lower = name.strip().lower()
        for a in athletes:
            a_name = (a.get("displayName") or a.get("fullName", "")).lower()
            if search_lower in a_name or a_name in search_lower:
                return str(a["id"]), None
        return str(athletes[0]["id"]), None
    except (requests.RequestException, ValueError, KeyError):
        return None, None


def search_player_espn(name):
    url = f"https://search.espncricinfo.com/ci/content/player/search.html?search={requests.utils.quote(name)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"/content/player/\d+\.html"))
        candidates = []
        for link in links:
            match = re.search(r"/player/(\d+)\.html", link["href"])
            if match:
                pid = match.group(1)
                text = link.get_text(strip=True)
                candidates.append((pid, text))
        if candidates:
            return _pick_best_candidate(candidates, name)
    except requests.RequestException:
        pass

    return _search_player_espn_api(name)


def _pick_best_candidate(candidates, search_name):
    if len(candidates) == 1:
        return candidates[0][0], None

    search_lower = search_name.strip().lower()
    search_parts = set(search_lower.split())

    all_parsed = []
    for pid, text in candidates:
        before_paren = text.split("(")[0].strip()
        if before_paren and any(c.isalpha() for c in before_paren):
            display_name = re.sub(r"\s+", " ", before_paren).strip()
        else:
            paren = re.search(r"\(([^,]+)", text)
            display_name = paren.group(1).strip() if paren else text.split("\n")[0].strip()
        name_parts = set(display_name.lower().split())
        overlap = len(search_parts & name_parts)
        name_ratio = SequenceMatcher(None, search_lower, display_name.lower()).ratio()
        all_parsed.append((pid, text, display_name, overlap, name_ratio))

    all_parsed.sort(key=lambda x: (-x[3], -x[4]))

    if not all_parsed:
        return candidates[0][0], None

    if len(all_parsed) == 1:
        return all_parsed[0][0], None

    top_overlap = all_parsed[0][3]
    tied = [x for x in all_parsed if x[3] == top_overlap]

    if len(tied) == 1:
        return tied[0][0], None

    best_pid = None
    best_matches = -1
    for pid, text, _, _, _ in tied:
        stats = _fetch_statsguru_allround(pid)
        if not stats:
            continue
        total = sum(f.get("matches", 0) for f in stats.values())
        if total > best_matches:
            best_matches = total
            best_pid = pid
        if best_matches >= 50:
            break
    if best_pid:
        return best_pid, None

    return tied[0][0], None


BAT_STYLE_MAP = {
    "lhb": "Left", "left-hand bat": "Left",
    "rhb": "Right", "right-hand bat": "Right",
}

BOWL_STYLE_MAP = {
    "right-arm fast": "Right-arm fast",
    "right-arm medium-fast": "Right-arm medium-fast",
    "right-arm fast-medium": "Right-arm medium-fast",
    "right-arm medium": "Right-arm medium",
    "left-arm fast": "Left-arm fast",
    "left-arm medium-fast": "Left-arm medium-fast",
    "left-arm fast-medium": "Left-arm medium-fast",
    "left-arm medium": "Left-arm medium",
    "right-arm offbreak": "Right-arm offbreak",
    "right-arm legbreak": "Right-arm legbreak",
    "legbreak": "Leg break",
    "legbreak googly": "Leg break googly",
    "slow left-arm orthodox": "Slow left-arm orthodox",
    "left-arm wrist spin": "Left-arm wrist spin",
    "offbreak": "Offbreak",
    "slow left-arm chinaman": "Left-arm wrist spin",
}


def _fetch_player_metadata_espn(player_id):
    url = f"https://site.web.api.espn.com/apis/common/v3/sports/cricket/cricinfo/athletes/{player_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    athlete = data.get("athlete", {})
    if not athlete:
        return None

    name = athlete.get("displayName") or athlete.get("fullName", "")

    bat_hand = "Unknown"
    for bs in athlete.get("batStyle", []):
        desc = bs.get("description", "").lower()
        bat_hand = BAT_STYLE_MAP.get(desc, bat_hand)
        if bat_hand != "Unknown":
            break

    bowl_style_str = "N/A"
    for bw in athlete.get("bowlStyle", []):
        desc = bw.get("description", "")
        bowl_style_str = BOWL_STYLE_MAP.get(desc.lower(), desc)
        break

    country = "Unknown"
    team = athlete.get("team", {})
    if team.get("displayName"):
        country = team["displayName"]

    return {
        "name": name,
        "country": country,
        "bat_hand": bat_hand,
        "bowl_style": bowl_style_str,
    }


def _fetch_statsguru_allround(player_id):
    url = f"https://stats.espncricinfo.com/ci/engine/player/{player_id}.html?class=11;template=results;type=allround"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None

    for table in soup.find_all("table"):
        caption = table.find("caption")
        if not caption or "summary" not in caption.get_text(strip=True).lower():
            continue

        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]

        formats = {}
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if not cells or not cells[0]:
                continue

            grouping = cells[0]
            fmt = None
            for fmt_key, label in FORMAT_LABELS.items():
                if grouping == label:
                    fmt = fmt_key
                    break
            if not fmt:
                continue

            def col(name):
                try:
                    idx = headers.index(name)
                    return cells[idx] if idx < len(cells) else ""
                except ValueError:
                    return ""

            formats[fmt] = {
                "matches": _to_int(col("Mat")),
                "runs": _to_int(col("Runs")),
                "bat_avg": _to_float(col("Bat Av")),
                "hundreds": _to_int(col("100")),
                "highest_score": col("HS") or "0",
                "wickets": _to_int(col("Wkts")),
                "bowl_avg": _to_float(col("Bowl Av")),
                "best_bowling": col("BBI") or "-",
                "five_wickets": _to_int(col("5")),
                "catches": _to_int(col("Ct")),
                "stumpings": _to_int(col("St")),
            }

        return formats if formats else None

    return None


def _fetch_statsguru_batting(player_id):
    url = f"https://stats.espncricinfo.com/ci/engine/player/{player_id}.html?class=11;template=results;type=batting"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return {}
        soup = BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return {}

    for table in soup.find_all("table"):
        caption = table.find("caption")
        if not caption or "summary" not in caption.get_text(strip=True).lower():
            continue

        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        result = {}
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if not cells or not cells[0]:
                continue

            fmt = None
            for fmt_key, label in FORMAT_LABELS.items():
                if cells[0] == label:
                    fmt = fmt_key
                    break
            if not fmt:
                continue

            def col(name):
                try:
                    idx = headers.index(name)
                    return cells[idx] if idx < len(cells) else ""
                except ValueError:
                    return ""

            result[fmt] = {
                "innings_bat": _to_int(col("Inns")),
                "fifties": _to_int(col("50")),
            }
        return result

    return {}


def fetch_player_profile_espn(player_id):
    metadata = _fetch_player_metadata_espn(player_id)
    if not metadata:
        return None

    allround = _fetch_statsguru_allround(player_id)

    if not allround:
        batting_extra = _fetch_statsguru_batting(player_id)
        if not batting_extra:
            return None
        allround = {}
        for fmt, extra in batting_extra.items():
            allround[fmt] = {
                "matches": 0,
                "runs": 0,
                "bat_avg": 0.0,
                "hundreds": 0,
                "highest_score": "0",
                "wickets": 0,
                "bowl_avg": 0.0,
                "best_bowling": "-",
                "five_wickets": 0,
                "catches": 0,
                "stumpings": 0,
                "innings_bat": extra.get("innings_bat", 0),
                "fifties": extra.get("fifties", 0),
                "innings_bowl": 0,
            }
    else:
        batting_extra = _fetch_statsguru_batting(player_id)
        for fmt, stats in allround.items():
            extra = batting_extra.get(fmt, {})
            stats["innings_bat"] = extra.get("innings_bat", 0)
            stats["fifties"] = extra.get("fifties", 0)
            stats.setdefault("innings_bowl", 0)

    role = _determine_role(allround, metadata["bowl_style"])

    return {
        "name": metadata["name"],
        "country": metadata["country"],
        "role": role,
        "bat_hand": metadata["bat_hand"],
        "bowl_style": metadata["bowl_style"],
        "formats": allround,
    }


def _determine_role(formats, bowl_style):
    total_runs = sum(f.get("runs", 0) for f in formats.values())
    total_wickets = sum(f.get("wickets", 0) for f in formats.values())
    total_stumpings = sum(f.get("stumpings", 0) for f in formats.values())

    if total_stumpings > 5:
        return "Wicket-keeper"
    if total_runs > 2000 and total_wickets > 100:
        return "All-rounder"
    if total_wickets > 50 and total_runs < 2000:
        return "Bowler"
    if total_runs > 1000:
        return "Batsman"
    if total_wickets > 20:
        return "Bowler"
    return "All-rounder"


def scrape_and_cache(name, game_format):
    players = load_players()
    existing = _find_player_local_strict(name, players)
    if existing and game_format in existing.get("formats", {}):
        return existing

    player_id, full_name = search_player_espn(name)
    if not player_id:
        return None

    profile = fetch_player_profile_espn(player_id)
    if not profile:
        return None

    if game_format not in profile.get("formats", {}):
        return None

    if existing:
        for fmt, stats in profile["formats"].items():
            if fmt not in existing.get("formats", {}):
                existing.setdefault("formats", {})[fmt] = stats
            else:
                existing["formats"][fmt] = stats
        if existing.get("country") == "Unknown":
            existing["country"] = profile["country"]
        if existing.get("bat_hand") == "Unknown":
            existing["bat_hand"] = profile["bat_hand"]
        if existing.get("role") == "Unknown":
            existing["role"] = profile["role"]
        if existing.get("bowl_style") in ("Unknown", "N/A") and profile["bowl_style"] not in ("Unknown", "N/A"):
            existing["bowl_style"] = profile["bowl_style"]
        save_players(players)
        return existing

    new_player = {
        "name": profile["name"],
        "country": profile["country"],
        "role": profile["role"],
        "bat_hand": profile["bat_hand"],
        "bowl_style": profile["bowl_style"],
        "formats": profile["formats"],
    }
    players.append(new_player)
    save_players(players)
    return new_player


def _to_int(val):
    try:
        return int(re.sub(r"[^\d]", "", str(val)) or "0")
    except ValueError:
        return 0


def _to_float(val):
    try:
        return float(re.sub(r"[^\d.]", "", str(val)) or "0")
    except ValueError:
        return 0.0
