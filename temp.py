from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ChatJoinRequest
from aiogram.filters import CommandStart
import asyncio
import time
import logging

BOT_TOKEN = "8258489863:AAFEH6pypIYxHSulwNey-t-sdy2_NwEIeU4"
GROUP_ID = -1001234567890  # Replace with your Telegram group ID

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ---- TEMP STORAGE (Replace with MongoDB / PostgreSQL later) ----
mobile_to_user = {}
invite_to_user = {}

# ---------------- Helper ----------------
def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Share phone number", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# ---------------- /start ----------------
@dp.message(CommandStart())
async def start_command(message: Message):
    """
    User clicks bot link: /start <mobile>
    Example: t.me/YourBot?start=919876543210
    """
    parts = message.text.split()
    expected_mobile = parts[1] if len(parts) > 1 else None

    if not expected_mobile:
        await message.answer(
            "⚠️ Please open your personal invite link. "
            "It should look like this:\n\n👉 /start <your-mobile-number>"
        )
        return

    # Store expected mobile temporarily (replace with DB save)
    mobile_to_user[message.from_user.id] = {"expected_mobile": expected_mobile}

    await message.answer(
        f"Hi {message.from_user.first_name}! 👋\n\n"
        f"Please verify your mobile number: +{expected_mobile}\n\n"
        "Tap the button below to share your phone number 👇",
        reply_markup=phone_keyboard()
    )

# ---------------- Contact Verification ----------------
@dp.message(F.contact)
async def handle_contact(message: Message):
    user_id = message.from_user.id
    user_phone = message.contact.phone_number.replace("+", "").strip()

    user_info = mobile_to_user.get(user_id)
    if not user_info:
        await message.answer("⚠️ Please restart the bot using your personal invite link.")
        return

    expected_mobile = user_info["expected_mobile"]

    # Compare mobile numbers
    if user_phone != expected_mobile:
        await message.answer(
            "❌ The shared phone number doesn’t match the one you registered with.\n"
            "Please restart the process using your registered number."
        )
        return

    # ✅ Mobile verified successfully
    mobile_to_user[expected_mobile] = user_id

    # Create single-use join link (valid for 1 hour)
    expire_at = int(time.time()) + 3600
    invite_link = await bot.create_chat_invite_link(
        chat_id=GROUP_ID,
        name=f"Personal link for {user_id}",
        expire_date=expire_at,
        member_limit=1,
        creates_join_request=True
    )

    # Map invite link → allowed user
    invite_to_user[invite_link.invite_link] = user_id

    await message.answer(
        "✅ Mobile number verified successfully!\n\n"
        "Here’s your personal join link (valid for 1 hour, single-use):\n\n"
        f"{invite_link.invite_link}\n\n"
        "⚠️ Only you can use this link. Others will be automatically declined."
    )

# ---------------- Handle Join Requests ----------------
@dp.chat_join_request()
async def handle_join_request(event: ChatJoinRequest):
    """
    Auto-approve/decline join requests based on invite link mapping.
    """
    allowed_user_id = None

    if event.invite_link:
        allowed_user_id = invite_to_user.get(event.invite_link.invite_link)

    if allowed_user_id and event.from_user.id == allowed_user_id:
        await bot.approve_chat_join_request(chat_id=event.chat.id, user_id=event.from_user.id)
        logging.info(f"✅ Approved join request from {event.from_user.id}")
    else:
        await bot.decline_chat_join_request(chat_id=event.chat.id, user_id=event.from_user.id)
        logging.info(f"🚫 Declined join request from {event.from_user.id}")

        try:
            await bot.send_message(
                chat_id=event.from_user.id,
                text=(
                    "❌ You are not authorized to join this group.\n"
                    "Please use the verified Telegram account that matches your registered mobile number."
                )
            )
        except Exception:
            pass  # User might have no open chat with bot

# ---------------- Main ----------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
