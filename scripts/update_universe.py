import argparse
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai


KST = ZoneInfo("Asia/Seoul")
UNIVERSE_PATH = "data/universe/stock_universe.json"
MAX_DIVIDEND = 120
MAX_QUALITY = 100
MAX_THEME_PER_GROUP = 14


def now_kst():
    return datetime.now(KST)


def load_universe():
    with open(UNIVERSE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_universe(universe):
    os.makedirs(os.path.dirname(UNIVERSE_PATH), exist_ok=True)
    with open(UNIVERSE_PATH, "w", encoding="utf-8") as f:
        json.dump(universe, f, ensure_ascii=False, indent=2)
        f.write("\n")


def normalize_symbol(symbol):
    symbol = str(symbol).strip().upper()
    if re.fullmatch(r"[A-Z0-9.-]{1,10}", symbol):
        return symbol
    return ""


def dedupe_symbols(symbols, limit):
    result = []
    seen = set()
    for symbol in symbols or []:
        normalized = normalize_symbol(symbol)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
        if len(result) >= limit:
            break
    return result


def sanitize_update(current, proposed):
    sanitized = dict(current)
    if proposed.get("dividend"):
        dividend = dedupe_symbols(proposed["dividend"], MAX_DIVIDEND)
        if len(dividend) >= 50:
            sanitized["dividend"] = dividend

    if proposed.get("quality"):
        quality = dedupe_symbols(proposed["quality"], MAX_QUALITY)
        if len(quality) >= 40:
            sanitized["quality"] = quality

    if proposed.get("theme"):
        theme = {}
        for name, symbols in proposed["theme"].items():
            clean_name = str(name).strip()[:40]
            clean_symbols = dedupe_symbols(symbols, MAX_THEME_PER_GROUP)
            if clean_name and len(clean_symbols) >= 5:
                theme[clean_name] = clean_symbols
        if len(theme) >= 5:
            sanitized["theme"] = theme

    sanitized["updated_at"] = now_kst().strftime("%Y-%m-%d %H:%M KST")
    sanitized["version"] = int(current.get("version", 1)) + 1
    return sanitized


def select_modes(mode):
    if mode != "auto":
        return [mode]

    today = now_kst()
    modes = ["theme"]
    if today.day <= 7:
        modes.append("dividend")
    if today.day <= 7 and today.month in {1, 4, 7, 10}:
        modes.append("quality")
    return modes


def build_prompt(current, modes):
    return f"""
You maintain ticker universes for a daily stock briefing.

Refresh only these universe sections: {', '.join(modes)}.
Keep the universe practical for a free-API workflow: avoid excessive breadth, penny stocks, thinly traded names, and highly speculative micro-caps.

Rules:
- Return ONLY valid JSON.
- Keep existing good tickers unless there is a clear reason to replace them.
- Dividend universe: global high-yield cash-flow names, BDCs, REITs, MLPs, CEFs, covered-call ETFs, telecoms, utilities, energy income names.
- Theme universe: group tickers by current investable themes; each group should have 5 to {MAX_THEME_PER_GROUP} tickers.
- Quality universe: 3+ year holding candidates with durable profitability, cash flow, balance-sheet quality, and competitive position.
- Use US-listed tickers or liquid ADR/ETF symbols only.

Current universe:
{json.dumps(current, ensure_ascii=False)}

Expected JSON shape:
{{
  "dividend": ["ARCC", "MAIN"],
  "theme": {{
    "AI/semiconductor": ["NVDA", "AVGO"]
  }},
  "quality": ["MSFT", "COST"]
}}
"""


def refresh_universe(current, modes, api_key):
    if not api_key:
        print("GEMINI_API_KEY 없음 — universe 업데이트 생략")
        return current

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=build_prompt(current, modes),
    )
    raw = response.text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("Gemini response did not contain a JSON object")

    proposed = json.loads(match.group())
    filtered = {mode: proposed.get(mode) for mode in modes if proposed.get(mode)}
    return sanitize_update(current, filtered)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["auto", "theme", "dividend", "quality"], default="auto")
    args = parser.parse_args()

    current = load_universe()
    modes = select_modes(args.mode)
    updated = refresh_universe(current, modes, os.getenv("GEMINI_API_KEY"))
    if updated != current:
        save_universe(updated)
        print(f"universe updated: {', '.join(modes)}")
    else:
        print("universe unchanged")


if __name__ == "__main__":
    main()
