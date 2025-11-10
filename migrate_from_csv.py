# migrate_from_csv_with_dm.py
import asyncio
import csv
import logging
import re
from datetime import datetime, timedelta

import pymongo
from telegram import Bot, ChatPermissions
from telegram.error import TelegramError
from telegram.constants import ChatMemberStatus

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
BOT_TOKEN = "8258489863:AAFEH6pypIYxHSulwNey-t-sdy2_NwEIeU4"
NEW_CHAT_ID = -1003223329072
 

CSV_FILE = "old_group_members.csv"
USER_ID_FIELD = "telegram_id"

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "telegram_bot"
COLLECTION_NAME = "subscriptions"

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# MongoDB
# ----------------------------------------------------------------------
client = pymongo.MongoClient(MONGO_URI)
db = client[DB_NAME]
col = db[COLLECTION_NAME]

# ----------------------------------------------------------------------
# Load CSV
# ----------------------------------------------------------------------
def load_users_from_csv():
    users = []
    try:
        with open(CSV_FILE, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    user_id = int(row['id'].strip())
                    users.append(user_id)
                except (ValueError, KeyError):
                    log.warning(f"Skipping invalid row: {row}")
        log.info(f"Loaded {len(users)} users from {CSV_FILE}")
    except FileNotFoundError:
        log.error(f"CSV not found: {CSV_FILE}")
        exit(1)
    return users

# ----------------------------------------------------------------------
# Send Invite Link via DM
# ----------------------------------------------------------------------
async def send_invite_link(bot: Bot, user_id: int):
    try:
        # Generate invite link (1-time use)
        invite = await bot.create_chat_invite_link(
            chat_id=NEW_CHAT_ID,
            member_limit=1,
            expire_date=datetime.utcnow() + timedelta(days=1)
        )
        link = invite.invite_link

        # Send to user
        await bot.send_message(
            chat_id=user_id,
            text=f"Click to join the New Group (30-day access):\n\n{link}",
            disable_web_page_preview=True
        )

        # Save to DB
        now = datetime.utcnow()
        col.update_one(
            {USER_ID_FIELD: user_id},
            {"$set": {
                "joined_at": now,
                "expires_at": now + timedelta(days=30),
                "invite_link": link,
                "source": "dm_invite"
            }},
            upsert=True
        )
        log.info(f"INVITE SENT: {user_id} → {link}")
        return True

    except TelegramError as e:
        msg = str(e).lower()
        if "bot can't initiate" in msg or "chat not found" in msg:
            log.warning(f"CANNOT DM: {user_id} (privacy settings)")
        elif "user is deactivated" in msg:
            log.warning(f"DEACTIVATED: {user_id}")
        else:
            log.error(f"FAILED DM: {user_id} → {e}")
        return False

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
async def main():
    bot = Bot(token=BOT_TOKEN)
    me = await bot.get_me()
    log.info(f"Bot: @{me.username}")

    # Check admin
    member = await bot.get_chat_member(chat_id=NEW_CHAT_ID, user_id=me.id)
    if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        raise RuntimeError("Bot must be ADMIN with 'Invite Users' permission")

    users = load_users_from_csv()
    if not users:
        return

    success = 0
    for i, user_id in enumerate(users, 1):
        if await send_invite_link(bot, user_id):
            success += 1
        await asyncio.sleep(1)  # Avoid flood

        if i % 5 == 0:
            log.info(f"Sent {i}/{len(users)} invites")

    log.info(f"MIGRATION DONE: {success}/{len(users)} users invited via DM")

if __name__ == "__main__":
    asyncio.run(main())