# Telegram Duplicate Media Remover Bot

A Telegram bot that automatically detects and removes duplicate media from channels.

## Features

- 🔍 Automatic duplicate media detection
- 🖼️ Supports multiple media types (photos, videos, documents)
- ⚡ Real-time scanning of new media
- 📊 Channel statistics
- ⭐ Whitelist functionality to protect specific media
- 🤖 Easy to use commands

## Setup

1. Create a `.env` file with your bot token:
```
BOT_TOKEN=your_bot_token_here
```

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

3. Run the bot:
```bash
python bot.py
```

## Commands

- `/start` - Initialize bot and show welcome message
- `/help` - Display available commands
- `/stats` - Show channel media statistics
- `/whitelist` - Prevent specific media from being deleted
- `/scan` - Scan channel for duplicates

## Usage

1. Add the bot to your channel as an administrator
2. Start a private chat with the bot
3. Use `/scan` command
4. Send your channel ID (starts with -100)
5. Wait for the scan to complete

### Finding Your Channel ID
1. Forward any message from your channel to @username_to_id_bot
2. Copy the ID that starts with -100
3. Use this ID with the `/scan` command

## Current Status

### Working Features
- Channel scanning via channel ID
- Duplicate detection using perceptual hashing
- Database storage for media hashes
- Whitelist functionality
- Basic statistics
- Real-time duplicate detection for new media

### Known Limitations
- Scanning large channels can take significant time
- No progress saving for interrupted scans
- Forwarded message detection needs improvement
- No way to cancel ongoing scans

## Dependencies

- python-telegram-bot (v20.6)
- Pillow (v10.0.0)
- imagehash (v4.3.1)
- python-dotenv (v1.0.0)
- aiosqlite (v0.19.0)

## Future Improvements

### Performance
- [ ] Optimize scanning speed for large channels
- [ ] Implement batch processing
- [ ] Add ability to resume interrupted scans

### Features
- [ ] Fix forwarded message detection
- [ ] Add progress saving for interrupted scans
- [ ] Add ability to cancel ongoing scans
- [ ] Add configurable similarity threshold
- [ ] Add more detailed scanning statistics

### User Experience
- [ ] Add better progress indicators
- [ ] Add estimated time remaining
- [ ] Add scan scheduling options

## Contributing

Feel free to open issues or submit pull requests for any improvements.

## License

This project is open source and available under the MIT License.
