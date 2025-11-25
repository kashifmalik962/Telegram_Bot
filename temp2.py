# from telethon import TelegramClient
# from telethon.errors import PhoneNumberInvalidError
# from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
# from telethon.tl.types import InputPhoneContact

# api_id = 20133532
# api_hash = "9c0cfd8f61aa9127dc551839375f095c"

# client = TelegramClient("user", api_id, api_hash)


# async def get_telegram_id_by_phone(phone: str):
#     """
#     Import a phone contact and return Telegram ID + username if exists.
#     """
#     try:
#         contact = InputPhoneContact(
#             client_id=0,
#             phone=phone,
#             first_name="Temp",
#             last_name="Temp"
#         )

#         # IMPORTANT: await the client call
#         result = await client(ImportContactsRequest([contact]))

#         if result.users:
#             user = result.users[0]

#             # Cleanup the imported contact
#             await client(DeleteContactsRequest(id=[user.id]))

#             return user.id, getattr(user, "username", None)

#         return None, None

#     except PhoneNumberInvalidError:
#         return None, None
#     except Exception as e:
#         print(f"⚠️ Error importing {phone}: {e}")
#         return None, None


# async def main():
#     tg_id, username = await get_telegram_id_by_phone("+916306011985")
#     print("Telegram ID:", tg_id)
#     print("Username:", username)


# with client:
#     client.loop.run_until_complete(main())



from telethon import TelegramClient
from telethon.errors import (
    UsernameInvalidError,
    UsernameNotOccupiedError
)
import asyncio

API_ID = 20133532                 # Your API ID
API_HASH = "9c0cfd8f61aa9127dc551839375f095c"      # Your API HASH
SESSION = "user"             # Telethon session name


async def get_telegram_id(telegram_name: str):
    try:
        client = TelegramClient(SESSION, API_ID, API_HASH)
        await client.start()

        if telegram_name.startswith("@"):
            telegram_name = telegram_name[1:]

        user = await client.get_entity(telegram_name)

        return {
            "telegram_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }

    except UsernameNotOccupiedError:
        return {"error": "Username does not exist on Telegram"}

    except UsernameInvalidError:
        return {"error": "Invalid username format"}

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    # example from your DB
    telegram_name = input("Enter telegram username: ")

    data = asyncio.run(get_telegram_id(telegram_name))
    print(data)
