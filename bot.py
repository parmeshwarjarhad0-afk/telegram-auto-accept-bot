import os
import time
import asyncio
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, ChatJoinRequest, BotCommand, 
    BotCommandScopeChat, InlineKeyboardMarkup, InlineKeyboardButton
)
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from motor.motor_asyncio import AsyncIOMotorClient

# --- Environment Variables ---
API_ID = int(os.environ.get("API_ID", "123456"))
API_HASH = os.environ.get("API_HASH", "your_api_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
MONGO_URL = os.environ.get("MONGO_URL", "your_mongodb_connection_string")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

# --- Database Setup ---
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["TelegramAutoAcceptBot"]
users_col = db["users"]
settings_col = db["settings"]
channels_col = db["channels"]
broadcast_col = db["last_broadcast"]

app = Client("auto_accept_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Default Backup Link
DEFAULT_BACKUP = "https://t.me/+zBROkdncuC5iMzdl"

# 3 Languages Messages
WELCOME_MULTI_LANG = (
    "✅ **Request Approved! / विनंती स्वीकारली! / अनुरोध स्वीकृत!**\n\n"
    "🇬🇧 **English:** Your request to join the channel has been approved. Make sure to click **'Verify Account'** below to receive all future updates.\n\n"
    "🇮🇳 **मराठी:** चॅनलमधील तुमची विनंती स्वीकारली गेली आहे. पुढील सर्व अपडेट्स मिळवण्यासाठी खालील **'Verify Account'** बटणावर नक्की क्लिक करा.\n\n"
    "🇮🇳 **हिंदी:** चैनल में आपका अनुरोध स्वीकार कर लिया गया है। आगे के सभी अपडेट्स पाने के लिए नीचे दिए गए **'Verify Account'** बटन पर अवश्य क्लिक करें।"
)

REMINDER_MULTI_LANG = (
    "🔔 **Reminder / आठवण / रिमाइंडर**\n\n"
    "🇬🇧 **English:** You joined the channel 1 day ago but haven't verified your account yet. Click below to verify.\n\n"
    "🇮🇳 **मराठी:** तुम्ही १ दिवसापूर्वी चॅनल जॉईन केले आहे पण अद्याप अकाउंट व्हेरिफाय केलेले नाही. अपडेट्ससाठी खालील बटणावर क्लिक करा.\n\n"
    "🇮🇳 **हिंदी:** आपने १ दिन पहले चैनल जॉइन किया था लेकिन अभी तक अकाउंट वेरिफाई नहीं किया है। अपडेट्स के लिए नीचे क्लिक करें।"
)

async def get_backup_link():
    settings = await settings_col.find_one({"_id": "bot_settings"})
    if not settings:
        data = {"_id": "bot_settings", "backup": DEFAULT_BACKUP}
        await settings_col.insert_one(data)
        return DEFAULT_BACKUP
    return settings.get("backup", DEFAULT_BACKUP)

async def setup_admin_menu():
    admin_commands = [
        BotCommand("start", "Start Bot"),
        BotCommand("stats", "View Statistics"),
        BotCommand("users", "Total Users"),
        BotCommand("ping", "Response Latency"),
        BotCommand("backup", "Change Backup Link"),
        BotCommand("broadcast", "Send Text/Media Broadcast"),
        BotCommand("fbroadcast", "Send Forward Broadcast"),
        BotCommand("delete", "Delete Last Broadcast"),
        BotCommand("addchannel", "Add Channel"),
        BotCommand("mychannels", "View My Channels"),
        BotCommand("restart", "Restart Bot"),
        BotCommand("help", "Show Help")
    ]
    try:
        await app.set_bot_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    except Exception as e:
        print(f"Error setting admin commands: {e}")

def is_admin(_, __, message: Message):
    return message.from_user and message.from_user.id == ADMIN_ID


# 1. AUTO ACCEPT JOIN REQUESTS
@app.on_chat_join_request()
async def auto_accept(client: Client, req: ChatJoinRequest):
    user_id = req.from_user.id
    chat_id = req.chat.id
    current_time = time.time()
    
    # Save User Details
    await users_col.update_one(
        {"user_id": user_id},
        {
            "$setOnInsert": {
                "user_id": user_id,
                "joined_at": current_time,
                "is_verified": False,
                "reminder_sent": False
            }
        },
        upsert=True
    )
    
    # Approve Request
    try:
        await client.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
    except Exception as e:
        print(f"Approve Error: {e}")

    # Send Welcome Message
    backup_link = await get_backup_link()
    bot_info = await client.get_me()
    verify_link = f"https://t.me/{bot_info.username}?start=verified"

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Verify Account / खाते अधिकृत करा", url=verify_link)],
        [InlineKeyboardButton("🔗 Join Backup Channel", url=backup_link)]
    ])
    
    try:
        await client.send_message(
            chat_id=user_id,
            text=f"{WELCOME_MULTI_LANG}\n\n👉 **Backup Channel:** {backup_link}",
            reply_markup=buttons,
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Direct Message Error: {e}")


# 2. START / VERIFICATION HANDLER
@app.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "is_verified": True}},
        upsert=True
    )
    
    if len(message.command) > 1 and message.command[1] == "verified":
        backup_link = await get_backup_link()
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Join Backup Channel", url=backup_link)]])
        
        verified_text = (
            "🎉 **Account Verified Successfully!**\n\n"
            "🇬🇧 Now you will directly receive all channel updates.\n"
            "🇮🇳 आता तुम्हाला चॅनलचे सर्व अपडेट्स थेट मिळतील.\n"
            "🇮🇳 अब आपको चैनल के सभी अपडेट्स सीधे मिलेंगे।"
        )
        await message.reply_text(verified_text, reply_markup=buttons)
    else:
        await message.reply_text("👋 Hello! This bot automatically approves channel join requests.")


# 3. 1-DAY AUTO REMINDER BACKGROUND TASK
async def auto_verify_reminder_task():
    while True:
        try:
            one_day_ago = time.time() - (1 * 24 * 60 * 60) # १ दिवस = ८६,४०० सेकंद
            
            query = {
                "joined_at": {"$lte": one_day_ago},
                "is_verified": False,
                "reminder_sent": False
            }
            
            bot_info = await app.get_me()
            verify_link = f"https://t.me/{bot_info.username}?start=verified"
            backup_link = await get_backup_link()

            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Verify Account / खाते अधिकृत करा", url=verify_link)],
                [InlineKeyboardButton("🔗 Join Backup Channel", url=backup_link)]
            ])

            cursor = users_col.find(query)
            async for user in cursor:
                uid = user["user_id"]
                try:
                    await app.send_message(
                        chat_id=uid,
                        text=f"{REMINDER_MULTI_LANG}\n\n👉 **Backup Channel:** {backup_link}",
                        reply_markup=buttons,
                        disable_web_page_preview=True
                    )
                    await users_col.update_one({"user_id": uid}, {"$set": {"reminder_sent": True}})
                    await asyncio.sleep(0.1)
                except Exception:
                    await users_col.update_one({"user_id": uid}, {"$set": {"reminder_sent": True}})

        except Exception as e:
            print(f"Reminder loop error: {e}")

        # दर १ तासाने डेटाबेस तपासा
        await asyncio.sleep(3600)


# 4. ADMIN & MANAGEMENT COMMANDS
@app.on_message(filters.command("ping"))
async def ping_cmd(client: Client, message: Message):
    start_time = time.time()
    msg = await message.reply_text("Pinging...")
    latency = round((time.time() - start_time) * 1000, 2)
    await msg.edit_text(f"🏓 **Pong!** Latency: `{latency}ms`")

@app.on_message(filters.command("stats") & filters.create(is_admin))
async def stats_cmd(client: Client, message: Message):
    total_users = await users_col.count_documents({})
    verified_users = await users_col.count_documents({"is_verified": True})
    total_channels = await channels_col.count_documents({})
    await message.reply_text(
        f"📊 **Bot Statistics:**\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"✅ Verified Users: `{verified_users}`\n"
        f"⏳ Unverified Users: `{total_users - verified_users}`\n"
        f"📢 Registered Channels: `{total_channels}`"
    )

@app.on_message(filters.command("users") & filters.create(is_admin))
async def users_cmd(client: Client, message: Message):
    total_users = await users_col.count_documents({})
    await message.reply_text(f"👥 Total Saved Users: `{total_users}`")

@app.on_message(filters.command("backup") & filters.create(is_admin))
async def set_backup_link(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/backup https://t.me/your_channel`")
    link = message.command[1]
    await settings_col.update_one({"_id": "bot_settings"}, {"$set": {"backup": link}}, upsert=True)
    await message.reply_text(f"✅ Backup link updated successfully:\n`{link}`")

@app.on_message(filters.command("addchannel"))
async def add_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/addchannel -100xxxxxxxxxx`\n\n(Note: Bot must be channel Admin first.)")
    try:
        chat_id = int(message.command[1])
        member = await client.get_chat_member(chat_id, (await client.get_me()).id)
        if member.privileges and member.privileges.can_invite_users:
            await channels_col.update_one(
                {"chat_id": chat_id},
                {"$set": {"chat_id": chat_id, "added_by": message.from_user.id}},
                upsert=True
            )
            await message.reply_text(f"✅ Channel `{chat_id}` has been registered successfully!")
        else:
            await message.reply_text("❌ Bot does not have 'Invite Users via Link' admin rights.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("mychannels"))
async def my_channels_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    channels = channels_col.find({"added_by": user_id})
    res = "📢 **Your Registered Channels:**\n\n"
    count = 0
    async for c in channels:
        count += 1
        res += f"{count}. `{c['chat_id']}`\n"
    if count == 0:
        res = "❌ You haven't added any channels yet."
    await message.reply_text(res)


# 5. BROADCAST HANDLERS
@app.on_message(filters.command("broadcast") & filters.create(is_admin))
async def broadcast_handler(client: Client, message: Message):
    target_msg = message.reply_to_message if message.reply_to_message else None
    text_content = message.text.split(None, 1)[1] if len(message.command) > 1 else None

    if not target_msg and not text_content:
        return await message.reply_text("❌ Reply to a message with `/broadcast` or type `/broadcast text`.")

    await broadcast_col.delete_many({})
    status_msg = await message.reply_text("🚀 Starting broadcast...")
    users = users_col.find({})
    success, failed = 0, 0
    broadcast_batch = []

    async for user in users:
        uid = user["user_id"]
        try:
            if target_msg:
                sent = await target_msg.copy(chat_id=uid)
            else:
                sent = await client.send_message(chat_id=uid, text=text_content)

            broadcast_batch.append({"user_id": uid, "msg_id": sent.id})
            success += 1
            await asyncio.sleep(0.04)

        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            if target_msg:
                sent = await target_msg.copy(chat_id=uid)
            else:
                sent = await client.send_message(chat_id=uid, text=text_content)
            broadcast_batch.append({"user_id": uid, "msg_id": sent.id})
            success += 1

        except (UserIsBlocked, InputUserDeactivated):
            failed += 1
        except Exception:
            failed += 1

        if len(broadcast_batch) >= 50:
            await broadcast_col.insert_many(broadcast_batch)
            broadcast_batch = []

    if broadcast_batch:
        await broadcast_col.insert_many(broadcast_batch)

    await status_msg.edit_text(
        f"✅ **Broadcast Completed!**\n\n"
        f"📤 Successful: `{success}`\n"
        f"🚫 Failed: `{failed}`"
    )

@app.on_message(filters.command("fbroadcast") & filters.create(is_admin))
async def forward_broadcast(client: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply_text("Please reply to a message with `/fbroadcast`.")

    await broadcast_col.delete_many({})
    status_msg = await message.reply_text("🚀 Starting forward broadcast...")
    
    users = users_col.find({})
    success, failed = 0, 0
    broadcast_batch = []

    async for user in users:
        uid = user["user_id"]
        try:
            sent = await message.reply_to_message.forward(chat_id=uid)
            broadcast_batch.append({"user_id": uid, "msg_id": sent.id})
            success += 1
            await asyncio.sleep(0.04)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            sent = await message.reply_to_message.forward(chat_id=uid)
            broadcast_batch.append({"user_id": uid, "msg_id": sent.id})
            success += 1
        except (UserIsBlocked, InputUserDeactivated):
            failed += 1
        except Exception:
            failed += 1

        if len(broadcast_batch) >= 50:
            await broadcast_col.insert_many(broadcast_batch)
            broadcast_batch = []

    if broadcast_batch:
        await broadcast_col.insert_many(broadcast_batch)

    await status_msg.edit_text(
        f"✅ **Forward Broadcast Completed!**\n\n"
        f"📤 Successful: `{success}`\n"
        f"🚫 Failed: `{failed}`"
    )

@app.on_message(filters.command("delete") & filters.create(is_admin))
async def delete_last_broadcast(client: Client, message: Message):
    records = await broadcast_col.find({}).to_list(length=None)
    if not records:
        return await message.reply_text("❌ No recent broadcast records found to delete.")

    msg = await message.reply_text("🗑️ Deleting broadcast messages from all users...")
    deleted = 0

    for item in records:
        uid = item["user_id"]
        msg_id = item["msg_id"]
        try:
            await client.delete_messages(chat_id=uid, message_ids=msg_id)
            deleted += 1
            await asyncio.sleep(0.03)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await client.delete_messages(chat_id=uid, message_ids=msg_id)
            deleted += 1
        except Exception:
            pass

    await broadcast_col.delete_many({})
    await msg.edit_text(f"✅ Successfully deleted the last broadcast for `{deleted}` users!")

@app.on_message(filters.command("restart") & filters.create(is_admin))
async def restart_bot(client: Client, message: Message):
    await message.reply_text("🔄 Bot is restarting...")
    os._exit(0)

@app.on_message(filters.command("help"))
async def help_cmd(client: Client, message: Message):
    help_text = (
        "📖 **Bot Help & Guide:**\n\n"
        "1. Promote the bot to Admin in your channel with 'Invite Users via Link' permission.\n"
        "2. Add your channel using `/addchannel <Channel_ID>`.\n"
        "3. All incoming join requests will be automatically approved."
    )
    await message.reply_text(help_text)


# Main Execution
async def main():
    await app.start()
    await setup_admin_menu()
    asyncio.create_task(auto_verify_reminder_task())
    print("Bot is up and running successfully!")
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
