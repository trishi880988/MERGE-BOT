from dotenv import load_dotenv
load_dotenv("config.env", override=True)

import asyncio
import os
import shutil
import time
import logging
from typing import List, Dict, Optional, Union

import psutil
import pyromod
from PIL import Image
from pyrogram import Client, filters, enums
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from __init__ import (
    AUDIO_EXTENSIONS,
    BROADCAST_MSG,
    LOGGER,
    MERGE_MODE,
    SUBTITLE_EXTENSIONS,
    UPLOAD_AS_DOC,
    UPLOAD_TO_DRIVE,
    VIDEO_EXTENSIONS,
    bMaker,
    formatDB,
    gDict,
    queueDB,
    replyDB,
)
from config import Config
from helpers import database
from helpers.utils import (
    UserSettings, 
    get_readable_file_size, 
    get_readable_time,
    humanbytes,
    time_formatter
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class EnhancedMergeBot(Client):
    """
    Enhanced MergeBot with improved functionality and error handling
    """
    
    def __init__(self):
        super().__init__(
            name="merge-bot",
            api_hash=Config.API_HASH,
            api_id=Config.TELEGRAM_API,
            bot_token=Config.BOT_TOKEN,
            workers=300,
            plugins=dict(root="plugins"),
            app_version="6.0+enhanced-mergebot",
        )
        self.bot_start_time = time.time()
        self.user_bot = None
        self._init_directories()
        
    def _init_directories(self):
        """Initialize required directories"""
        os.makedirs("downloads", exist_ok=True)
        os.makedirs("logs", exist_ok=True)
        
    async def start(self):
        """Start the bot with enhanced initialization"""
        await super().start()
        
        # Initialize user bot if available
        if Config.USER_SESSION_STRING:
            try:
                self.user_bot = Client(
                    name="merge-bot-user",
                    session_string=Config.USER_SESSION_STRING,
                    no_updates=True,
                )
                await self.user_bot.start()
                user = await self.user_bot.get_me()
                Config.IS_PREMIUM = user.is_premium
                logger.info(f"User bot started (Premium: {Config.IS_PREMIUM})")
            except Exception as e:
                logger.error(f"Failed to start user bot: {e}")
                Config.IS_PREMIUM = False
        
        # Send startup notification
        try:
            await self.send_message(
                chat_id=int(Config.OWNER),
                text="<b>🤖 Bot Started Successfully!</b>",
                parse_mode=enums.ParseMode.HTML
            )
            if Config.LOGCHANNEL:
                await self.send_message(
                    chat_id=int(Config.LOGCHANNEL),
                    text="<b>🚀 Merge Bot Started!</b>\n\n"
                         f"<b>• Version:</b> 6.0\n"
                         f"<b>• Premium:</b> {Config.IS_PREMIUM}\n"
                         f"<b>• Uptime:</b> {time.ctime()}",
                    disable_web_page_preview=True
                )
        except Exception as e:
            logger.error(f"Startup notification failed: {e}")
            
        logger.info("Bot Started Successfully!")
        return self
        
    async def stop(self):
        """Stop the bot gracefully"""
        if self.user_bot:
            await self.user_bot.stop()
        await super().stop()
        logger.info("Bot Stopped Gracefully")
        
    async def restart(self):
        """Restart the bot"""
        logger.info("Restarting Bot...")
        await self.stop()
        await self.start()

merge_bot = EnhancedMergeBot()

# ================================================
#               Utility Functions
# ================================================

async def is_user_authorized(user_id: int, message: Message = None) -> bool:
    """
    Check if user is authorized to use the bot
    """
    user = UserSettings(user_id, message.from_user.first_name if message else "")
    
    if user.banned:
        if message:
            await message.reply_text(
                text="⛔ <b>Banned User Detected!</b>\n\n"
                     "🚫 Unfortunately you can't use this bot\n\n"
                     f"<b>Contact:</b> @{Config.OWNER_USERNAME}",
                quote=True
            )
        return False
    
    if user_id == int(Config.OWNER):
        user.allowed = True
        user.set()
        return True
        
    if not user.allowed and message:
        await message.reply_text(
            text="🔒 <b>Access Denied</b>\n\n"
                 "You need to login first to use this bot.\n\n"
                 "<b>Command:</b> <code>/login password</code>",
            quote=True
        )
        return False
        
    return True

async def cleanup_files(user_id: int):
    """Cleanup user files after operation"""
    user_dir = f"downloads/{user_id}"
    if os.path.exists(user_dir):
        try:
            shutil.rmtree(user_dir)
            logger.info(f"Cleaned up files for user {user_id}")
        except Exception as e:
            logger.error(f"Error cleaning files for user {user_id}: {e}")

async def generate_stats():
    """Generate system statistics"""
    current_time = get_readable_time(time.time() - merge_bot.bot_start_time)
    
    # System stats
    total, used, free = shutil.disk_usage(".")
    cpu_usage = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    
    # Network stats
    net_io = psutil.net_io_counters()
    
    # Bot stats
    db_stats = await database.get_stats()
    
    stats = (
        f"<b>╭──「 📊 SYSTEM STATISTICS 」──╮</b>\n"
        f"<b>│</b>\n"
        f"<b>├⏳ Bot Uptime:</b> <code>{current_time}</code>\n"
        f"<b>├💾 Disk Space:</b> <code>{humanbytes(total)}</code>\n"
        f"<b>├📀 Used Space:</b> <code>{humanbytes(used)} ({disk}%)</code>\n"
        f"<b>├💿 Free Space:</b> <code>{humanbytes(free)}</code>\n"
        f"<b>├🖥 CPU Usage:</b> <code>{cpu_usage}%</code>\n"
        f"<b>├⚙️ RAM Usage:</b> <code>{memory}%</code>\n"
        f"<b>├🔺 Upload:</b> <code>{humanbytes(net_io.bytes_sent)}</code>\n"
        f"<b>├🔻 Download:</b> <code>{humanbytes(net_io.bytes_recv)}</code>\n"
        f"<b>│</b>\n"
        f"<b>├👤 Total Users:</b> <code>{db_stats.get('total_users', 0)}</code>\n"
        f"<b>├✅ Allowed Users:</b> <code>{db_stats.get('allowed_users', 0)}</code>\n"
        f"<b>╰❌ Banned Users:</b> <code>{db_stats.get('banned_users', 0)}</code>"
    )
    
    return stats

# ================================================
#               Message Handlers
# ================================================

@merge_bot.on_message(filters.command(["start", "help"]) & filters.private)
async def start_handler(client: Client, message: Message):
    """Handle start and help commands"""
    if not await is_user_authorized(message.from_user.id, message):
        return
        
    if "help" in message.text.lower():
        await message.reply_text(
            text="""📚 <b>Merge Bot Help Guide</b>

1. <b>Set Thumbnail</b> (optional):
   - Send an image as thumbnail or use /savethumb command

2. <b>Send Files to Merge</b>:
   - Send videos/audios/subtitles based on your current mode

3. <b>Merge Options</b>:
   - Choose merge settings when ready

4. <b>Upload Mode</b>:
   - Select how you want the merged file to be uploaded

5. <b>Rename</b> (optional):
   - Set custom filename or use default

<b>Commands:</b>
- /mode - Change merge mode
- /settings - Configure bot settings
- /stats - Show bot statistics
- /login - Authenticate to use bot
- /help - Show this message""",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Close", callback_data="close")]
            ]),
            disable_web_page_preview=True
        )
        return
        
    # Welcome message for /start
    await message.reply_text(
        text=f"👋 <b>Hello {message.from_user.first_name}!</b>\n\n"
             "⚡ I'm an advanced file merger bot that can:\n"
             "• Merge multiple videos\n"
             "• Merge video with audio\n" 
             "• Add subtitles to videos\n"
             "• Extract audio/subtitles\n\n"
             "📌 Use /help to see how to use me",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆘 Help", callback_data="help"),
             InlineKeyboardButton("ℹ️ About", callback_data="about")],
            [InlineKeyboardButton("🔧 Settings", callback_data="settings")]
        ])
    )

@merge_bot.on_message(filters.command(["stats"]) & filters.private)
async def stats_handler(client: Client, message: Message):
    """Handle stats command"""
    if not await is_user_authorized(message.from_user.id, message):
        return
        
    stats = await generate_stats()
    await message.reply_text(
        text=stats,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_stats"),
             InlineKeyboardButton("❌ Close", callback_data="close")]
        ])
    )

@merge_bot.on_message(filters.command(["log"]) & filters.user(Config.OWNER_USERNAME))
async def send_log_file(client: Client, message: Message):
    """Send log file to owner"""
    try:
        await message.reply_document(
            document="./mergebotlog.txt",
            caption="📄 <b>Bot Log File</b>"
        )
    except Exception as e:
        await message.reply_text(f"❌ Failed to send log file: {e}")

@merge_bot.on_message(filters.command(["restart"]) & filters.user(Config.OWNER_USERNAME))
async def restart_bot(client: Client, message: Message):
    """Restart the bot (owner only)"""
    msg = await message.reply_text("🔄 <b>Restarting bot...</b>")
    await merge_bot.restart()
    await msg.edit_text("✅ <b>Bot restarted successfully!</b>")

# ================================================
#               File Processing
# ================================================

@merge_bot.on_message(
    (filters.document | filters.video | filters.audio) & filters.private
)
async def files_handler(client: Client, message: Message):
    """Handle incoming files for merging"""
    user_id = message.from_user.id
    if not await is_user_authorized(user_id, message):
        return
        
    user = UserSettings(user_id, message.from_user.first_name)
    
    # Check if user is in extract mode
    if user.merge_mode == 4:
        return
        
    # Check for existing process
    input_file = f"downloads/{user_id}/input.txt"
    if os.path.exists(input_file):
        await message.reply_text(
            "⏳ <b>Another process is already running!</b>\n"
            "Please wait for it to complete or /cancel it",
            quote=True
        )
        return
        
    media = message.video or message.document or message.audio
    if not media or not media.file_name:
        await message.reply_text("❌ <b>Invalid file detected</b>", quote=True)
        return
        
    file_ext = media.file_name.rsplit(".", 1)[-1].lower()
    
    # Handle config files
    if file_ext == "conf":
        await message.reply_text(
            text="🔧 <b>Config file detected!</b>\nDo you want to save it?",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes", callback_data="rclone_save"),
                    InlineKeyboardButton("❌ No", callback_data="rclone_discard")
                ]
            ]),
            quote=True
        )
        return
        
    # Process based on merge mode
    if user.merge_mode == 1:
        await handle_video_merge(client, message, user, file_ext)
    elif user.merge_mode == 2:
        await handle_audio_merge(client, message, user, file_ext)
    elif user.merge_mode == 3:
        await handle_subtitle_merge(client, message, user, file_ext)

async def handle_video_merge(
    client: Client, 
    message: Message, 
    user: UserSettings,
    file_ext: str
):
    """Handle video merge mode"""
    if queueDB.get(user.user_id) is None:
        formatDB[user.user_id] = file_ext
        
    if formatDB.get(user.user_id) and file_ext != formatDB[user.user_id]:
        await message.reply_text(
            f"❌ <b>File type mismatch!</b>\n"
            f"You first sent a {formatDB[user.user_id].upper()} file. "
            f"Now send only that type.",
            quote=True
        )
        return
        
    if file_ext not in VIDEO_EXTENSIONS:
        await message.reply_text(
            "❌ <b>Unsupported video format!</b>\n"
            "Only MP4, MKV or WEBM files are allowed.",
            quote=True
        )
        return
        
    editable = await message.reply_text("⏳ <b>Processing file...</b>", quote=True)
    
    # Initialize queue if not exists
    if queueDB.get(user.user_id) is None:
        queueDB[user.user_id] = {"videos": [], "subtitles": [], "audios": []}
        
    videos = queueDB[user.user_id]["videos"]
    
    if len(videos) >= 10:
        await editable.edit_text(
            "⚠️ <b>Maximum limit reached!</b>\n"
            "You can merge up to 10 videos at once.",
            reply_markup=await make_buttons(client, message, queueDB)
        )
        return
        
    # Add video to queue
    videos.append(message.id)
    queueDB[user.user_id]["subtitles"].append(None)
    
    if len(videos) == 1:
        reply = await editable.edit(
            "📤 <b>Send more videos to merge</b>\n"
            "You can send up to 10 videos",
            reply_markup=InlineKeyboardMarkup(
                bMaker.makebuttons(["❌ Cancel"], ["cancel"])
            )
        )
        replyDB[user.user_id] = reply.id
        return
        
    if replyDB.get(user.user_id):
        await client.delete_messages(
            chat_id=message.chat.id,
            message_ids=replyDB[user.user_id]
        )
        
    message_text = (
        "✅ <b>Video added to queue!</b>\n"
        "Send more videos or press <b>Merge Now</b>"
    )
    
    if len(videos) == 10:
        message_text = "✅ <b>Maximum videos reached!</b>\nPress <b>Merge Now</b>"
        
    markup = await make_buttons(client, message, queueDB)
    reply = await editable.edit_text(
        text=message_text,
        reply_markup=InlineKeyboardMarkup(markup)
    )
    replyDB[user.user_id] = reply.id

# ================================================
#               Button Handlers
# ================================================

@merge_bot.on_callback_query(filters.regex(r"^showFileName_"))
async def show_filename(client: Client, callback: CallbackQuery):
    """Show details of a specific file"""
    try:
        message_id = int(callback.data.split("_", 1)[1])
        msg = await client.get_messages(
            chat_id=callback.message.chat.id,
            message_ids=message_id
        )
        
        media = msg.video or msg.document or msg.audio
        if not media:
            await callback.answer("File not found", show_alert=True)
            return
            
        file_size = humanbytes(media.file_size)
        duration = get_readable_time(media.duration) if hasattr(media, 'duration') else "N/A"
        
        text = (
            f"📄 <b>File Name:</b> <code>{media.file_name}</code>\n"
            f"📦 <b>Size:</b> <code>{file_size}</code>\n"
            f"⏱ <b>Duration:</b> <code>{duration}</code>\n"
            f"🆔 <b>Message ID:</b> <code>{message_id}</code>"
        )
        
        await callback.message.reply_text(text, quote=True)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in show_filename: {e}")
        await callback.answer("Failed to get file info", show_alert=True)

@merge_bot.on_callback_query(filters.regex(r"^refresh_stats$"))
async def refresh_stats(client: Client, callback: CallbackQuery):
    """Refresh statistics"""
    try:
        stats = await generate_stats()
        await callback.message.edit_text(
            text=stats,
            reply_markup=callback.message.reply_markup
        )
        await callback.answer("Stats refreshed!")
    except Exception as e:
        logger.error(f"Error refreshing stats: {e}")
        await callback.answer("Failed to refresh stats", show_alert=True)

# ================================================
#               Main Execution
# ================================================

if __name__ == "__main__":
    logger.info("Starting Merge Bot...")
    try:
        merge_bot.run()
    except Exception as e:
        logger.critical(f"Bot crashed: {e}")
    finally:
        logger.info("Bot stopped")
