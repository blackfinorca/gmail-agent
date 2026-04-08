# Gmail Intelligence Agent

A Python agent that monitors a Gmail account, filters emails by sender/keyword rules,
and maintains a distilled, always-current AI summary per conversation thread.

---

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your values
```

### 3. Enable Gmail API (Google Cloud Console)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create or select a project
3. **APIs & Services → Enable APIs** → search for "Gmail API" → Enable
4. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Desktop app**
5. Download the JSON file and save it as `credentials/credentials.json`
6. Under **OAuth consent screen**, add your Gmail address as a test user

---

## First Run (OAuth)

```bash
python agent.py
```

On first run this opens a browser window for Google OAuth. After you approve access,
`credentials/token.json` is saved and the browser window can be closed. Subsequent
runs use the saved token (auto-refreshed).

---

## Running the Agent

```bash
# Continuous mode (polls every POLL_INTERVAL_SECONDS)
python agent.py

# Single poll then exit (useful for testing)
python agent.py --once
```

Keep the terminal open or use `nohup` / `screen` for a persistent process:

```bash
nohup python agent.py > /dev/null 2>&1 &
# or
screen -S gmail-agent
python agent.py
# Ctrl+A then D to detach
```

---

## Running the Dashboard

In a second terminal (with the venv active):

```bash
python dashboard/app.py
```

Open [http://localhost:5050](http://localhost:5050) — the dashboard auto-refreshes every 60 seconds.

---

## Customising Rules

Edit `rules.json` — changes are picked up on the next poll cycle, no restart needed:

```json
{
  "sender_whitelist": ["billing@", "accounts@", "invoice@"],
  "keywords": ["invoice", "purchase order", "payment due", "contract"]
}
```

- **sender_whitelist**: partial matches against the From address (e.g. `"@acme.com"` matches any Acme sender)
- **keywords**: case-insensitive matches against subject + body

---

## Project Structure

```
├── agent.py            — main poll loop, orchestration
├── config.py           — loads .env + rules.json
├── filter_engine.py    — sender/keyword rule matching
├── gmail_client.py     — Gmail API auth + message fetching
├── storage.py          — SQLite: threads, messages, run log
├── summariser.py       — Anthropic API calls, prompt logic
├── rules.json          — editable filter rules
├── dashboard/
│   ├── app.py          — Flask app (read-only)
│   └── templates/      — index.html, thread.html
└── credentials/        — OAuth token files (gitignored)
```
