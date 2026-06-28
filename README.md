# Duck Hunt Telegram Bot

A one-time-use Telegram bot for a birthday duck hunt game. Players find numbered resin ducks, send a photo with the duck number as the caption, and the bot verifies the claim with Gemini Flash before recording it.

## Setup

### 1. Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the bot token

### 2. Get a Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Create an API key

### 3. Configure the bot

```bash
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in `BOT_TOKEN` and `GEMINI_API_KEY`.

### 4. Get the group chat ID and topic ID

1. Add the bot to your birthday group chat
2. Open the **Duck Hunt** topic (not General)
3. Send `/chatid` in that topic
4. Copy the chat ID into `GROUP_CHAT_ID` and the topic ID into `GROUP_TOPIC_ID` in `.env`

If your group uses forum topics and you skip `GROUP_TOPIC_ID`, announcements will land in **General** by default.

Set `ADMIN_USER_ID` (your Telegram user ID from `/chatid` in DM with the bot) to receive photos that look edited or suspicious. Use `/remove <number>` in DM to revoke a claim — the group will be notified.

### 5. Run the bot

```bash
python bot.py
```

On first run, the bot creates `ducks.db` and pre-seeds ducks 1–100.

## How to play

1. Find a numbered resin duck (any color)
2. **DM the bot** a photo of the duck with the **duck number as the caption** (e.g. `37`) — not in the group chat
3. The bot verifies the photo and records your find
4. A group announcement is posted: "Duck #37 found by @alice! 63 ducks left."

Use `/leaderboard` and `/remaining` in the group. Claims must be sent in DM.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Rules and how to claim |
| `/leaderboard` | Ranked list of finders |
| `/remaining` | How many ducks are left |
| `/chatid` | Print the current chat ID (for setup) |

## Database

SQLite file at `ducks.db` (configurable via `DB_PATH`). You can inspect or edit it with [DB Browser for SQLite](https://sqlitebrowser.org/).

## Moving to cloud later

No code changes needed:

1. Copy the project folder and `ducks.db` to your server
2. Set the same `.env` values
3. Run `python bot.py` (use `tmux`, `nohup`, or `systemd` to keep it running)

The bot uses long-polling, so no public URL or webhook setup is required.

## Laptop tips for party night

- Disable sleep / keep laptop plugged in
- Use phone hotspot as WiFi backup if chalet WiFi is flaky
