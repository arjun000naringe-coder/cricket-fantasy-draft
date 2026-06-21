"""Quick eval: test persona LLM output quality — clean names vs garbage."""
from llm_client import chat, FAST_MODEL

EVAL_MODEL = "gemma3:12b"
import re
import time

CONSTRAINT = "Only select batsmen with average below 40 or bowlers with average above 30"
FORMAT = "Test"

PERSONAS = {
    "casual_observer": {
        "name": "Casual Observer",
        "prompt": (
            "You are playing a cricket fantasy draft game. You are a casual cricket fan — you "
            "watch the occasional World Cup final and know the big names, but that's about it.\n\n"
            "Your knowledge is limited to ~20 household names: Sachin Tendulkar, Virat Kohli, "
            "MS Dhoni, Ricky Ponting, Brian Lara, Shane Warne, Wasim Akram, AB de Villiers, "
            "Chris Gayle, Rohit Sharma, Jacques Kallis, Adam Gilchrist, Muttiah Muralitharan, "
            "Brett Lee, Yuvraj Singh, Kevin Pietersen, Shahid Afridi, Glenn McGrath, Kumar "
            "Sangakkara, and maybe a few more you half-remember.\n\n"
            "Behavior:\n"
            "- You always pick the most famous name you can think of first.\n"
            "- You misspell lesser-known names sometimes.\n"
            "- When a pick is rejected, you get confused and just try another famous name.\n"
            "- You sometimes type first name only or last name only.\n\n"
            "Respond with ONLY the next player name — nothing else. No explanation, no commentary, just the name."
        ),
    },
    "cricket_geek": {
        "name": "Cricket Geek",
        "prompt": (
            "You are playing a cricket fantasy draft game. You are an obsessive cricket "
            "statistician who knows deep stats and cult heroes.\n\n"
            "Behavior:\n"
            "- Read the constraint carefully and build your team around it.\n"
            "- You pick from all eras — cult heroes others forget.\n"
            "- You use full formal names.\n\n"
            "Respond with ONLY the next player name — nothing else."
        ),
    },
    "ipl_fan": {
        "name": "IPL Fan",
        "prompt": (
            "You are playing a cricket fantasy draft game. You are a massive IPL fan who "
            "started watching cricket through T20 leagues. You pick based on T20 ability "
            "regardless of the game format.\n\n"
            "Behavior:\n"
            "- You pick T20 specialists and IPL stars.\n"
            "- When the format is Test, you pick T20 specialists anyway.\n"
            "- When rejected, you try another T20 star.\n\n"
            "Respond with ONLY the next player name — nothing else."
        ),
    },
    "nineties_nostalgist": {
        "name": "90s Nostalgist",
        "prompt": (
            "You are playing a cricket fantasy draft game. You believe cricket peaked in the "
            "1990s and early 2000s. Every pick comes from that era.\n\n"
            "Behavior:\n"
            "- Pick from the 90s/early 2000s only.\n"
            "- You pick fast bowlers heavily.\n"
            "- You think about team balance classically.\n\n"
            "Respond with ONLY the next player name — nothing else."
        ),
    },
}


def is_garbage(text):
    if not text or len(text) > 60:
        return True
    if re.search(r'[0-9/():\[\]{}]', text):
        return True
    if len(text.split()) > 6:
        return True
    noise = ["innings", "wicket", "bowler", "batsmen", "scored", "average",
             "select", "constraint", "fantasy", "draft", "pick ", "analyze",
             "sorry", "here", "would", "going", "think", "choose", "next"]
    lower = text.lower()
    if any(w in lower for w in noise):
        return True
    if text.startswith(("-", "*", "•")):
        return True
    return False


def clean_response(raw):
    text = raw.strip().strip('"').strip("'").strip()
    text = re.sub(r'^[-–•*\d.]+\s*', '', text).strip()
    text = text.split("\n")[0].strip()
    text = text.rstrip(".!,;:")
    return text


print(f"Model: {EVAL_MODEL}")
print(f"Constraint: {CONSTRAINT}")
print(f"Format: {FORMAT}")
print(f"Picks per persona: 10")
print()

for pid, persona in PERSONAS.items():
    print(f"=== {persona['name']} ===")
    picked = []
    garbage_count = 0

    for i in range(10):
        picked_str = ", ".join(picked) if picked else "none yet"
        context = (
            f"Format: {FORMAT}\n"
            f"Constraint: {CONSTRAINT}\n"
            f"Already picked: {picked_str}\n"
            f"Pick #{i+1} of 11. Respond with ONLY a player name."
        )

        try:
            t = time.time()
            raw = chat(
                messages=[{"role": "user", "content": context}],
                system=persona["prompt"],
                max_tokens=40,
                model=EVAL_MODEL,
            )
            elapsed = time.time() - t
            cleaned = clean_response(raw)
            garbage = is_garbage(cleaned)

            status = "GARBAGE" if garbage else "OK"
            if garbage:
                garbage_count += 1
            else:
                picked.append(cleaned)

            raw_preview = repr(raw.strip()[:70])
            print(f"  [{i+1:2d}] {status:7s} {elapsed:.1f}s  raw={raw_preview}")
        except Exception as e:
            garbage_count += 1
            print(f"  [{i+1:2d}] ERROR   {e}")

    print(f"  >> {10 - garbage_count}/10 clean, {garbage_count}/10 garbage")
    print()
