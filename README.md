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

Set `ADMIN_USER_ID` (your Telegram user ID from `/chatid` in DM with the bot) to enable admin commands and receive manual review requests from players.

### 5. Save hiding-spot photos (admin, before the party)

1. DM the bot and run `/input_mode`
2. Send a photo of each duck in its hiding spot with the duck number as the caption (e.g. `37`)
3. Run `/done` when finished
4. Use `/spot 37` to retrieve a hiding photo later, or `/missing` to see which numbers are not saved yet

Photos are stored locally in `duck_spots/` (configurable via `DUCK_SPOTS_DIR`).

### 6. Run the bot

```bash
python bot.py
```

On first run, the bot creates `ducks.db` and pre-seeds ducks 1–100.

## How to play

1. Find a numbered resin duck (any color)
2. **DM the bot** a photo of the duck with the **duck number as the caption** (e.g. `37`) — not in the group chat
3. The bot verifies the photo and records your find
4. A group announcement is posted: "Duck #37 found by @alice! 63 ducks left."

If verification fails twice in a row for the same duck, a button appears to request manual review from the admin.

Use `/leaderboard` and `/remaining` in the group. Claims must be sent in DM. Type `/help` for the full command list.

## Commands

### Players

| Command | Description |
|---------|-------------|
| `/start` | Rules and how to claim |
| `/help` | List available commands |
| `/leaderboard` | Ranked list of finders |
| `/remaining` | How many ducks are left |

### Admin (DM only)

| Command | Description |
|---------|-------------|
| `/help` | Player + admin command lists |
| `/input_mode` | Start saving hiding-spot photos |
| `/done` | Exit input mode |
| `/spot <n>` | Retrieve hiding photo for duck #n |
| `/missing` | List duck numbers without a saved spot |
| `/start_game` | Open the hunt for new claims |
| `/end_game` | Stop accepting new claims |
| `/remove <n>` | Revoke a claim (group is notified) |
| `/chatid` | Print chat/topic IDs for setup |

When a player requests manual review, the admin receives the photo in DM with **Accept** / **Reject** buttons. Accept records the claim and posts the usual group announcement.

Use `/start_game` before the party and `/end_game` when finished. Game state is saved to `bot_state.json` and survives bot restarts.

## Database

SQLite file at `ducks.db` (configurable via `DB_PATH`). You can inspect or edit it with [DB Browser for SQLite](https://sqlitebrowser.org/).

## Moving to cloud later

No code changes needed:

1. Copy the project folder, `ducks.db`, and `duck_spots/` to your server
2. Set the same `.env` values
3. Run `python bot.py` (use `tmux`, `nohup`, or `systemd` to keep it running)

The bot uses long-polling, so no public URL or webhook setup is required.

## Laptop tips for party night

- Disable sleep / keep laptop plugged in
- Use phone hotspot as WiFi backup if chalet WiFi is flaky
