if isinstance(start, str):
            try:
                start = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()
            except Exception:
                start = 0
        if isinstance(end, str):
            try:
                end = datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp()
            except Exception:
                end = float("inf")

        # price can be number, string (wei), or nested
        price = stage.get("price")
        if isinstance(price, dict):
            price = price.get("amount") or price.get("value")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None

        # free = 0 (or extremely small wei amount)
        if start <= now <= end and price is not None and price == 0:
            return True
    return False


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
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


if name == "__main__":
    main()
