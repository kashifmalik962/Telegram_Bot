# from telethon import TelegramClient, types

# api_id = 20133532
# api_hash = "9c0cfd8f61aa9127dc551839375f095c"
# client = TelegramClient("session", api_id, api_hash)

# async def get_phone(user_identifier):
#     user = await client.get_entity(user_identifier)   # id, username or Peer
#     # user.phone may be None if not visible
#     print("phone:", getattr(user, "phone", None))

# with client:
#     client.loop.run_until_complete(get_phone(8307332619))  # numeric id



from telethon.errors import PhoneNumberInvalidError
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact



def get_telegram_id_by_phone(phone: str):
    """
    Import a phone contact, return Telegram ID and username if exists.
    """
    try:
        contact = InputPhoneContact(client_id=0, phone=phone, first_name="Temp", last_name="Temp")
        result = client(ImportContactsRequest([contact]))
        if result.users:
            user = result.users[0]
            # Optional cleanup: remove contact after fetching
            client(DeleteContactsRequest(id=[user.id]))
            return user.id, getattr(user, "username", None)
        return None, None
    except PhoneNumberInvalidError:
        return None, None
    except Exception as e:
        print(f"⚠️ Error importing {phone}: {e}")
        return None, None
    


get_telegram_id_by_phone("+919872317102")