"""
Crypto Phase-1 Bot — single-file implementation (main.py)

Features:
- Polls Binance every 5 minutes for symbols:
  BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, AAVEUSDT, TRXUSDT
- Stores last price + timestamp into Redis (redis.asyncio, TLS enabled)
- Sends a Telegram message on start/restart: "Bot online"
- Every 5 minutes sends a Telegram message with the last prices
- Sends compact price data to OpenAI for a short analysis included in Telegram message

Environment variables required:
- REDIS_URL  (Railway Redis plugin → rediss://...)
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- OPENAI_API_KEY
"""

import os
import asyncio
import time
import json
from datetime import datetime, timezone

import aiohttp
import redis.asyncio as redis
from openai import OpenAI
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

# Configuration from env
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Init OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Symbols (Binance)
SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "AAVEUSDT",
    "TRXUSDT",
]

# Poll interval seconds (default 5 minutes)
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 300))

BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"


async def send_telegram(session: aiohttp.ClientSession, text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram token or chat id not set. Skipping telegram send.")
        return

    url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN, method="sendMessage")
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        async with session.post(url, json=payload, timeout=20) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"[ERROR] Telegram send failed: {resp.status} {text}")
    except Exception as e:
        print(f"[ERROR] Telegram request exception: {e}")


async def fetch_price(session: aiohttp.ClientSession, symbol: str):
    url = BINANCE_PRICE_URL.format(symbol=symbol)
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                price = float(data.get("price", 0))
                return price
            else:
                text = await resp.text()
                print(f"[WARN] Binance returned {resp.status} for {symbol}: {text}")
                return None
    except Exception as e:
        print(f"[ERROR] fetch_price exception for {symbol}: {e}")
        return None


async def save_to_redis(r, symbol: str, price: float):
    key = f"price:{symbol}"
    payload = {
        "price": price,
        "ts": int(time.time()),
        "iso": datetime.now(timezone.utc).isoformat(),
    }
    await r.set(key, json.dumps(payload))


async def read_from_redis(r, symbol: str):
    raw = await r.get(f"price:{symbol}")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


async def openai_analyze(price_map: dict):
    if not OPENAI_API_KEY:
        print("[WARN] OPENAI_API_KEY not set; skipping analysis.")
        return None

    lines = [f"{s}: {v['price']}" if v else f"{s}: NA" for s, v in price_map.items()]
    prompt = (
        "You are a concise crypto market assistant. Given the following latest spot prices (UTC), "
        "provide a one-sentence summary indicating any notable observations (e.g., big moves, relative strength, warnings).\n\n"
        "Prices:\n" + "\n".join(lines) + "\n\nOne-sentence summary:"
    )

    try:
        resp = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=60,
                temperature=0.3,
            ),
        )
        return resp.choices[0].message.content.strip().splitlines()[0]
    except Exception as e:
        print(f"[ERROR] OpenAI request failed: {e}")
        return None


async def periodic_task():
    # Connect to Redis (Railway uses TLS → ssl=True)
    r = None
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True, ssl=True)
        await r.ping()
        print(f"[INFO] Connected to Redis at {REDIS_URL}")
    except Exception as e:
        print(f"[ERROR] Cannot connect to Redis at {REDIS_URL}: {e}")
        r = None

    async with aiohttp.ClientSession() as session:
        # On start: send "Bot online"
        await send_telegram(session, "*Bot online* — Phase 1 (data + analysis + alerts)")
        print("[INFO] Sent startup telegram message.")

        while True:
            start = time.time()
            price_map = {}

            # Fetch prices concurrently
            tasks = [fetch_price(session, s) for s in SYMBOLS]
            fetched = await asyncio.gather(*tasks)

            for s, p in zip(SYMBOLS, fetched):
                if p is not None:
                    if r:
                        try:
                            await save_to_redis(r, s, p)
                        except Exception as e:
                            print(f"[WARN] Failed to save {s} to Redis: {e}")
                    price_map[s] = {"price": p}
                else:
                    if r:
                        price_map[s] = await read_from_redis(r, s)
                    else:
                        price_map[s] = None

            # Ask OpenAI for a short analysis
            analysis = await openai_analyze(price_map)

            # Build Telegram text message
            lines = []
            for s in SYMBOLS:
                v = price_map.get(s)
                if v and "price" in v:
                    lines.append(f"*{s}*: `{v['price']}`")
                else:
                    lines.append(f"*{s}*: NA")
            body = "\n".join(lines)
            footer = analysis if analysis else "(No analysis)"

            message = f"*5-min prices (UTC {datetime.now(timezone.utc).strftime('%H:%M')})*\n\n{body}\n\n_{footer}_"

            # Send Telegram
            await send_telegram(session, message)
            print(f"[INFO] Sent prices update at {datetime.utcnow().isoformat()} UTC")

            # Sleep until next interval
            elapsed = time.time() - start
            to_sleep = max(0, POLL_INTERVAL - elapsed)
            await asyncio.sleep(to_sleep)


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return
    if not OPENAI_API_KEY:
        print("[WARN] OPENAI_API_KEY not set; analysis skipped")

    print("[INFO] Starting crypto Phase-1 bot...")
    try:
        asyncio.run(periodic_task())
    except KeyboardInterrupt:
        print("[INFO] Interrupted by user. Exiting...")
    except Exception as e:
        print(f"[ERROR] Fatal exception: {e}")


if __name__ == "__main__":
    main()
