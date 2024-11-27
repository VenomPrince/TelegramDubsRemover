import os
import logging
import aiosqlite
import imagehash
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, ChatMemberHandler
import asyncio
import sys
import signal
import tempfile
import os.path

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class DuplicateMediaRemover:
    def __init__(self):
        self.db_path = 'media_hashes.db'
        
    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS media_hashes (
                    file_id TEXT PRIMARY KEY,
                    hash TEXT,
                    message_id INTEGER,
                    chat_id INTEGER,
                    media_type TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS whitelist (
                    file_id TEXT PRIMARY KEY
                )
            ''')
            await db.commit()

    async def is_duplicate(self, file_hash: str, chat_id: int) -> tuple:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT message_id FROM media_hashes WHERE hash = ? AND chat_id = ?',
                (file_hash, chat_id)
            )
            result = await cursor.fetchone()
            return (True, result[0]) if result else (False, None)

    async def store_hash(self, file_id: str, file_hash: str, message_id: int, 
                        chat_id: int, media_type: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT INTO media_hashes (file_id, hash, message_id, chat_id, media_type) VALUES (?, ?, ?, ?, ?)',
                (file_id, file_hash, message_id, chat_id, media_type)
            )
            await db.commit()

    async def is_whitelisted(self, file_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT file_id FROM whitelist WHERE file_id = ?',
                (file_id,)
            )
            return bool(await cursor.fetchone())

    async def whitelist_media(self, file_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT INTO whitelist (file_id) VALUES (?)',
                (file_id,)
            )
            await db.commit()

    async def get_stats(self, chat_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT COUNT(*) FROM media_hashes WHERE chat_id = ?',
                (chat_id,)
            )
            total = await cursor.fetchone()[0]

            cursor = await db.execute(
                'SELECT COUNT(*) FROM media_hashes WHERE chat_id = ? AND media_type = ?',
                (chat_id, 'photo')
            )
            photos = await cursor.fetchone()[0]

            cursor = await db.execute(
                'SELECT COUNT(*) FROM media_hashes WHERE chat_id = ? AND media_type = ?',
                (chat_id, 'video')
            )
            videos = await cursor.fetchone()[0]

            cursor = await db.execute(
                'SELECT COUNT(*) FROM media_hashes WHERE chat_id = ? AND media_type = ?',
                (chat_id, 'document')
            )
            documents = await cursor.fetchone()[0]

            return {
                'total': total,
                'photos': photos,
                'videos': videos,
                'documents': documents
            }

async def calculate_image_hash(photo_file) -> str:
    image_data = await photo_file.download_as_bytearray()
    image = Image.open(BytesIO(image_data))
    return str(imagehash.average_hash(image))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! I'm a Duplicate Media Remover bot. "
        "Add me to your channel as an admin, and I'll help keep it clean by removing duplicate media.\n\n"
        "Use /help to see available commands."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📋 Available Commands:
/start - Start the bot
/help - Show this help message
/stats - Show channel statistics
/scan - Scan channel history for duplicates
/whitelist - Whitelist the replied media

To use me:
1. Add me to your channel as an admin
2. Send /scan in the channel to find duplicates
3. I'll also detect new duplicates automatically
    """
    await update.message.reply_text(help_text)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming media messages"""
    message = update.message or update.channel_post
    if not message:
        return

    remover = context.bot_data.get('remover')
    if not remover:
        remover = DuplicateMediaRemover()
        await remover.init_db()
        context.bot_data['remover'] = remover

    file_id = None
    file_hash = None
    media_type = None

    try:
        if message.photo:
            file_id = message.photo[-1].file_id
            photo_file = await context.bot.get_file(file_id)
            file_hash = await calculate_image_hash(photo_file)
            media_type = 'photo'
        elif message.video:
            file_id = message.video.file_id
            file_hash = file_id  # Use file_id as hash for videos
            media_type = 'video'
        elif message.document:
            file_id = message.document.file_id
            file_hash = file_id  # Use file_id as hash for documents
            media_type = 'document'
        else:
            return

        # Check if media is whitelisted
        if await remover.is_whitelisted(file_id):
            return

        # Check for duplicates
        if await remover.is_duplicate(file_hash, message.chat_id):
            try:
                await message.delete()
                logger.info(f"Removed duplicate media: {file_id}")
            except Exception as e:
                logger.error(f"Error removing duplicate: {e}")
        else:
            await remover.store_hash(file_id, file_hash, message.message_id, message.chat_id, media_type)

    except Exception as e:
        logger.error(f"Error processing media: {e}")

async def whitelist_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Whitelist a media item to prevent it from being removed"""
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a media message to whitelist it.")
        return

    message = update.message.reply_to_message
    if not (message.photo or message.video or message.document):
        await update.message.reply_text("Please reply to a media message (photo/video/document).")
        return

    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.document:
        file_id = message.document.file_id

    remover = context.bot_data.get('remover')
    if not remover:
        remover = DuplicateMediaRemover()
        await remover.init_db()
        context.bot_data['remover'] = remover

    await remover.whitelist_media(file_id)
    await update.message.reply_text("✅ Media has been whitelisted and won't be removed as duplicate.")

async def channel_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show channel statistics"""
    chat = update.message.chat if update.message else update.channel_post.chat
    if not chat:
        return

    remover = context.bot_data.get('remover')
    if not remover:
        remover = DuplicateMediaRemover()
        await remover.init_db()
        context.bot_data['remover'] = remover

    stats = await remover.get_stats(chat.id)
    stats_text = f"""
📊 Channel Statistics:
Total Media: {stats['total']}
Photos: {stats['photos']}
Videos: {stats['videos']}
Documents: {stats['documents']}
    """
    if update.message:
        await update.message.reply_text(stats_text)
    else:
        await context.bot.send_message(chat_id=chat.id, text=stats_text)

async def scan_channel_history(bot, chat_id: int, remover: DuplicateMediaRemover):
    """Scan channel history using get_updates"""
    try:
        # Send initial message
        status_msg = await bot.send_message(
            chat_id=chat_id,
            text="🔍 Starting channel scan..."
        )

        media_hashes = {}
        duplicates_found = 0
        media_processed = 0
        
        try:
            # Get updates in smaller chunks to avoid timeouts
            offset = -1
            all_updates = []
            while True:
                updates = await bot.get_updates(
                    offset=offset,
                    limit=100,  # Process in smaller chunks
                    timeout=60
                )
                if not updates:
                    break
                    
                all_updates.extend(updates)
                offset = updates[-1].update_id + 1
                await asyncio.sleep(1)  # Rate limiting between chunks
                
        except Exception as e:
            logger.error(f"Error getting updates: {e}")
            return

        channel_updates = [u for u in all_updates if hasattr(u, 'channel_post') 
                         and u.channel_post 
                         and u.channel_post.chat.id == chat_id]

        total_messages = len(channel_updates)
        
        # Process each update
        for i, update in enumerate(channel_updates):
            try:
                # More aggressive rate limiting
                if i > 0 and i % 5 == 0:  # Every 5 messages instead of 10
                    await asyncio.sleep(1.0)  # Longer delay

                message = update.channel_post
                if not message:
                    continue

                # Skip non-media messages
                if not (message.photo or message.video or message.document):
                    continue

                # Process media
                file_id = None
                file_hash = None
                media_type = None

                if message.photo:
                    file_id = message.photo[-1].file_id
                    try:
                        photo_file = await bot.get_file(file_id)
                        file_hash = await calculate_image_hash(photo_file)
                        media_type = 'photo'
                        await asyncio.sleep(0.5)  # Rate limiting for photo processing
                    except Exception as e:
                        logger.error(f"Error processing photo: {e}")
                        continue
                elif message.video:
                    file_id = message.video.file_id
                    file_hash = file_id
                    media_type = 'video'
                elif message.document:
                    file_id = message.document.file_id
                    file_hash = file_id
                    media_type = 'document'

                if file_id and file_hash:
                    media_processed += 1
                    
                    # Check for duplicates
                    if file_hash in media_hashes:
                        if not await remover.is_whitelisted(file_id):
                            try:
                                await asyncio.sleep(1.0)  # Longer delay before deletion
                                await bot.delete_message(
                                    chat_id=chat_id,
                                    message_id=message.message_id
                                )
                                duplicates_found += 1
                                logger.info(f"Removed duplicate at message {message.message_id}")
                            except Exception as e:
                                logger.error(f"Error removing duplicate: {e}")
                    else:
                        media_hashes[file_hash] = {
                            'msg_id': message.message_id,
                            'file_id': file_id
                        }
                        await remover.store_hash(
                            file_id, file_hash, message.message_id,
                            chat_id, media_type
                        )

                # Update progress every 5 messages
                if i % 5 == 0:
                    try:
                        progress = (i + 1) / total_messages * 100
                        await status_msg.edit_text(
                            f"🔍 Scanning messages...\n"
                            f"Progress: {progress:.1f}%\n"
                            f"Media processed: {media_processed}\n"
                            f"Duplicates found: {duplicates_found}"
                        )
                        await asyncio.sleep(0.5)  # Rate limiting for status updates
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"Error processing message: {e}")
                continue

        # Final status
        final_text = (
            f"✅ Channel scan completed!\n"
            f"Media processed: {media_processed}\n"
            f"Duplicates removed: {duplicates_found}"
        )
        await status_msg.edit_text(final_text)
        
        # Delete status message after 1 minute
        await asyncio.sleep(60)
        try:
            await status_msg.delete()
        except:
            pass

    except Exception as e:
        logger.error(f"Error scanning channel: {e}")

async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bot being added to or removed from a chat"""
    try:
        chat_member = update.my_chat_member
        if not chat_member:
            return

        chat = chat_member.chat
        if chat.type != 'channel':
            return

        # Initialize remover if needed
        remover = context.bot_data.get('remover')
        if not remover:
            remover = DuplicateMediaRemover()
            await remover.init_db()
            context.bot_data['remover'] = remover

        # Check if bot was added to channel
        if chat_member.new_chat_member.status in ['administrator', 'member']:
            # Start scanning channel
            await scan_channel_history(context.bot, chat.id, remover)

    except Exception as e:
        logger.error(f"Error in handle_my_chat_member: {e}")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scan all channels where bot is admin"""
    if not update.message or update.message.chat.type != 'private':
        return

    try:
        # Send initial message
        status_msg = await update.message.reply_text(
            "🔍 Getting list of channels..."
        )

        # Initialize remover if needed
        remover = context.bot_data.get('remover')
        if not remover:
            remover = DuplicateMediaRemover()
            await remover.init_db()
            context.bot_data['remover'] = remover

        # Ask user for channel ID
        await status_msg.edit_text(
            "Please forward any message from the channel you want to scan.\n"
            "Or send the channel ID directly (e.g., -100xxxxxxxxxxxx)"
        )

        # Store the user's state
        context.user_data['waiting_for_channel'] = True
        context.user_data['status_msg'] = status_msg
        context.user_data['remover'] = remover

    except Exception as e:
        logger.error(f"Error in scan command: {e}")
        await update.message.reply_text(
            f"❌ Error during scan: {str(e)}"
        )

async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded message or channel ID to start scanning"""
    if not update.message or not context.user_data.get('waiting_for_channel'):
        return

    try:
        chat_id = None
        
        # Check if it's a forwarded message
        if update.message.forward_from_chat:
            chat_id = update.message.forward_from_chat.id
        # Check if it's a channel ID
        elif update.message.text and update.message.text.startswith('-100'):
            try:
                chat_id = int(update.message.text)
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid channel ID format. Please forward a message from the channel or send a valid channel ID."
                )
                return

        if not chat_id:
            await update.message.reply_text(
                "❌ Please forward a message from the channel or send the channel ID."
            )
            return

        # Try to get chat info to verify bot's access
        try:
            chat = await context.bot.get_chat(chat_id)
            if chat.type != 'channel':
                await update.message.reply_text("❌ This is not a channel!")
                return
            
            # Get bot member info
            bot_member = await chat.get_member(context.bot.id)
            if bot_member.status not in ['administrator']:
                await update.message.reply_text(
                    "❌ I need to be an administrator in the channel to scan it!"
                )
                return

        except Exception as e:
            await update.message.reply_text(
                "❌ I don't have access to this channel or it doesn't exist.\n"
                "Make sure I'm added as an admin!"
            )
            return

        # Clear the waiting state
        context.user_data.pop('waiting_for_channel', None)
        
        # Get the stored remover instance
        remover = context.user_data.get('remover')
        if not remover:
            remover = DuplicateMediaRemover()
            await remover.init_db()

        # Start scanning
        await update.message.reply_text(
            f"✅ Starting scan of channel: {chat.title}\n"
            "This might take a while..."
        )
        
        await scan_channel_history(context.bot, chat_id, remover)

    except Exception as e:
        logger.error(f"Error handling channel message: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

class SingleInstance:
    def __init__(self):
        self.lockfile = os.path.join(tempfile.gettempdir(), 'telegram_dubs_remover.lock')
        
    def __enter__(self):
        try:
            if os.path.exists(self.lockfile):
                # Check if the process is still running
                with open(self.lockfile, 'r') as f:
                    pid = int(f.read().strip())
                try:
                    # Check if process with this PID exists
                    os.kill(pid, 0)
                    print("Bot is already running! Exiting.")
                    sys.exit(1)
                except OSError:
                    # Process not found, we can proceed
                    pass
            
            # Create lock file
            with open(self.lockfile, 'w') as f:
                f.write(str(os.getpid()))
            return self
        except Exception as e:
            print(f"Error creating lock file: {e}")
            sys.exit(1)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            os.remove(self.lockfile)
        except:
            pass

def signal_handler(signum, frame):
    """Handle shutdown gracefully"""
    print("\nShutting down bot...")
    sys.exit(0)

def main():
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Use single instance lock
    with SingleInstance():
        try:
            # Configure connection pool with much higher limits
            application = (
                Application.builder()
                .token(BOT_TOKEN)
                .connection_pool_size(16)     # Double the previous size
                .connect_timeout(60.0)        # Double connection timeout
                .read_timeout(60.0)           # Double read timeout
                .write_timeout(60.0)          # Double write timeout
                .pool_timeout(20.0)           # Much longer pool timeout
                .get_updates_connection_pool_size(16)  # Separate pool for updates
                .build()
            )

            # Add handlers for private messages
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("help", help_command))
            application.add_handler(CommandHandler("whitelist", whitelist_media))
            application.add_handler(CommandHandler("stats", channel_stats))
            application.add_handler(CommandHandler("scan", scan_command))

            # Add handler for channel ID/forward
            application.add_handler(MessageHandler(
                filters.TEXT | filters.FORWARDED,
                handle_channel_message
            ))

            # Add handler for when bot is added to channel
            application.add_handler(ChatMemberHandler(
                handle_my_chat_member,
                ChatMemberHandler.MY_CHAT_MEMBER
            ))

            # Add media handler
            application.add_handler(MessageHandler(
                filters.PHOTO | filters.VIDEO | filters.Document.ALL,
                handle_media
            ))

            # Start the bot
            print("Bot started successfully!")
            application.run_polling(
                allowed_updates=[
                    Update.MESSAGE,
                    Update.CHANNEL_POST,
                    Update.MY_CHAT_MEMBER
                ],
                pool_timeout=None,  # Disable pool timeout for long-running operations
                read_timeout=60,    # Longer read timeout
                write_timeout=60    # Longer write timeout
            )

        except Exception as e:
            print(f"Error starting bot: {e}")
            sys.exit(1)

if __name__ == '__main__':
    main()
