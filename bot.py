import json
import os
import time
from datetime import datetime

import requests

CHAIN = "robinhood"
SEEN_FILE = "seen.json"
MIN_FLOOR_USD = float(os.getenv("MIN_FLOOR_USD", "0"))
OPENSEA_API_KEY = os.getenv("OPENSEA_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

OPENSEA_BASE_URL = "https://api.opensea.io/api/v2"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
TOKEN_IDS = {"eth": "ethereum", "weth": "weth", "matic": "matic-network"}


def opensea_get(path: str, params=None):
    headers = {"accept": "application/json"}
    if OPENSEA_API_KEY:
        headers["x-api-key"] = OPENSEA_API_KEY

    try:
        resp = requests.get(
            f"{OPENSEA_BASE_URL}{path}",
            headers=headers,
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        print(f"OpenSea request failed for {path}: {exc}")
        return None

    if resp.status_code != 200:
        print(f"OpenSea API returned {resp.status_code} for {path}")
        return None

    try:
        return resp.json()
    except ValueError:
        print(f"OpenSea API returned invalid JSON for {path}")
        return None


def list_chain_collections(chain: str):
    payload = opensea_get("/collections", params={"chain": chain, "limit": 100})
    if not isinstance(payload, dict):
        return []
    collections = payload.get("collections")
    return collections if isinstance(collections, list) else []


def get_collection_stats(slug: str):
    payload = opensea_get(f"/collections/{slug}/stats")
    return payload if isinstance(payload, dict) else None


def get_native_token_price_usd(symbol: str):
    token_id = TOKEN_IDS.get((symbol or "").lower())
    if not token_id:
        return 0.0

    try:
        resp = requests.get(
            COINGECKO_URL,
            params={"ids": token_id, "vs_currencies": "usd"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return 0.0

    usd = data.get(token_id, {}).get("usd")
    return float(usd) if isinstance(usd, (int, float)) else 0.0


def is_free_mint_live(slug: str):
    payload = opensea_get(f"/collections/{slug}")
    if not isinstance(payload, dict):
        return False

    stages = payload.get("mint_stages") or payload.get("stages") or []
    if not isinstance(stages, list):
        return False

    now = time.time()
    for stage in stages:
        if not isinstance(stage, dict):
            continue

        start = stage.get("start_time") or stage.get("startDate") or stage.get("start") or 0
        end = stage.get("end_time") or stage.get("endDate") or stage.get("end") or float("inf")

        if isinstance(start, str):
            try:
                start = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()
            except ValueError:
                start = 0
        if isinstance(end, str):
            try:
                end = datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp()
            except ValueError:
                end = float("inf")

        price = stage.get("price")
        if isinstance(price, dict):
            price = price.get("amount") or price.get("value")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None

        if start <= now <= end and price is not None and price == 0:
            return True
    return False


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set()
    return set(data) if isinstance(data, list) else set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials are not configured; skipping notification.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"Telegram send failed: {exc}")
        return

    if resp.status_code != 200:
        print(f"Telegram send failed: {resp.status_code} {resp.text[:200]}")


def main():
    seen = load_seen()
    new_seen = set(seen)

    collections = list_chain_collections(CHAIN)
    print(f"Found {len(collections)} collections on {CHAIN}")

    alerts = []
    for c in collections:
        slug = c.get("collection") or c.get("slug")
        name = c.get("name", slug)
        if not slug or slug in seen:
            continue

        if not is_free_mint_live(slug):
            continue

        stats = get_collection_stats(slug)
        if not stats:
            continue

        total = stats.get("total", {})
        floor = total.get("floor_price")
        floor_symbol = total.get("floor_price_symbol", "eth")
        if floor is None:
            continue

        try:
            floor = float(floor)
        except (TypeError, ValueError):
            continue

        token_price_usd = get_native_token_price_usd(floor_symbol)
        floor_usd = floor * token_price_usd if token_price_usd else 0.0

        if floor_usd >= MIN_FLOOR_USD:
            alerts.append((name, slug, floor, floor_symbol, floor_usd))
            new_seen.add(slug)

        time.sleep(0.35)

    if alerts:
        for name, slug, floor, symbol, floor_usd in alerts:
            msg = (
                f"🟢 *Free mint live on Robinhood Chain*\n"
                f"*{name}*\n"
                f"Floor: {floor} {symbol.upper()} (~${floor_usd:.2f})\n"
                f"https://opensea.io/collection/{slug}"
            )
            send_telegram(msg)
            time.sleep(1)
        print(f"Sent {len(alerts)} alert(s)")
    else:
        print("No qualifying new collections this run.")

    save_seen(new_seen)


if __name__ == "__main__":
    main()
