<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/platform-Telegram-blue.svg" alt="Telegram">
</p>

<h1 align="center"> Telegram Permission Bot</h1>

<p align="center">
  <b>Precision tool for managing Telegram group member permissions.</b><br>
  Unban one specific permission at a time, without touching anything else.
</p>

---

## Table of Contents

- [What problem does this solve?](#what-problem-does-this-solve)
- [Quick Start (30 seconds)](#quick-start-30-seconds)
- [Commands Reference](#commands-reference)
- [Installation](#installation)
- [Usage Examples](#usage-examples)
- [How It Works (technical)](#how-it-works-technical)
- [Customizing Permissions](#customizing-permissions)
- [Limitations & Troubleshooting](#limitations--troubleshooting)
- [Security](#security)
- [License](#license)

---

## What problem does this solve?

A moderation bot joined your Telegram group and restricted a permission for all members. For example, `GroupHelpBot` removed the ability to **react to messages**. Now you want that permission back, but you don't want to reset everything else.

Telegram's official Bot API **cannot** control some permissions (like `send_reactions`) individually. Even Python libraries like Pyrogram and Telethon use older API layers that don't expose these fields.

**This bot solves that** by manipulating the raw MTProto bytes directly, giving you surgical control over every permission bit — including ones no library supports yet.

---

## Quick Start (30 seconds)

```bash
# 1. Clone
git clone https://github.com/Atrayant-I/telegram-permission-bot.git
cd telegram-permission-bot

# 2. Install
pip install -r requirements.txt

# 3. Create your .env file
#    Edit it with your bot token, api_id and api_hash
cp .env.example .env

# 4. Run
python bot.py
```

Then in your group: **`/unban reactions`**

---

## Commands Reference

| Command | What it does |
|:---|:---|
| `/unban reactions` | Restore reaction ability for every restricted member |
| `/unban messages` | Restore message sending |
| `/unban media` | Restore media sharing |
| `/unban stickers` | Restore stickers & GIFs |
| `/unban links` | Restore link previews |
| `/unban polls` | Restore poll creation |
| `/unban invite` | Restore invite privileges |
| `/unban all` | Remove **every** restriction (use carefully) |
| `/permissions` | Show full permission list with aliases |

All commands are **admin-only**. Anonymous admins are supported.

---

## Installation

### Prerequisites

| You need | Get it from |
|:---|:---|
| Bot token | [@BotFather](https://t.me/BotFather) on Telegram |
| API ID + API Hash | [my.telegram.org/apps](https://my.telegram.org/apps) |
| Python 3.9+ | [python.org](https://python.org) |

### Step by step

**1. Create your bot**

Message [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the prompts. Save the token you receive.

**2. Get API credentials**

Go to [my.telegram.org/apps](https://my.telegram.org/apps), log in, and create an app. Note the `api_id` and `api_hash`.

**3. Add the bot to your group**

Add your bot to the target group as an **administrator** with at least the **Ban users** permission.

> The bot needs "Ban users" because Telegram uses the same API method (`channels.editBanned`) for both restricting *and* unrestricting users. Without it, the bot cannot modify restrictions.

**4. Configure credentials**

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```ini
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890
```

**5. Run**

```bash
python bot.py
```

---

## Usage Examples

### Restore reactions for everyone

```
/unban reactions
```

The bot scans all restricted members, and for each one, it unsets only the `send_reactions` flag. All other restrictions (like muted messages, banned media, etc.) stay exactly as they were.

### Restore multiple permissions (one at a time)

```
/unban reactions
# ... wait for it to finish ...
/unban stickers
# ... wait for it to finish ...
/unban links
```

Each command touches only the permission you asked for.

### List all available permissions

```
/permissions
```

Shows every permission the bot can manage, with aliases and descriptions.

### Remove all restrictions (use carefully)

```
/unban all
```

This completely clears every restriction for every restricted member — they get full group access back.

---

## How It Works (technical)

### The core problem

Telegram stores member restrictions as a **bitmask** inside a `ChatBannedRights` object. Each permission maps to one bit:

```
Permission bits (simplified):

  bit 0: view_messages       bit 1: send_messages      bit 2: send_media
  bit 3: send_stickers       bit 4: send_gifs           bit 5: send_games
  bit 6: send_inline         bit 7: embed_links         bit 8: send_polls
  bit 9: send_reactions  ←── NOT IN ANY CURRENT PYTHON LIBRARY
  bit 10: change_info        bit 15: invite_users       bit 17: pin_messages
  ... and more ...
```

The problem: Pyrogram, Telethon, and Hydrogram all use Telegram API layers from **before** bit 9 was added. Their `ChatBannedRights` class doesn't know `send_reactions` exists. When you serialize (write) the object, bit 9 gets **lost**.

### The solution

This bot defines `PermissionOverride`, a subclass of `ChatBannedRights` that **overrides the byte serialization directly**:

```python
class PermissionOverride(ChatBannedRights):
    def _bytes(self):
        orig = super()._bytes()          # Get the bytes the library would send
        flags = struct.unpack("<I", orig[4:8])[0]  # Read the flag bitmask
        flags &= ~(1 << 9)               # Force bit 9 to 0 (unban reactions)
        return orig[:4] + struct.pack("<I", flags) + orig[8:]  # Rebuild
```

This approach works for **any** permission bit, present or future, regardless of library support.

---

## Customizing Permissions

### Adding a new permission the library doesn't support yet

If Telegram adds a new permission in a future API layer, you can add it in **two places** — no library update needed:

**1. Add the bit mapping** in `bot.py` (line ~49):

```python
PERMISSION_BIT_MAP = {
    # ... existing entries ...
    "send_reactions": 9,        # Already added (bit 9)
    "future_permission": 27,    # ← Add new bit here
}
```

**2. Add a friendly alias** in `PERMISSION_ALIASES` (line ~72):

```python
PERMISSION_ALIASES = {
    # ... existing entries ...
    "future": "future_permission",   # ← Add alias here
}
```

**3. Add a description** in the `/permissions` handler (line ~310):

```python
descriptions = {
    # ... existing entries ...
    "future_permission": "Description of what this does",
}
```

That's it. The `PermissionOverride._bytes()` code handles **any** bit automatically. No need to touch the serialization logic.

### Removing a permission alias

Simply delete the alias entry from `PERMISSION_ALIASES`. The full name will still work.

### Changing which members are targeted

By default the bot targets all `ChannelParticipantBanned` members. To change this, modify the `gather_restricted()` function (line ~175). For example, to also target kicked users, add a second query with `ChannelParticipantsKicked`.

### Adjusting speed

The delay between API calls is on line ~280:

```python
await asyncio.sleep(0.05)   # 50ms between calls — reduce for speed, increase if rate-limited
```

Telethon handles Telegram's `FloodWait` automatically, but if you get rate-limited, increase this value to `0.2` or `0.5`.

---

## Limitations & Troubleshooting

| Issue | Likely cause | Solution |
|:---|:---|:---|
| "Only group admins can use this command" | You're not an admin, or the bot can't detect it | Make sure you have admin rights; try without anonymous mode |
| "ChatAdminRequiredError" | Bot doesn't have "Ban users" permission | Re-add the bot as admin with "Ban users" enabled |
| Processing stops at ~1000 members | Telegram API limits results per query | Run `/unban` again — the bot skips already-processed users and picks up new ones |
| Bot seems slow for large groups | ~0.05s per member + ~1.5s per search query (37 total) | Expected. For 500+ restricted members it takes a few minutes |
| Bot only works in supergroups | Basic groups use a different API | Convert to supergroup or use a different approach |

---

## Security

- Your `.env` file contains your bot token and API credentials. **Never commit it** or share it publicly.
- If credentials are ever exposed, revoke them immediately:
  - Bot token: message [@BotFather](https://t.me/BotFather), use `/revoke`
  - API credentials: delete and recreate at [my.telegram.org/apps](https://my.telegram.org/apps)
- The `processed/` directory stores real Telegram user IDs locally for deduplication. Keep it private.

---

## License

MIT — use it, modify it, share it. Attribution appreciated.
