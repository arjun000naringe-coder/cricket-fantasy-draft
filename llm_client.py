import os
import requests

OLLAMA_BASE_URL = "https://api.ollama.com"
FAST_MODEL = "minimax-m3:cloud"
HEAVY_MODEL = "kimi-k2.5:cloud"
FALLBACK_MODEL = "minimax-m2.7:cloud"


CONFIG_PATH = os.path.join(os.path.dirname(__file__), ".env")


def _get_api_key():
    key = os.environ.get("OLLAMA_API_KEY", "")
    if key:
        return key
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("OLLAMA_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError(
        "OLLAMA_API_KEY not set. Either:\n"
        "  1) Run: export OLLAMA_API_KEY='your-key-here'\n"
        f"  2) Create {CONFIG_PATH} with: OLLAMA_API_KEY=your-key-here"
    )


def _get_headers():
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
    }


def chat(messages, system=None, max_tokens=1000, model=None):
    model = model or FAST_MODEL
    if model == HEAVY_MODEL:
        token_budget = max(max_tokens * 8, 4000)
    else:
        token_budget = max(max_tokens * 4, 2000)

    ollama_messages = []
    if system:
        ollama_messages.append({"role": "system", "content": system})
    ollama_messages.extend(messages)

    payload = {
        "model": model,
        "messages": ollama_messages,
        "stream": False,
        "options": {"num_predict": token_budget},
    }

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            headers=_get_headers(),
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        if os.environ.get("DEBUG"):
            print(f"  [DEBUG] Status: {resp.status_code}")
            print(f"  [DEBUG] Done reason: {data.get('done_reason')}")
            content = data.get("message", {}).get("content", "")
            thinking = data.get("message", {}).get("thinking", "")
            print(f"  [DEBUG] Content length: {len(content)}")
            print(f"  [DEBUG] Thinking length: {len(thinking)}")
            if content:
                print(f"  [DEBUG] Content preview: {content[:200]}")

        msg = data.get("message", {})
        content = msg.get("content", "").strip()
        if content:
            return content
        # Some reasoning models put the answer in thinking when content is empty
        thinking = msg.get("thinking", "").strip()
        if thinking:
            return thinking
        return ""
    except Exception as e:
        if model != FALLBACK_MODEL:
            print(f"  Primary model failed ({e}), trying fallback...")
            return chat(messages, system=system, max_tokens=max_tokens, model=FALLBACK_MODEL)
        raise
