from telethon import TelegramClient
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact
from telethon.errors import FloodWaitError, PhoneNumberInvalidError

import asyncio


API_ID = 20133532      # <-- your API ID
API_HASH = "9c0cfd8f61aa9127dc551839375f095c"
SESSION_NAME = "telethon_dev_session/user.session"


async def get_telegram_id(phone_number: str):
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    await client.start()

    try:
        # Add contact temporarily
        contact = InputPhoneContact(
            client_id=0,
            phone=phone_number,
            first_name="Temp",
            last_name=""
        )

        result = await client(ImportContactsRequest([contact]))

        if not result.users:
            return {"status": 0, "message": "User not found or privacy is set to nobody"}

        user = result.users[0]
        telegram_id = user.id

        # Delete the contact
        await client(DeleteContactsRequest(id=[user]))

        return {"status": 1, "telegram_id": telegram_id}

    except PhoneNumberInvalidError:
        return {"status": 0, "message": "Invalid phone number format"}

    except FloodWaitError as e:
        return {"status": 0, "message": f"Flood wait: retry after {e.seconds} seconds"}

    finally:
        await client.disconnect()


if __name__ == "__main__":
    phone = input("Enter phone number with country code (e.g., +919876543210): ")
    result = asyncio.run(get_telegram_id(phone))
    print(result)
