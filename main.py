import logging
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters

import config
from bot_handler import start_command, handle_image, help_command, toggle_auto_prompt_command

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

async def post_init(application: Application):
    """
    Post-initialization hook to set bot commands.
    This function is called by the Application after it's built, but before it starts polling.
    """
    commands = [
        BotCommand("start", "Displays a welcome message."),
        BotCommand("help", "Shows detailed instructions on how to use the bot."),
        BotCommand("toggle_auto_prompt", "Turn automatic prompt improvement ON/OFF."),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Custom commands have been set.")

def main():
    """
    Runs the Telegram bot.
    """
    logger.info("Starting bot...")
    
    # Create the Application and pass it your bot's token.
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("Telegram bot token not found. Please set it in config.py")
        return
        
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # --- Register Handlers ---
    # Register the /start command handler
    application.add_handler(CommandHandler("start", start_command))
    
    # Register the /help command handler
    application.add_handler(CommandHandler("help", help_command))
    
    # Register the /toggle_auto_prompt command handler
    application.add_handler(CommandHandler("toggle_auto_prompt", toggle_auto_prompt_command))
    
    # Register the handler for images (photos)
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))

    # --- Start the Bot ---
    logger.info("Bot started and polling for messages...")
    application.run_polling()

if __name__ == "__main__":
    main() 