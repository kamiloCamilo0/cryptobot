import os, re, json, html
import feedparser
import requests

TOKEN = os.environ["TG_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]

# ============ الإعدادات (عدّل هنا فقط) ============
COINS = {
    "BTC": (["bitcoin", "btc"], "bitcoin"),
    "ETH": (["ethereum", "ether", "eth"], "ethereum"),
    "SOL": (["solana", "sol"], "solana"),
    # "XRP": (["xrp", "ripple"], "ripple"),
}

FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://bitcoinmagazine.com/feed",
    "https://cryptoslate.com/feed/",
]

MAX_PER_RUN = 10
SHOW_PRICE = True
SHOW_SUMMARY = True

IMPORTANT = ["hack", "exploit", "stolen", "sec ", "etf", "lawsuit", "ban",
             "approval", "approved", "delist", "listing", "outage", "bankrupt",
             "regulation", "fed ", "rate cut", "rate hike", "liquidat"]

MUTE = ["sponsored", "price prediction", "how to buy", "giveaway", "airdrop guide"]

BULLISH = ["surge", "soar", "rally", "jump", "gain", "approve", "approval", "adopt",
           "record high", "all-time high", "ath", "inflow", "bullish", "breakout",
           "partnership", "upgrade", "launch"]
BEARISH = ["crash", "plunge", "drop", "fall", "slump", "hack", "exploit", "stolen",
           "ban", "lawsuit", "sue", "outflow", "bearish", "liquidat", "sell-off",
           "selloff", "bankrupt", "fraud", "delist", "outage", "decline"]
# ==================================================

SEEN_FILE = "seen.json"


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-3000:], f)


def clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def match_coins(text):
    found = []
    for coin, (words, _) in COINS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE):
                found.append(coin)
                break
    return found


def sentiment(text):
    t = text.lower()
    bull = sum(1 for w in BULLISH if w in t)
    bear = sum(1 for w in BEARISH if w in t)
    if bull > bear:
        return "🟢 إيجابي"
    if bear > bull:
        return "🔴 سلبي"
    return "⚪ محايد"


def is_important(text):
    t = text.lower() + " "
    return any(w in t for w in IMPORTANT)


def translate_ar(text):
    if not text:
        return ""
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "en", "tl": "ar", "dt": "t", "q": text},
            timeout=15,
        )
        r.raise_for_status()
        return "".join(p[0] for p in r.json()[0] if p[0])
    except Exception:
        return text


def short_summary(summary, title):
    s = summary
    if s.lower().startswith(title.lower()[:30]):
        return ""
    if len(s) > 220:
        s = s[:220].rsplit(" ", 1)[0] + "…"
    return s


def get_prices(coins):
    ids = [COINS[c][1] for c in coins]
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(ids), "vs_currencies": "usd",
                    "include_24hr_change": "true"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def price_line(coins, prices):
    parts = []
    for c in coins:
        d = prices.get(COINS[c][1])
        if d and "usd" in d:
            ch = d.get("usd_24h_change")
            arrow = "" if ch is None else f" ({ch:+.1f}%)"
            parts.append(f"{c}: ${d['usd']:,.2f}{arrow}")
    return "💰 " + " | ".join(parts) if parts else ""


def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML",
              "disable_web_page_preview": "false"},
        timeout=15,
    )


def main():
    seen = load_seen()
    pending, titles_now = [], set()

    for url in FEEDS:
        feed = feedparser.parse(url)
        source = clean(feed.feed.get("title", "")) or url
        for e in feed.entries:
            uid = e.get("id") or e.link
            if uid in seen:
                continue
            title = clean(e.title)
            summary = clean(e.get("summary", ""))
            text = f"{title} {summary}"
            low = text.lower()

            key = re.sub(r"\W+", "", title.lower())[:50]
            coins = match_coins(text)
            if not coins or any(m in low for m in MUTE) or key in titles_now:
                seen.add(uid)
                continue
            titles_now.add(key)
            pending.append((uid, coins, title, summary, e.link, source))

    batch = pending[:MAX_PER_RUN]
    prices = get_prices({c for _, cs, *_ in batch for c in cs}) if (SHOW_PRICE and batch) else {}

    for uid, coins, title, summary, link, source in batch:
        text = f"{title} {summary}"
        head = "🚨 " if is_important(text) else "📰 "
        lines = [f"{head}<b>{' · '.join(coins)}</b>",
                 f"<b>{html.escape(translate_ar(title))}</b>"]
        if SHOW_SUMMARY:
            s = short_summary(summary, title)
            if s:
                lines.append(html.escape(translate_ar(s)))
        lines.append(f"📊 التأثير المتوقع: {sentiment(text)} (تقدير تقريبي)")
        pl = price_line(coins, prices) if SHOW_PRICE else ""
        if pl:
            lines.append(pl)
        lines.append(f'🔗 <a href="{html.escape(link)}">{html.escape(source)}</a>')
        send("\n\n".join(lines))
        seen.add(uid)

    save_seen(seen)


if __name__ == "__main__":
    main()
