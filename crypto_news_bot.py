import os, json, re
import feedparser
import requests

TOKEN = os.environ["TG_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]

COINS = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "ether", "eth"],
    "SOL": ["solana", "sol"],
}

FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
]

SEEN_FILE = "seen.json"


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-2000:], f)


def match_coins(text):
    found = []
    for coin, words in COINS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE):
                found.append(coin)
                break
    return found


def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg},
        timeout=15,
    )


def main():
    seen = load_seen()
    for url in FEEDS:
        for entry in feedparser.parse(url).entries:
            uid = entry.get("id") or entry.link
            if uid in seen:
                continue
            seen.add(uid)
            text = entry.title + " " + entry.get("summary", "")
            coins = match_coins(text)
            if coins:
                send(f"📰 {' / '.join(coins)}\n{entry.title}\n{entry.link}")
    save_seen(seen)


if __name__ == "__main__":
    main()
