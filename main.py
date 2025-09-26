import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters, PicklePersistence
import asyncio
from concurrent.futures import ThreadPoolExecutor
import config
from bot_handler import start_command, handle_image, help_command, handle_text_prompt, magic_prompt_command, set_bot_commands, handle_audio

asyncio.get_event_loop().set_default_executor(ThreadPoolExecutor(max_workers=200))

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

async def post_init(application):
    """Post initialization function to set bot commands."""
    await set_bot_commands(application)

def main():
    """
    Runs the Telegram bot.
    """
    logger.info("Starting bot...")
    
    # Create the Application and pass it your bot's token.
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("Telegram bot token not found. Please set it in config.py")
        return
    
    # Add persistence to save user data across restarts
    persistence = PicklePersistence(filepath="user_data.pkl")
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).persistence(persistence).build()

    # --- Register Handlers ---
    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("magic", magic_prompt_command))
    
    # Register message handlers
    application.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | (filters.Document.AUDIO), handle_audio))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_prompt))


    # Set bot commands for the menu after startup
    application.post_init = post_init

    # --- Start the Bot ---
    logger.info("Bot started and polling for messages...")
    application.run_polling()

if __name__ == "__main__":
    main()