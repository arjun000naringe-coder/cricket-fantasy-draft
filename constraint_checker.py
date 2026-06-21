import re


SUBCONTINENT = {"india", "pakistan", "sri lanka", "bangladesh", "afghanistan", "nepal"}
SENA = {"south africa", "england", "new zealand", "australia"}
ASIA = {"india", "pakistan", "sri lanka", "bangladesh", "afghanistan", "nepal"}
CARIBBEAN = {"west indies", "windies"}
AFRICA = {"south africa", "zimbabwe", "kenya", "namibia"}
OCEANIA = {"australia", "new zealand"}
SOUTHERN_HEMISPHERE = OCEANIA | AFRICA | {"south africa", "zimbabwe", "kenya", "namibia", "west indies"}
WORLD_CUP_WINNERS_ODI = {"india", "australia", "west indies", "pakistan", "sri lanka", "england"}
WORLD_CUP_WINNERS_T20 = {"india", "australia", "west indies", "pakistan", "sri lanka", "england"}

PACE_KEYWORDS = {"fast", "medium-fast", "fast-medium", "medium", "right-arm fast", "left-arm fast",
                 "right-arm medium", "left-arm medium", "right-arm fast-medium", "left-arm fast-medium",
                 "right-arm medium-fast", "left-arm medium-fast"}
SPIN_KEYWORDS = {"spin", "leg break", "off break", "left-arm orthodox", "left-arm unorthodox",
                 "left-arm wrist spin", "right-arm leg break", "slow left-arm orthodox",
                 "right-arm off break", "left-arm chinaman"}


def _is_pace(bowl_style):
    if not bowl_style:
        return False
    lower = bowl_style.lower()
    if any(k in lower for k in ("fast", "medium", "seam", "pace")):
        if not any(k in lower for k in ("spin", "leg break", "off break", "orthodox")):
            return True
    return False


def _is_spin(bowl_style):
    if not bowl_style:
        return False
    lower = bowl_style.lower()
    return any(k in lower for k in ("spin", "leg break", "off break", "orthodox", "chinaman", "wrist spin"))


def _is_left_arm(bowl_style):
    if not bowl_style:
        return False
    return "left" in bowl_style.lower()


def _is_right_arm(bowl_style):
    if not bowl_style:
        return False
    return "right" in bowl_style.lower()


def _country_lower(player):
    return (player.get("country") or "").strip().lower()


def _role_lower(player):
    return (player.get("role") or "").strip().lower()


def _bat_hand(player):
    return (player.get("bat_hand") or "").strip().lower()


def _bowl_style(player):
    return (player.get("bowl_style") or "").strip().lower()


def _stats(player, game_format):
    return player.get("formats", {}).get(game_format, {})


def _in_region(country, region_name):
    c = country.lower().strip()
    region_name = region_name.lower().strip()
    if region_name in ("subcontinent", "the subcontinent", "subcontinental"):
        return c in SUBCONTINENT
    if region_name in ("sena", "sena countries"):
        return c in SENA
    if region_name in ("asia", "asian countries"):
        return c in ASIA
    if region_name in ("caribbean", "the caribbean", "west indies"):
        return c in CARIBBEAN or c == "west indies"
    if region_name in ("africa",):
        return c in AFRICA
    if region_name in ("oceania",):
        return c in OCEANIA
    if region_name in ("southern hemisphere", "the southern hemisphere"):
        return c in SOUTHERN_HEMISPHERE
    return False


def _country_matches(country, text):
    c = country.lower().strip()
    text = text.lower().strip()
    if c == text:
        return True
    if text == "south africa" and c == "south africa":
        return True
    if text == "new zealand" and c == "new zealand":
        return True
    if text in ("west indies", "windies", "caribbean") and c in ("west indies",):
        return True
    return c == text


def _is_role(player, role_text):
    role = _role_lower(player)
    rt = role_text.lower().strip()

    if rt in ("batsman", "batsmen", "batter", "batters"):
        return role in ("batsman", "top-order batsman", "opening batsman", "middle-order batsman")
    if rt in ("bowler", "bowlers"):
        return role == "bowler"
    if rt in ("pace bowler", "pace bowlers", "fast bowler", "fast bowlers", "pacer", "pacers"):
        return role == "bowler" and _is_pace(player.get("bowl_style"))
    if rt in ("spin bowler", "spin bowlers", "spinner", "spinners"):
        return role == "bowler" and _is_spin(player.get("bowl_style"))
    if rt in ("all-rounder", "all-rounders", "allrounder", "allrounders"):
        return role == "all-rounder"
    if rt in ("wicket-keeper", "wicket-keepers", "keeper", "keepers", "wicketkeeper"):
        return role in ("wicket-keeper", "wicket-keeper batsman")
    return False


# --- Rule extractors ---

def _try_stat_threshold(constraint, player, fmt, game_format):
    """Check stat-based thresholds like 'batting average above 40', 'runs >= 3000', 'wickets below 30'."""
    stats = _stats(player, game_format)
    if not stats:
        return None

    patterns = [
        (r"batting average (?:above|over|greater than|more than|at least|>=?)\s*([\d.]+)", "bat_avg", ">="),
        (r"batting average (?:below|under|less than|<=?)\s*([\d.]+)", "bat_avg", "<="),
        (r"bowling average (?:above|over|greater than|more than|at least|>=?)\s*([\d.]+)", "bowl_avg", ">="),
        (r"bowling average (?:below|under|less than|<=?)\s*([\d.]+)", "bowl_avg", "<="),
        (r"(\d+)\+?\s*(?:test |odi |t20i )?(?:matches|caps)", "matches", ">="),
        (r"(?:played|at least)\s*(\d+)\+?\s*(?:test |odi |t20i )?(?:matches|caps)", "matches", ">="),
        (r"(\d+)\+?\s*(?:test |odi |t20i )?runs", "runs", ">="),
        (r"(\d+)\+?\s*(?:test |odi |t20i )?wickets", "wickets", ">="),
        (r"(\d+)\+?\s*(?:test |odi |t20i )?centuries|(\d+)\+?\s*(?:test |odi |t20i )?(?:hundreds|100s)", "hundreds", ">="),
        (r"(\d+)\+?\s*(?:test |odi |t20i )?(?:fifties|50s)", "fifties", ">="),
        (r"(\d+)\+?\s*(?:test |odi |t20i )?catches", "catches", ">="),
        (r"(\d+)\+?\s*(?:test |odi |t20i )?stumpings", "stumpings", ">="),
        (r"(\d+)\+?\s*(?:test |odi |t20i )?(?:five.?wicket|5.?wicket|5w)", "five_wickets", ">="),
        (r"at least (\d+)\s*(?:test |odi |t20i )?(?:centuries|hundreds|100s)", "hundreds", ">="),
        (r"at least (\d+)\s*(?:test |odi |t20i )?(?:runs)", "runs", ">="),
        (r"at least (\d+)\s*(?:test |odi |t20i )?(?:wickets)", "wickets", ">="),
        (r"at least (\d+)\s*(?:test |odi |t20i )?(?:catches)", "catches", ">="),
        (r"at least (\d+)\s*(?:test |odi |t20i )?(?:ducks)", "ducks", ">="),
    ]

    cl = constraint.lower()
    results = []
    for pattern, stat_key, op in patterns:
        m = re.search(pattern, cl)
        if m:
            val = float(m.group(1) if m.group(1) else m.group(2))
            stat_val = stats.get(stat_key)
            if stat_val is None:
                continue
            if op == ">=" and stat_val >= val:
                results.append(True)
            elif op == "<=" and stat_val <= val:
                results.append(True)
            else:
                results.append(False)

    return results if results else None


def _check_country_filter(constraint, player):
    """Check country/region inclusion/exclusion."""
    cl = constraint.lower()
    country = _country_lower(player)

    not_from = re.search(r"not from ([\w\s,]+?)(?:\s*[-—]|$)", cl)
    if not_from:
        excluded = [c.strip() for c in not_from.group(1).replace(" or ", ",").replace(" and ", ",").split(",")]
        for exc in excluded:
            if _country_matches(country, exc):
                return False, f"{player['name']} is from {player.get('country')}"
        return True, "Country not excluded"

    from_match = re.search(r"from (?:the )?(subcontinent|sena|asia|caribbean|the caribbean|africa|oceania|southern hemisphere|outside [\w\s]+)", cl)
    if from_match:
        region = from_match.group(1)
        if region.startswith("outside "):
            inner = region[8:].strip()
            if _in_region(country, inner):
                return False, f"{player['name']} is from {player.get('country')}"
            return True, "Country outside excluded region"
        else:
            if _in_region(country, region):
                return True, "Country in region"
            return False, f"{player['name']} is from {player.get('country')}, not from {region}"

    from_countries = re.search(r"from ([\w\s,]+?)(?:\s*\(|$)", cl)
    if from_countries and "not from" not in cl:
        countries = [c.strip() for c in from_countries.group(1).replace(" or ", ",").replace(" and ", ",").split(",")]
        for c in countries:
            if _country_matches(country, c):
                return True, f"From {player.get('country')}"
        return False, f"{player['name']} is from {player.get('country')}"

    return None, None


def _check_handedness(constraint, player):
    """Check left/right hand batting or bowling."""
    cl = constraint.lower()

    if "left-handed batsmen" in cl or "left-handed batsman" in cl:
        if _bat_hand(player) == "left":
            return True, "Left-handed batsman"
    if "right-handed batsmen" in cl or "right-handed batsman" in cl:
        if _bat_hand(player) == "right":
            return True, "Right-handed batsman"
    if "left-arm bowler" in cl or "left-arm bowlers" in cl:
        if _is_left_arm(player.get("bowl_style")):
            return True, "Left-arm bowler"
    if "right-arm" in cl and ("bowler" in cl or "fast" in cl):
        if _is_right_arm(player.get("bowl_style")):
            return True, "Right-arm bowler"

    if "no lefties" in cl:
        if _bat_hand(player) == "left" or _is_left_arm(player.get("bowl_style")):
            return False, "Left-handed/left-arm not allowed"
        return True, "Right-handed/right-arm"

    return None, None


def _check_role_filter(constraint, player):
    """Check pure role filters like 'only select all-rounders and wicket-keepers'."""
    cl = constraint.lower()

    role_only = re.search(r"only select (all-rounders|wicket-keepers|spin bowlers|pace bowlers|fast bowlers)(?: and (all-rounders|wicket-keepers|spin bowlers|pace bowlers|fast bowlers))?(?:\s*[-—])", cl)
    if role_only:
        allowed = [role_only.group(1)]
        if role_only.group(2):
            allowed.append(role_only.group(2))
        for role_text in allowed:
            if _is_role(player, role_text):
                return True, f"Role matches: {role_text}"
        return False, f"{player['name']} ({player.get('role')}) doesn't match required roles"

    if "no specialist batsmen or bowlers" in cl:
        role = _role_lower(player)
        if role in ("all-rounder", "wicket-keeper", "wicket-keeper batsman"):
            return True, "All-rounder or wicket-keeper"
        return False, f"{player['name']} is a specialist {player.get('role')}"

    return None, None


def _split_or_constraint(constraint):
    """Split on uppercase ' OR ' only — lowercase 'or' is part of a single condition."""
    for m in re.finditer(r"\s+OR\s+", constraint):
        part_a = constraint[:m.start()].strip()
        part_b = constraint[m.end():].strip()
        return part_a, part_b
    return None


def _split_and_constraint(constraint):
    """Split on uppercase ' AND ' only — lowercase 'and' is part of a single condition."""
    for m in re.finditer(r"\s+AND\s+", constraint):
        part_a = constraint[:m.start()].strip()
        part_b = constraint[m.end():].strip()
        return part_a, part_b
    return None


def validate_constraint(player, constraint, game_format):
    """
    Try to validate programmatically. Returns (is_valid, reason) or None if can't determine.
    None means "fall back to LLM".
    """
    cl = constraint.lower()
    stats = _stats(player, game_format)

    # Venue/match-context constraints need LLM
    if re.search(r"in (australia|england|india|asia|a world cup|a losing cause|lord's|a [\w]+ match)", cl):
        return None
    if re.search(r"against (india|australia|england|pakistan|south africa|at least \d+ different)", cl):
        return None
    if re.search(r"(man of the match|on debut|world cup|semi.?final|knockout)", cl):
        return None

    # --- Handle OR constraints ---
    or_parts = _split_or_constraint(constraint)
    if or_parts:
        a_result = _validate_single_condition(or_parts[0], player, game_format, stats)
        if a_result is True:
            return True, "Meets first condition"
        b_result = _validate_single_condition(or_parts[1], player, game_format, stats)
        if b_result is True:
            return True, "Meets second condition"
        if a_result is False and b_result is False:
            return False, f"{player['name']} doesn't meet either condition"
        # One or both returned None (couldn't determine) — fall back to LLM
        return None

    # --- Handle AND constraints ---
    and_parts = _split_and_constraint(constraint)
    if and_parts:
        a_result = _validate_single_condition(and_parts[0], player, game_format, stats)
        b_result = _validate_single_condition(and_parts[1], player, game_format, stats)
        if a_result is False or b_result is False:
            return False, f"{player['name']} doesn't meet both conditions"
        if a_result is True and b_result is True:
            return True, "Meets both conditions"
        return None

    # --- Single condition ---
    result = _validate_single_condition(constraint, player, game_format, stats)
    if result is True:
        return True, "Meets constraint"
    if result is False:
        return False, f"{player['name']} doesn't meet the constraint"
    return None


def _validate_single_condition(condition, player, game_format, stats):
    """Validate a single (non-compound) condition. Returns True, False, or None."""
    cl = condition.lower().strip()

    # Country/region filter
    country_result, _ = _check_country_filter(condition, player)
    if country_result is not None:
        return country_result

    # Handedness
    hand_result, _ = _check_handedness(condition, player)
    if hand_result is not None:
        return hand_result

    # Role filter
    role_result, _ = _check_role_filter(condition, player)
    if role_result is not None:
        return role_result

    if not stats:
        return None

    # Role-qualified stat: "bowlers with bowling average above 30" (must be before plain stat checks)
    m = re.search(r"(bowlers?|pace bowlers?|fast bowlers?) with bowling average (above|over|below|under)\s*([\d.]+)", cl)
    if m:
        role_text, direction, threshold = m.group(1), m.group(2), float(m.group(3))
        if not _is_role(player, role_text):
            return False
        avg = stats.get("bowl_avg")
        if avg is None or avg == 0:
            return False
        if direction in ("above", "over"):
            return avg >= threshold
        return avg <= threshold

    m = re.search(r"(bowlers?|pace bowlers?) with (\d+)\+?\s*(?:test |odi |t20i )?wickets", cl)
    if m:
        if not _is_role(player, m.group(1)):
            return False
        return stats.get("wickets", 0) >= int(m.group(2))

    # Role-qualified stat: "batsmen with batting average below 35"
    m = re.search(r"(batsmen|batsman|batter) with batting average (above|over|below|under)\s*([\d.]+)", cl)
    if m:
        role_text, direction, threshold = m.group(1), m.group(2), float(m.group(3))
        if not _is_role(player, role_text):
            return False
        avg = stats.get("bat_avg")
        if avg is None:
            return False
        if direction in ("above", "over"):
            return avg >= threshold
        return avg <= threshold

    # Stat: matches threshold
    m = re.search(r"(?:played\s+)?(\d+)\+?\s*(?:test |odi |t20i )?(?:matches|caps)", cl)
    if m:
        return stats.get("matches", 0) >= int(m.group(1))

    # Stat: runs threshold
    m = re.search(r"(\d+)\+?\s*(?:test |odi |t20i )?runs", cl)
    if m:
        return stats.get("runs", 0) >= int(m.group(1))

    # Stat: wickets threshold
    m = re.search(r"(\d+)\+?\s*(?:test |odi |t20i )?wickets", cl)
    if m:
        return stats.get("wickets", 0) >= int(m.group(1))

    # Stat: centuries
    m = re.search(r"(?:at least\s+)?(\d+)\+?\s*(?:test |odi |t20i )?(?:century|centuries|hundreds|100s)", cl)
    if m:
        return stats.get("hundreds", 0) >= int(m.group(1))

    # Stat: scored a century (at least 1)
    if re.search(r"scored a (?:test |odi |t20i )?century", cl):
        return stats.get("hundreds", 0) >= 1

    # Stat: fifties
    m = re.search(r"(?:at least\s+)?(\d+)\+?\s*(?:test |odi |t20i )?(?:fifties|50s)", cl)
    if m:
        return stats.get("fifties", 0) >= int(m.group(1))

    # Stat: scored a fifty (at least 1)
    if re.search(r"scored (?:a |at least one )(?:test |odi |t20i )?fifty", cl):
        return stats.get("fifties", 0) >= 1

    # Stat: taken a 5-wicket haul
    if re.search(r"taken a (?:test |odi |t20i )?(?:5-wicket|five-wicket|5 wicket) haul", cl):
        return stats.get("five_wickets", 0) >= 1

    # Stat: taken 5+ wickets in an innings
    if re.search(r"taken (?:at least )?5\+? wickets in (?:a |an |a single )?(?:test )?innings", cl):
        return stats.get("five_wickets", 0) >= 1

    # Stat: batting average above/below
    m = re.search(r"batting average (?:above|over|at least|>=?)\s*([\d.]+)", cl)
    if m:
        avg = stats.get("bat_avg")
        return avg is not None and avg >= float(m.group(1))

    m = re.search(r"batting average (?:below|under|less than|<=?)\s*([\d.]+)", cl)
    if m:
        avg = stats.get("bat_avg")
        return avg is not None and avg <= float(m.group(1))

    # Stat: bowling average above/below
    m = re.search(r"bowling average (?:above|over|at least|>=?)\s*([\d.]+)", cl)
    if m:
        avg = stats.get("bowl_avg")
        if avg is None or avg == 0:
            return None
        return avg >= float(m.group(1))

    m = re.search(r"bowling average (?:below|under|less than|<=?)\s*([\d.]+)", cl)
    if m:
        avg = stats.get("bowl_avg")
        if avg is None or avg == 0:
            return None
        return avg <= float(m.group(1))

    # Stat: catches
    m = re.search(r"(?:at least\s+)?(\d+)\+?\s*(?:test |odi |t20i )?(?:catch(?:es)?)", cl)
    if m:
        return stats.get("catches", 0) >= int(m.group(1))

    # Stat: stumpings
    m = re.search(r"(\d+)\+?\s*(?:test |odi |t20i )?stumpings", cl)
    if m:
        return stats.get("stumpings", 0) >= int(m.group(1))

    # Stat: at least 1 wicket
    if re.search(r"at least (?:one|1)\s*(?:test |odi |t20i )?wicket", cl):
        return stats.get("wickets", 0) >= 1

    # Stat: at least X runs
    m = re.search(r"at least\s+(\d+)\s*(?:test |odi |t20i )?runs", cl)
    if m:
        return stats.get("runs", 0) >= int(m.group(1))

    # Role checks embedded in condition
    if re.search(r"^(?:only select |only )?(?:pace |fast )?bowlers", cl):
        role = _role_lower(player)
        if "pace" in cl or "fast" in cl:
            return role == "bowler" and _is_pace(player.get("bowl_style"))
        return role == "bowler"

    if re.search(r"^(?:only select |only )?spin bowlers", cl):
        return _role_lower(player) == "bowler" and _is_spin(player.get("bowl_style"))

    if re.search(r"^(?:only select |only )?(?:batsmen|batsman|batter)", cl):
        return _is_role(player, "batsman")

    if re.search(r"^(?:only select |only )?all-rounders", cl):
        return _is_role(player, "all-rounder")

    if re.search(r"^(?:only select |only )?wicket-keepers", cl):
        return _is_role(player, "wicket-keeper")

    # Left-handed batsmen
    if "left-handed" in cl and ("batsmen" in cl or "batsman" in cl):
        return _bat_hand(player) == "left"

    # Right-handed batsmen
    if "right-handed" in cl and ("batsmen" in cl or "batsman" in cl):
        return _bat_hand(player) == "right"

    # Left-arm bowlers
    if "left-arm" in cl and ("bowler" in cl or "bowlers" in cl):
        return _is_left_arm(player.get("bowl_style"))

    # Right-arm bowlers
    if "right-arm" in cl and ("bowler" in cl or "bowlers" in cl or "fast" in cl or "pace" in cl):
        return _is_right_arm(player.get("bowl_style"))

    # Pace bowlers from region
    m = re.search(r"pace bowlers? from (?:the )?([\w\s]+?)(?:\s+or\s+|$)", cl)
    if m:
        region = m.group(1).strip()
        if _is_role(player, "pace bowler"):
            return _in_region(_country_lower(player), region) or _country_matches(_country_lower(player), region)

    # Spin bowlers from region
    m = re.search(r"spin bowlers? from (?:the |outside )?([\w\s]+?)(?:\s+or\s+|$)", cl)
    if m:
        region = m.group(1).strip()
        outside = "outside" in cl[:cl.find(m.group(1))]
        if _is_role(player, "spin bowler"):
            in_region = _in_region(_country_lower(player), region) or _country_matches(_country_lower(player), region)
            return not in_region if outside else in_region

    # Can't determine — return None for LLM fallback
    return None
