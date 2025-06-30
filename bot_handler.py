import os
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import config
from comfy_client import generate_image

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Authorization Decorator ---
def authorized(func):
    """
    Decorator to check if the user is authorized to use the bot.
    """
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in config.AUTHORIZED_USER_IDS:
            logger.warning(f"Unauthorized access attempt by user_id: {user_id}")
            await update.message.reply_text(
                "Sorry, you are not authorized to use this bot."
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# --- Command Handlers ---
@authorized
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /start command.
    """
    start_message = (
        "Welcome to the Flux Image Bot!\\n\\n"
        "To get started, please send me an image with a text caption\\. "
        "The caption will be used as the prompt to generate a new image based on your input\\."
        "\\n\\nFor more detailed instructions, type /help\\."
    )
    await update.message.reply_text(start_message, parse_mode=ParseMode.MARKDOWN_V2)

@authorized
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /help command and displays a detailed help message.
    """
    help_text = (
        "*How to Use This Bot:*\n\n"
        "This bot creates a new image based on an image and a text prompt you provide\\.\n\n"
        "1\\. *Send an Image*: Tap the paperclip icon in the message bar to attach a photo\\.\n"
        "2\\. *Add a Caption*: Before sending the image, type a description in the 'Add a caption\\.\\.' field\\. This text will be used as the prompt for the new image\\.\n"
        "3\\. *Send It*: Press send and wait for the magic to happen\\!\n\n"
        "*Example:*\n"
        "Send a picture of your dog with the caption: 'A painting in the style of Van Gogh'\\."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)

@authorized
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles incoming images with captions.
    """
    if not update.message.caption:
        await update.message.reply_text(
            "Please send an image with a caption. The caption will be used as the prompt."
        )
        return

    prompt_text = update.message.caption
    photo_file = await update.message.photo[-1].get_file()
    
    # Create a temporary directory for downloads if it doesn't exist
    temp_dir = "temp_downloads"
    os.makedirs(temp_dir, exist_ok=True)
    
    input_image_path = os.path.join(temp_dir, f"{photo_file.file_id}.jpg")
    await photo_file.download_to_drive(input_image_path)
    
    logger.info(f"Received image from {update.effective_user.first_name}. Prompt: '{prompt_text}'")
    await update.message.reply_text(
        "Image received. Processing your request, this might take a moment..."
    )

    try:
        # Call the image generation function
        generated_image_path = generate_image(
            image_path=input_image_path,
            prompt_text=prompt_text,
            workflow_path=config.WORKFLOW_FILE_PATH,
            server_address=config.COMFYUI_SERVER_ADDRESS
        )

        if generated_image_path and os.path.exists(generated_image_path):
            logger.info(f"Image generated successfully: {generated_image_path}")
            await update.message.reply_photo(
                photo=open(generated_image_path, 'rb'),
                caption="Here is your generated image!"
            )
        else:
            raise FileNotFoundError("The generated image file was not found.")

    except Exception as e:
        logger.error(f"Failed to generate image for user {update.effective_user.id}. Error: {e}")
        await update.message.reply_text(
            "Sorry, something went wrong while generating the image. Please try again later."
        )
    finally:
        # Clean up the downloaded image
        if os.path.exists(input_image_path):
            os.remove(input_image_path) 