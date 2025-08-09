import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters

import config
from bot_handler import start_command, handle_image, help_command, handle_text_prompt

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def main():
    """
    Runs the Telegram bot.
    """
    logger.info("Starting bot...")
    
    # Create the Application and pass it your bot's token.
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("Telegram bot token not found. Please set it in config.py")
        return
        
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # --- Register Handlers ---
    # Register the /start command handler
    application.add_handler(CommandHandler("start", start_command))
    
    # Register the /help command handler
    application.add_handler(CommandHandler("help", help_command))
    
    # Register the handler for images (photos)
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))

    # Register the handler for text prompts (no photo)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_prompt))

    # --- Start the Bot ---
    logger.info("Bot started and polling for messages...")
    application.run_polling()

if __name__ == "__main__":
    main() 