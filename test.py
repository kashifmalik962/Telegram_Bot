from telethon import TelegramClient
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")  # Your Telegram number

client = TelegramClient('session', API_ID, API_HASH)


async def main():
    async with TelegramClient('session_temp', API_ID, API_HASH) as client:
        # Ensure login
        me = await client.get_me()
        print("Logged in as:", me.id, getattr(me, "username", None))
        
        # Import phone contact
        contact = InputPhoneContact(client_id=0, phone='+916306011985', first_name='Kaif', last_name='Malik')
        result = await client(ImportContactsRequest([contact]))
        
        if result.users:
            user = result.users[0]
            print("User ID:", user.id)
            print("Username:", getattr(user, "username", None))
            await client(DeleteContactsRequest(id=[user.id]))
        else:
            print("User not found.")

asyncio.run(main())

