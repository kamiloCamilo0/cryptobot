import os, re, json, html
import feedparser
import requests

TOKEN = os.environ["TG_TOKEN"]
CHAT_ID = str(os.environ["TG_CHAT_ID"])

# ============ الإعدادات ============
# العملات الابتدائية فقط (بعدها تُدار من تيليجرام بالأوامر /add و/remove)
DEFAULT_COINS = {
    "BTC": (["bitcoin", "btc"], "bitcoin"),
    "ETH": (["ethereum", "ether", "eth"], "ethereum"),
    "BNB": (["bnb", "binance coin"], "binancecoin"),
    "SOL": (["solana", "sol"], "solana"),
    "XRP": (["xrp", "ripple"], "ripple"),
    "DOGE": (["dogecoin", "doge"], "dogecoin"),
    "ADA": (["cardano"], "cardano"),
    "TRX": (["tron", "trx"], "tron"),
    "AVAX": (["avalanche", "avax"], "avalanche-2"),
    "LINK": (["chainlink"], "chainlink"),
    "TON": (["toncoin"], "the-open-network"),
    "DOT": (["polkadot"], "polkadot"),
    "LTC": (["litecoin", "ltc"], "litecoin"),
    "SUI": (["sui"], "sui"),
    "NEAR": (["near protocol"], "near"),
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
# ===================================

SEEN_FILE = "seen.json"   # يحفظ الأخبار المرسلة + العملات + آخر رسالة قُرئت
COINS = {}


# ---------- الحالة ----------
def load_state():
    try:
        with open(SEEN_FILE) as f:
            data = json.load(f)
    except Exception:
        data = {}
    if isinstance(data, list):  # توافق مع النسخة القديمة
        data = {"seen": data}
    seen = set(data.get("seen", []))
    coins = data.get("coins") or {
        k: {"words": v[0], "id": v[1]} for k, v in DEFAULT_COINS.items()
    }
    return seen, coins, data.get("offset", 0)


def save_state(seen, coins, offset):
    with open(SEEN_FILE, "w") as f:
        json.dump({"seen": list(seen)[-3000:], "coins": coins, "offset": offset},
                  f, ensure_ascii=False)


# ---------- أدوات ----------
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
    return any(w in text.lower() + " " for w in IMPORTANT)


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


# ---------- أوامر تيليجرام ----------
def find_coin(query):
    """يبحث عن العملة في CoinGecko (مجاني) ويرجع (الرمز، الكلمات، المعرّف)"""
    try:
        r = requests.get("https://api.coingecko.com/api/v3/search",
                         params={"query": query}, timeout=15)
        r.raise_for_status()
        results = r.json().get("coins", [])
    except Exception:
        return None
    q = query.lower()
    exact = [c for c in results
             if c["symbol"].lower() == q or c["name"].lower() == q]
    exact.sort(key=lambda c: c.get("market_cap_rank") or 10**9)
    pick = (exact or results[:1] or [None])[0]
    if not pick:
        return None
    words = [pick["name"].lower()]
    if len(pick["symbol"]) >= 3 and pick["symbol"].lower() not in words:
        words.append(pick["symbol"].lower())
    return pick["symbol"].upper(), words, pick["id"]


HELP = ("🤖 الأوامر:\n"
        "/add XRP — إضافة عملة\n"
        "/remove DOGE — حذف عملة\n"
        "/list — عرض عملاتك\n\n"
        "ملاحظة: يقرأ البوت أوامرك عند كل تشغيل، فقد يتأخر الرد بعض الوقت.")


def handle_commands(coins, offset):
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                         params={"offset": offset, "timeout": 0}, timeout=15)
        updates = r.json().get("result", [])
    except Exception:
        return offset

    for u in updates:
        offset = u["update_id"] + 1
        msg = u.get("message")
        if not msg or str(msg["chat"]["id"]) != CHAT_ID:
            continue  # تجاهل أي شخص غيرك
        parts = (msg.get("text") or "").strip().split()
        if not parts or not parts[0].startswith("/"):
            continue
        cmd, args = parts[0].lower().split("@")[0], parts[1:]

        if cmd == "/add" and args:
            out = []
            for a in args[:5]:
                found = find_coin(a)
                if not found:
                    out.append(f"❌ لم أجد عملة باسم {a}")
                    continue
                sym, words, cid = found
                if sym in coins:
                    out.append(f"ℹ️ {sym} موجودة مسبقاً")
                else:
                    coins[sym] = {"words": words, "id": cid}
                    out.append(f"✅ تمت إضافة {sym}")
            send(html.escape("\n".join(out)))
        elif cmd == "/remove" and args:
            out = []
            for a in args:
                sym = a.upper()
                if coins.pop(sym, None):
                    out.append(f"🗑️ تم حذف {sym}")
                else:
                    out.append(f"❌ {sym} غير موجودة")
            send(html.escape("\n".join(out)))
        elif cmd == "/list":
            send("📋 عملاتك (" + str(len(coins)) + "):\n" + " · ".join(coins) if coins
                 else "لا توجد عملات. أضف بـ /add BTC")
        else:
            send(html.escape(HELP))
    return offset


# ---------- التشغيل ----------
def main():
    global COINS
    seen, coins_state, offset = load_state()
    offset = handle_commands(coins_state, offset)
    COINS = {k: (v["words"], v["id"]) for k, v in coins_state.items()}

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

    save_state(seen, coins_state, offset)


if __name__ == "__main__":