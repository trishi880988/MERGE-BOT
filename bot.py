import os
import shutil
import time
import logging
import asyncio
from typing import List, Dict, Optional

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

from config import Config
from helpers.utils import (
    humanbytes,
    time_formatter,
    get_readable_time,
    UserSettings
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VideoMergerBot(Client):
    def __init__(self):
        super().__init__(
            name="video_merger_bot",
            api_id=Config.TELEGRAM_API,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            workers=200,
            plugins=dict(root="plugins")
        )
        self.queue = {}
        self.user_settings = {}
        self.bot_start_time = time.time()

    async def start(self):
        await super().start()
        logger.info("Bot started successfully")
        try:
            await self.send_message(
                Config.OWNER,
                "🚀 Bot Started Successfully!"
            )
        except Exception as e:
            logger.error(f"Failed to send startup message: {e}")

    async def stop(self):
        await super().stop()
        logger.info("Bot stopped")

    async def add_to_queue(self, user_id: int, message: Message):
        """Add video to user's merge queue"""
        if user_id not in self.queue:
            self.queue[user_id] = {
                'videos': [],
                'status': 'waiting',
                'start_time': None,
                'last_msg': None
            }
        
        media = message.video or message.document
        if not media:
            return False

        self.queue[user_id]['videos'].append({
            'message_id': message.id,
            'file_name': media.file_name,
            'file_size': media.file_size,
            'mime_type': media.mime_type
        })
        return True

    async def get_user_settings(self, user_id: int) -> UserSettings:
        """Get or create user settings"""
        if user_id not in self.user_settings:
            self.user_settings[user_id] = UserSettings(user_id, "")
        return self.user_settings[user_id]

bot = VideoMergerBot()

@bot.on_message(filters.command(["start"]) & filters.private)
async def start_handler(client: VideoMergerBot, message: Message):
    """Handle start command"""
    await message.reply_text(
        "🎥 Welcome to Video Merger Bot!\n\n"
        "Send me multiple videos to merge them together.\n"
        "Use /help for more instructions.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Help", callback_data="help")]
        ])
    )

@bot.on_message(filters.video | filters.document & filters.private)
async def video_handler(client: VideoMergerBot, message: Message):
    """Handle incoming videos"""
    user = await client.get_user_settings(message.from_user.id)
    
    if not user.allowed:
        await message.reply_text("You're not authorized to use this bot.")
        return

    # Check if file is video
    media = message.video or message.document
    if not media.mime_type.startswith('video/'):
        await message.reply_text("Please send video files only.")
        return

    # Add to queue
    added = await client.add_to_queue(message.from_user.id, message)
    if not added:
        await message.reply_text("Failed to add video to queue.")
        return

    queue_size = len(client.queue[message.from_user.id]['videos'])
    reply_msg = await message.reply_text(
        f"✅ Video added to queue!\n\n"
        f"📊 Queue size: {queue_size}\n"
        f"📌 Send more videos or press /merge when ready.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Merge Now", callback_data="merge_now")],
            [InlineKeyboardButton("Clear Queue", callback_data="clear_queue")]
        ])
    )

    # Store last message for editing
    client.queue[message.from_user.id]['last_msg'] = reply_msg.id

@bot.on_message(filters.command(["merge"]) & filters.private)
async def merge_handler(client: VideoMergerBot, message: Message):
    """Handle merge command"""
    user_id = message.from_user.id
    if user_id not in client.queue or not client.queue[user_id]['videos']:
        await message.reply_text("Your queue is empty!")
        return

    if len(client.queue[user_id]['videos']) < 2:
        await message.reply_text("You need at least 2 videos to merge!")
        return

    # Start merging process
    client.queue[user_id]['status'] = 'processing'
    client.queue[user_id]['start_time'] = time.time()

    status_msg = await message.reply_text(
        "🔄 Starting merge process...\n"
        "⏳ This may take some time depending on video sizes."
    )

    try:
        # Create download directory
        download_dir = f"downloads/{user_id}"
        os.makedirs(download_dir, exist_ok=True)

        # Download videos
        downloaded_files = []
        for idx, video in enumerate(client.queue[user_id]['videos']):
            try:
                file_path = f"{download_dir}/{video['file_name']}"
                await message.reply_chat_action(enums.ChatAction.UPLOAD_VIDEO)
                
                edit_text = (
                    f"📥 Downloading {idx+1}/{len(client.queue[user_id]['videos'])}\n"
                    f"📄 {video['file_name']}\n"
                    f"📦 {humanbytes(video['file_size'])}"
                )
                await status_msg.edit_text(edit_text)

                dl_msg = await client.get_messages(
                    message.chat.id,
                    video['message_id']
                )
                await dl_msg.download(file_name=file_path)
                downloaded_files.append(file_path)

            except Exception as e:
                logger.error(f"Failed to download {video['file_name']}: {e}")
                continue

        # Merge videos using FFmpeg
        if len(downloaded_files) >= 2:
            await status_msg.edit_text("🔄 Merging videos...")
            
            merged_file = f"{download_dir}/merged_{int(time.time())}.mp4"
            await merge_videos_ffmpeg(downloaded_files, merged_file)

            # Send merged file
            await status_msg.edit_text("✅ Merging complete! Uploading...")
            await message.reply_video(
                video=merged_file,
                caption="Here's your merged video!",
                progress=progress_callback,
                progress_args=(status_msg, time.time())
            )

            await status_msg.delete()

    except Exception as e:
        logger.error(f"Merge failed: {e}")
        await status_msg.edit_text(f"❌ Merge failed: {str(e)}")
    finally:
        # Cleanup
        shutil.rmtree(download_dir, ignore_errors=True)
        client.queue[user_id]['status'] = 'completed'
        client.queue.pop(user_id, None)

async def merge_videos_ffmpeg(input_files: List[str], output_file: str):
    """Merge videos using FFmpeg"""
    # Create input file list for FFmpeg
    list_file = f"{output_file}.txt"
    with open(list_file, 'w') as f:
        for file in input_files:
            f.write(f"file '{file}'\n")

    # FFmpeg command to concatenate videos
    cmd = [
        'ffmpeg',
        '-f', 'concat',
        '-safe', '0',
        '-i', list_file,
        '-c', 'copy',
        output_file,
        '-y'
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    await proc.communicate()
    os.remove(list_file)

async def progress_callback(current, total, status_msg, start_time):
    """Upload progress callback"""
    try:
        percent = current * 100 / total
        speed = current / (time.time() - start_time)
        eta = (total - current) / speed
        
        progress = "⬢" * int(percent // 5) + "⬡" * (20 - int(percent // 5))
        
        text = (
            f"📤 Uploading...\n\n"
            f"{progress} {percent:.1f}%\n"
            f"📦 {humanbytes(current)} / {humanbytes(total)}\n"
            f"⚡ {humanbytes(speed)}/s\n"
            f"⏳ ETA: {time_formatter(eta)}"
        )
        
        await status_msg.edit_text(text)
    except Exception as e:
        logger.error(f"Progress error: {e}")

@bot.on_message(filters.command(["queue"]) & filters.private)
async def show_queue(client: VideoMergerBot, message: Message):
    """Show current queue status"""
    user_id = message.from_user.id
    if user_id not in client.queue or not client.queue[user_id]['videos']:
        await message.reply_text("Your queue is empty!")
        return

    queue_text = "📋 Your Video Queue:\n\n"
    for idx, video in enumerate(client.queue[user_id]['videos']):
        queue_text += (
            f"{idx+1}. {video['file_name']}\n"
            f"   └ {humanbytes(video['file_size'])}\n"
        )

    await message.reply_text(
        queue_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Merge Now", callback_data="merge_now")],
            [InlineKeyboardButton("Clear Queue", callback_data="clear_queue")]
        ])
    )

if __name__ == "__main__":
    logger.info("Starting Video Merger Bot...")
    try:
        bot.run()
    except Exception as e:
        logger.critical(f"Bot crashed: {e}")
    finally:
        logger.info("Bot stopped")
