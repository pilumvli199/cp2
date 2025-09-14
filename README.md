# Crypto Phase-1 Bot (Redis + OpenAI + Telegram)

This package is Phase-1 of a crypto bot that:
- reads spot prices from Binance every 5 minutes,
- stores last prices in Redis,
- sends a "Bot online" alert and recurring price summaries to Telegram,
- sends a compact snapshot to OpenAI for a one-line analysis included in the Telegram message.

## Files
- `main.py` — main program (full implementation).
- `requirements.txt` — Python dependencies.
- `.env.example` — template for environment variables.
- `Dockerfile` — Docker image for deployment.
- `Procfile` — simple start command for platforms that use Procfile.

## Local setup
1. Copy `.env.example` to `.env` and fill the values.
2. Create a virtualenv and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Run:
   ```bash
   python main.py
   ```

## Railway Deployment
1. Push this repo to GitHub.
2. Create a new Railway project and deploy from the repo.
3. Add environment variables in Railway (Variables): `REDIS_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OPENAI_API_KEY`.
4. Railway will install dependencies and run `python main.py` (Procfile or Dockerfile).

