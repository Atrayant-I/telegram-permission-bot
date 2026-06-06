"""
Telegram Permission Bot

Unban specific permissions for all restricted members in a Telegram group.
Works by overriding ChatBannedRights._bytes() to manipulate individual
permission bits that are not exposed by standard Python MTProto libraries.

Requires: Python 3.9+, Telethon, python-dotenv
Bot needs "Ban users" admin right in the target group.
"""

import os
import sys
import struct
import json
import string
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.set_event_loop(asyncio.new_event_loop())

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.functions.channels import EditBannedRequest, GetParticipantsRequest
from telethon.tl.types import (
    ChatBannedRights,
    ChannelParticipantBanned,
    InputPeerUser,
    User,
)
from telethon.errors import ChatAdminRequiredError

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

client = TelegramClient("permission_bot", API_ID, API_HASH)

PERMISSION_BIT_MAP = {
    "view_messages": 0,
    "send_messages": 1,
    "send_media": 2,
    "send_stickers": 3,
    "send_gifs": 4,
    "send_games": 5,
    "send_inline": 6,
    "embed_links": 7,
    "send_polls": 8,
    "send_reactions": 9,
    "change_info": 10,
    "invite_users": 15,
    "pin_messages": 17,
    "manage_topics": 18,
    "send_photos": 19,
    "send_videos": 20,
    "send_roundvideos": 21,
    "send_audios": 22,
    "send_voices": 23,
    "send_docs": 24,
    "send_plain": 25,
    "edit_rank": 26,
}

PERMISSION_ALIASES = {
    "reactions": "send_reactions",
    "messages": "send_messages",
    "media": "send_media",
    "stickers": "send_stickers",
    "gifs": "send_gifs",
    "games": "send_games",
    "inline": "send_inline",
    "links": "embed_links",
    "polls": "send_polls",
    "info": "change_info",
    "invite": "invite_users",
    "pin": "pin_messages",
    "topics": "manage_topics",
    "photos": "send_photos",
    "videos": "send_videos",
    "roundvideos": "send_roundvideos",
    "audios": "send_audios",
    "voices": "send_voices",
    "docs": "send_docs",
    "plain": "send_plain",
    "rank": "edit_rank",
    "view": "view_messages",
}


class PermissionOverride(ChatBannedRights):
    """
    ChatBannedRights subclass that can set/clear arbitrary permission bits.

    This is necessary because standard Python MTProto libraries
    (Pyrogram, Telethon, Hydrogram) use older API layers that do not
    include all ChatBannedRights fields such as send_reactions (bit 9).

    By overriding _bytes() we can inject any bit into the serialized
    TL object, regardless of whether the library knows about it.

    Args:
        bit_overrides: dict mapping bit position (int) to bool.
                       True = forbid, False = allow, None = leave unchanged.
    """

    def __init__(self, bit_overrides=None, **kwargs):
        super().__init__(**kwargs)
        self._bit_overrides = bit_overrides or {}

    @classmethod
    def from_original(cls, orig, bit_overrides=None):
        return cls(
            bit_overrides=bit_overrides,
            until_date=orig.until_date,
            view_messages=orig.view_messages,
            send_messages=orig.send_messages,
            send_media=orig.send_media,
            send_stickers=orig.send_stickers,
            send_gifs=orig.send_gifs,
            send_games=orig.send_games,
            send_inline=orig.send_inline,
            embed_links=orig.embed_links,
            send_polls=orig.send_polls,
            change_info=orig.change_info,
            invite_users=orig.invite_users,
            pin_messages=orig.pin_messages,
            manage_topics=orig.manage_topics,
            send_photos=orig.send_photos,
            send_videos=orig.send_videos,
            send_roundvideos=orig.send_roundvideos,
            send_audios=orig.send_audios,
            send_voices=orig.send_voices,
            send_docs=orig.send_docs,
            send_plain=orig.send_plain,
            edit_rank=orig.edit_rank,
        )

    def _bytes(self):
        orig = super()._bytes()
        flags = struct.unpack("<I", orig[4:8])[0]
        for bit, value in self._bit_overrides.items():
            if value is not None:
                if value:
                    flags |= 1 << bit
                else:
                    flags &= ~(1 << bit)
        return orig[:4] + struct.pack("<I", flags) + orig[8:]


PROCESSED_DIR = os.path.join(os.path.dirname(__file__), "processed")


def _processed_path(chat_id):
    return os.path.join(PROCESSED_DIR, f"{chat_id}.json")


def load_processed(chat_id):
    path = _processed_path(chat_id)
    if os.path.exists(path):
        with open(path, "r") as f:
            return set(json.load(f))
    return set()


def save_processed(chat_id, user_id):
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    path = _processed_path(chat_id)
    data = load_processed(chat_id)
    data.add(user_id)
    with open(path, "w") as f:
        json.dump(list(data), f)


def resolve_permission(name):
    name = name.lower().strip()
    if name in PERMISSION_BIT_MAP:
        return name, PERMISSION_BIT_MAP[name]
    if name in PERMISSION_ALIASES:
        resolved = PERMISSION_ALIASES[name]
        return resolved, PERMISSION_BIT_MAP[resolved]
    return None, None


async def gather_restricted(client, channel):
    seen = set()
    restricted = []
    queries = [""] + list(string.ascii_lowercase) + list(string.digits)

    for q in queries:
        offset = 0
        while True:
            result = await client(GetParticipantsRequest(
                channel=channel,
                filter=ChannelParticipantBanned(q=q),
                offset=offset,
                limit=200,
                hash=0,
            ))
            if not result.participants:
                break
            for p in result.participants:
                if isinstance(p, ChannelParticipantBanned) and p.peer.user_id not in seen:
                    seen.add(p.peer.user_id)
                    restricted.append(p)
            offset += len(result.participants)
            if len(result.participants) < 200:
                break
        await asyncio.sleep(0.3)

    return restricted


@client.on(events.NewMessage(pattern=r"/unban(?:\s+(.+))?"))
async def unban_handler(event):
    if not event.is_group:
        return

    raw_arg = event.pattern_match.group(1)
    if not raw_arg:
        await event.reply(
            "Usage: `/unban <permission>`\n"
            "Example: `/unban send_reactions`\n"
            "Aliases: reactions, messages, media, stickers, gifs, "
            "links, polls, invite, pin, topics, all\n"
            "See `/permissions` for the full list."
        )
        return

    if raw_arg.lower().strip() == "all":
        perms_to_unban = [(name, bit) for name, bit in PERMISSION_BIT_MAP.items()]
        label = "all permissions"
    else:
        name, bit = resolve_permission(raw_arg)
        if name is None:
            await event.reply(
                f"Unknown permission: `{raw_arg}`. "
                f"Use `/permissions` to see available options."
            )
            return
        perms_to_unban = [(name, bit)]
        label = name

    chat = await event.get_chat()
    chat_id = event.chat_id
    sender = await event.get_sender()

    is_anonymous = sender is not None and not isinstance(sender, User)

    if not is_anonymous:
        try:
            perms = await client.get_permissions(chat, sender)
            if not getattr(perms, "is_admin", False):
                await event.reply("Only group admins can use this command.")
                return
        except Exception as ex:
            await event.reply(f"Admin check failed: {type(ex).__name__}")
            return

    status_msg = await event.reply("Scanning for restricted members...")

    try:
        channel = await event.get_input_chat()
        restricted = await gather_restricted(client, channel)

        print(f"Found {len(restricted)} unique restricted members")

        already = load_processed(chat_id)

        pending = [
            p for p in restricted
            if isinstance(p, ChannelParticipantBanned)
            and p.peer.user_id not in already
        ]

        if len(restricted) == 0:
            await status_msg.edit("No restricted members found in this group.")
            return

        skipped = len(restricted) - len(pending)
        await status_msg.edit(
            f"Found {len(restricted)} restricted members."
            + (f" {skipped} already processed. " if skipped else " ")
            + f"Pending: {len(pending)}. Unbanning {label}..."
        )

        if len(pending) == 0:
            await status_msg.edit("All restricted members have already been processed.")
            return

        bit_overrides = {bit: False for _, bit in perms_to_unban}

        done = 0
        errors = 0
        total = len(pending)

        for i, p in enumerate(pending):
            user_id = p.peer.user_id
            try:
                new_bans = PermissionOverride.from_original(
                    p.banned_rights,
                    bit_overrides=bit_overrides,
                )
                await client(EditBannedRequest(
                    channel=channel,
                    participant=InputPeerUser(user_id=user_id, access_hash=0),
                    banned_rights=new_bans,
                ))
                done += 1
                save_processed(chat_id, user_id)
                print(f"OK  user_id={user_id}")
            except Exception as ex:
                errors += 1
                print(f"ERR user_id={user_id}  {type(ex).__name__}: {ex}")

            if (i + 1) % 20 == 0 or i == total - 1:
                try:
                    await status_msg.edit(
                        f"Progress: {done}/{total}"
                        + (f" ({errors} errors)" if errors else "")
                    )
                except Exception:
                    pass

            await asyncio.sleep(0.05)

        await status_msg.edit(
            f"Done. Unbanned {label} for {done} members."
            + (f" ({errors} errors)" if errors else "")
        )

    except ChatAdminRequiredError:
        await status_msg.edit(
            "Error: bot needs 'Ban users' admin right in this group."
        )
    except Exception as e:
        await status_msg.edit(f"Error: {type(e).__name__}: {e}")


@client.on(events.NewMessage(pattern="/permissions"))
async def permissions_handler(event):
    if not event.is_group:
        return

    lines = ["**Available permissions:**", ""]
    lines.append("Name (alias) — Description")
    lines.append("─" * 40)

    descriptions = {
        "view_messages": "Read messages",
        "send_messages": "Send text messages",
        "send_media": "Send media files",
        "send_stickers": "Send stickers & GIFs",
        "send_gifs": "Send GIFs",
        "send_games": "Send games",
        "send_inline": "Use inline bots",
        "embed_links": "Embed link previews",
        "send_polls": "Create polls",
        "send_reactions": "React to messages",
        "change_info": "Change group info",
        "invite_users": "Invite users",
        "pin_messages": "Pin messages",
        "manage_topics": "Manage forum topics",
        "send_photos": "Send photos",
        "send_videos": "Send videos",
        "send_roundvideos": "Send video messages",
        "send_audios": "Send audio files",
        "send_voices": "Send voice messages",
        "send_docs": "Send documents",
        "send_plain": "Send plain text",
        "edit_rank": "Edit admin rank",
    }

    shown_aliases = set()
    for name, bit in sorted(PERMISSION_BIT_MAP.items(), key=lambda x: x[1]):
        desc = descriptions.get(name, "")
        aliases = [k for k, v in PERMISSION_ALIASES.items() if v == name]
        alias_str = f" ({', '.join(aliases)})" if aliases else ""
        lines.append(f"`{name}`{alias_str} — {desc}")

    lines.append("")
    lines.append("**Special:** `/unban all` — remove all restrictions")
    lines.append("**Usage:** `/unban send_reactions` or `/unban reactions`")

    await event.reply("\n".join(lines))


if __name__ == "__main__":
    print("Permission Bot starting... Ctrl+C to stop.")
    client.start(bot_token=BOT_TOKEN)
    client.run_until_disconnected()
