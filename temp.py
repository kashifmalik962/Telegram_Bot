import asyncio
import logging
from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from telethon.errors import FloodWaitError, UserPrivacyRestrictedError

# ----------------------------------------------------------------------
# CONFIGURATION (REPLACE THESE)
# ----------------------------------------------------------------------
API_ID = 27919113          # <-- Your API ID from my.telegram.org
API_HASH = "eae1a8a3cfcf4d44c1ccc0acf3f7a8c6"  # <-- Your API Hash (string)
PHONE = "+919897178705"      # <-- Your phone number (with +country code)
OLD_CHAT_ID = -1003294223338  # <-- Your Old Group ID

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Get all members (paginated)
# ----------------------------------------------------------------------
async def get_all_members(client):
    all_members = []
    offset = 0
    limit = 200  # Telegram max per request

    while True:
        try:
            # Fetch batch of participants
            participants = await client(GetParticipantsRequest(
                channel=OLD_CHAT_ID,
                filter=ChannelParticipantsSearch(''),  # Empty search = all members
                offset=offset,
                limit=limit,
                hash=0  # Required for pagination
            ))

            if not participants.users:
                break

            # Extract user IDs (skip deleted/bots if needed)
            for user in participants.users:
                if not user.deleted and not user.bot:
                    all_members.append({
                        'id': user.id,
                        'username': user.username or 'No Username',
                        'first_name': user.first_name or '',
                        'last_name': user.last_name or ''
                    })

            print("all_members",all_members)
            fetched = len(participants.users)
            print("fetched",fetched)
            log.info(f"Fetched {fetched} users (total: {len(all_members)})")

            if fetched < limit:
                break  # End of list

            offset += fetched
            await asyncio.sleep(1)  # Rate limit: 1s pause

        except FloodWaitError as e:
            log.warning(f"Flood wait: {e.seconds}s")
            await asyncio.sleep(e.seconds)
        except UserPrivacyRestrictedError:
            log.error("Privacy restricted — can't access some users")
            continue
        except Exception as e:
            log.error(f"Error: {e}")
            break

    return all_members

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
async def main():
    # Create client
    client = TelegramClient('session', API_ID, API_HASH)

    await client.start(phone=PHONE)  # Will prompt for code on first run

    me = await client.get_me()
    log.info(f"Logged in as: {me.first_name} (@{me.username})")

    # Verify you're in the group
    try:
        chat = await client.get_entity(OLD_CHAT_ID)
        log.info(f"Group: {chat.title} (ID: {OLD_CHAT_ID})")
    except Exception as e:
        log.error(f"Can't access group: {e} — ensure you're a member/admin")
        return

    # Get members
    log.info("Starting member extraction...")
    members = await get_all_members(client)

    log.info(f"\n=== RESULTS ===\nTotal members found: {len(members)}")

    # Print IDs
    for member in members:
        print(f"ID: {member['id']} | Username: @{member['username']} | Name: {member['first_name']} {member['last_name']}")

    # Save to CSV (for easy import to MongoDB/next script)
    import csv
    with open('old_group_members.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'username', 'first_name', 'last_name'])
        writer.writeheader()
        writer.writerows(members)
    log.info("Saved to old_group_members.csv")

    await client.disconnect()

# ----------------------------------------------------------------------
# Run
# ----------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())