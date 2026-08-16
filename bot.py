import os
import time
import asyncio
from pyrogram import Client, filters
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
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))  # Admin/Owner Telegram User ID

# --- Database Setup ---
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["TelegramAutoAcceptBot"]
users_col = db["users"]
settings_col = db["settings"]
channels_col = db["channels"]
broadcast_col = db["last_broadcast"]

app = Client("auto_accept_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Defaults
DEFAULT_WELCOME = "नमस्कार! चॅनलमधील तुमची विनंती स्वीकारली गेली आहे. खाली दिलेल्या बॅकअप चॅनलला नक्की जॉईन करा."
DEFAULT_BACKUP = "https://t.me/telegram"

async def get_settings():
    settings = await settings_col.find_one({"_id": "bot_settings"})
    if not settings:
        data = {"_id": "bot_settings", "welcome": DEFAULT_WELCOME, "backup": DEFAULT_BACKUP}
        await settings_col.insert_one(data)
        return data
    return settings

# Admin Setup: Admin-only commands menu
async def setup_admin_menu():
    admin_commands = [
        BotCommand("start", "Start Bot"),
        BotCommand("stats", "View Statistics"),
        BotCommand("users", "Total Users"),
        BotCommand("ping", "Response Latency"),
        BotCommand("backup", "Change Backup Link"),
        BotCommand("setwelcome", "Set Welcome Message"),
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

# Admin Filter
def is_admin(_, __, message: Message):
    return message.from_user and message.from_user.id == ADMIN_ID


# 1. AUTO ACCEPT JOIN REQUESTS
@app.on_chat_join_request()
async def auto_accept(client: Client, req: ChatJoinRequest):
    user_id = req.from_user.id
    chat_id = req.chat.id
    
    # User ID Database मध्ये कायमस्वरूपी save करणे
    await users_col.update_one({"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)
    
    # Request Accept करणे
    try:
        await client.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
    except Exception as e:
        print(f"Approve Error: {e}")

    # Welcome Message व Backup Link पाठवणे
    settings = await get_settings()
    welcome_text = settings.get("welcome", DEFAULT_WELCOME)
    backup_link = settings.get("backup", DEFAULT_BACKUP)
    
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Join Backup Channel", url=backup_link)]])
    
    try:
        await client.send_message(
            chat_id=user_id,
            text=f"{welcome_text}\n\n👉 **Backup Channel:** {backup_link}",
            reply_markup=buttons,
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Direct Message Error: {e}")


# 2. BOT COMMANDS

@app.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    await users_col.update_one({"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)
    await message.reply_text("👋 हा Bot चॅनलच्या सर्व Join Requests आपोआप accept करतो.")

@app.on_message(filters.command("ping"))
async def ping_cmd(client: Client, message: Message):
    start_time = time.time()
    msg = await message.reply_text("Pinging...")
    end_time = time.time()
    latency = round((end_time - start_time) * 1000, 2)
    await msg.edit_text(f"🏓 **Pong!** Latency: `{latency}ms`")

@app.on_message(filters.command("stats") & filters.create(is_admin))
async def stats_cmd(client: Client, message: Message):
    total_users = await users_col.count_documents({})
    total_channels = await channels_col.count_documents({})
    await message.reply_text(f"📊 **Bot Statistics:**\n\n👥 Total Users: `{total_users}`\n📢 Registered Channels: `{total_channels}`")

@app.on_message(filters.command("users") & filters.create(is_admin))
async def users_cmd(client: Client, message: Message):
    total_users = await users_col.count_documents({})
    await message.reply_text(f"👥 Total Saved Users: `{total_users}`")

@app.on_message(filters.command("backup") & filters.create(is_admin))
async def set_backup_link(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("वापर: `/backup https://t.me/your_channel`")
    link = message.command[1]
    await settings_col.update_one({"_id": "bot_settings"}, {"$set": {"backup": link}}, upsert=True)
    await message.reply_text(f"✅ Backup link अपडेट झाली:\n`{link}`")

@app.on_message(filters.command("setwelcome") & filters.create(is_admin))
async def set_welcome_msg(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("वापर: `/setwelcome मेसेज इथे लिहा`")
    new_text = message.text.split(None, 1)[1]
    await settings_col.update_one({"_id": "bot_settings"}, {"$set": {"welcome": new_text}}, upsert=True)
    await message.reply_text("✅ Welcome Message यशस्वीरीत्या सेट झाला!")

@app.on_message(filters.command("addchannel"))
async def add_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("वापर: `/addchannel -100xxxxxxxxxx`\n\n(टीप: Bot ला आधी चॅनलमध्ये Admin बनवा.)")
    try:
        chat_id = int(message.command[1])
        member = await client.get_chat_member(chat_id, (await client.get_me()).id)
        if member.privileges and member.privileges.can_invite_users:
            await channels_col.update_one(
                {"chat_id": chat_id},
                {"$set": {"chat_id": chat_id, "added_by": message.from_user.id}},
                upsert=True
            )
            await message.reply_text(f"✅ चॅनल `{chat_id}` यशस्वीरीत्या रजिस्टर झाले आहे!")
        else:
            await message.reply_text("❌ Bot कडे चॅनलमध्ये 'Invite Users via Link' चे Admin Rights नाहीत.")
    except Exception as e:
        await message.reply_text(f"❌ त्रुटी: {e}")

@app.on_message(filters.command("mychannels"))
async def my_channels_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    channels = channels_col.find({"added_by": user_id})
    res = "📢 **तुमची जोडलेली चॅनेल्स:**\n\n"
    count = 0
    async for c in channels:
        count += 1
        res += f"{count}. `{c['chat_id']}`\n"
    if count == 0:
        res = "❌ तुम्ही अद्याप कोणतेही चॅनल ॲड केलेले नाही."
    await message.reply_text(res)


# 3. ADVANCED BROADCAST (Photo, Video, Text - No Forward Tag)
@app.on_message(filters.command("broadcast") & filters.create(is_admin))
async def broadcast_handler(client: Client, message: Message):
    target_msg = message.reply_to_message if message.reply_to_message else None
    text_content = message.text.split(None, 1)[1] if len(message.command) > 1 else None

    if not target_msg and not text_content:
        return await message.reply_text("❌ कोणत्याही मेसेज/फोटो/व्हिडिओला Reply करून `/broadcast` पाठवा किंवा `/broadcast मजकूर` टाईप करा.")

    # जुना डिलीट डेटाबेस रिकामा करणे
    await broadcast_col.delete_many({})

    status_msg = await message.reply_text("🚀 ब्रॉडकास्ट सुरू होत आहे...")
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

        # दर ५० मेसेजनंतर डेटाबेसमध्ये बॅच सेव्ह करणे
        if len(broadcast_batch) >= 50:
            await broadcast_col.insert_many(broadcast_batch)
            broadcast_batch = []

    if broadcast_batch:
        await broadcast_col.insert_many(broadcast_batch)

    await status_msg.edit_text(
        f"✅ **ब्रॉडकास्ट पूर्ण!**\n\n"
        f"📤 यशस्वी: `{success}`\n"
        f"🚫 अयशस्वी (Blocked/Deleted): `{failed}`"
    )


# 4. FORWARD BROADCAST (With Forward Tag)
@app.on_message(filters.command("fbroadcast") & filters.create(is_admin))
async def forward_broadcast(client: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply_text("मेसेजला reply करून `/fbroadcast` टाईप करा.")

    await broadcast_col.delete_many({})
    status_msg = await message.reply_text("🚀 फॉरवर्ड ब्रॉडकास्ट सुरू होत आहे...")
    
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
        f"✅ **फॉरवर्ड ब्रॉडकास्ट पूर्ण!**\n\n"
        f"📤 यशस्वी: `{success}`\n"
        f"🚫 अयशस्वी: `{failed}`"
    )


# 5. DELETE LAST BROADCAST (Direct from MongoDB)
@app.on_message(filters.command("delete") & filters.create(is_admin))
async def delete_last_broadcast(client: Client, message: Message):
    records = await broadcast_col.find({}).to_list(length=None)
    
    if not records:
        return await message.reply_text("❌ डिलीट करण्यासाठी कोणताही अलीकडचा ब्रॉडकास्ट डेटा सापडला नाही.")

    msg = await message.reply_text("🗑️ सर्व युझर्सकडून मेसेज डिलीट करणे सुरू आहे...")
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
    await msg.edit_text(f"✅ एकूण `{deleted}` युझर्सच्या इनबॉक्समधून शेवटचा ब्रॉडकास्ट डिलीट केला गेला!")


# 6. RESTART & HELP
@app.on_message(filters.command("restart") & filters.create(is_admin))
async def restart_bot(client: Client, message: Message):
    await message.reply_text("🔄 Bot रीस्टार्ट होत आहे...")
    os._exit(0)

@app.on_message(filters.command("help"))
async def help_cmd(client: Client, message: Message):
    help_text = (
        "📖 **Bot मदत केंद्र:**\n\n"
        "1. Bot ला चॅनलमध्ये Admin करा आणि 'Invite Users via Link' परवानगी द्या.\n"
        "2. `/addchannel <Channel_ID>` ने चॅनल जोडा.\n"
        "3. चॅनलवर येणाऱ्या सर्व Join Requests आपोआप स्वीकरल्या जातील व युझरला वेलकम मेसेज पाठवला जाईल."
    )
    await message.reply_text(help_text)


# Bot Startup
async def on_startup():
    await app.start()
    await setup_admin_menu()
    print("Bot is up and running successfully!")

if __name__ == "__main__":
    app.run(on_startup())
