from telethon import TelegramClient, types

api_id = 20133532
api_hash = "9c0cfd8f61aa9127dc551839375f095c"
client = TelegramClient("session", api_id, api_hash)

async def get_phone(user_identifier):
    user = await client.get_entity(user_identifier)   # id, username or Peer
    # user.phone may be None if not visible
    print("phone:", getattr(user, "phone", None))

with client:
    client.loop.run_until_complete(get_phone(8307332619))  # numeric id
