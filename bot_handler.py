import os
import logging
import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from datetime import datetime

import config
from comfy_client import generate_image

ACTIVE_HOUR_START = 20  # 8PM
ACTIVE_HOUR_END = 7     # 7AM
ACTIVE_MSG= f"Sorry, the bot is only active between {ACTIVE_HOUR_START} and {ACTIVE_HOUR_END} (GMT+2 Jerusalem). Please try again later."

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

def is_active_hours():
    return True
    now = datetime.now()
    hour = now.hour
    # Active if hour >= ACTIVE_HOUR_START or hour < ACTIVE_HOUR_END
    return hour >= ACTIVE_HOUR_START or hour < ACTIVE_HOUR_END



# --- Command Handlers ---
@authorized
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /start command.
    """
    start_message = telEscChars(
        "Welcome to the Flux Image Bot\n\n"
        "To get started, please send me a prompt or an image with a text caption"
        "The caption will be used as the prompt to generate a new image based on your input\n\n"
        "Average time is ~180-200 seconds on kontext, 380-450 on krea\n\n"
        "Note that for Text-to-Image generation the default model is Kontext-dev, if u want to use krea model start the message with 'kreawf' (this would take longer) or use lighter krea workflow with 'kreasmp'\n\n"
        "For more detailed instructions, type /help"
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
    if not is_active_hours():
        await update.message.reply_text(
            ACTIVE_MSG
        )
        return
    
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
    
    logger.info(f"Received image from {update.effective_user.first_name}. Prompt: '{prompt_text}'\n\n")
    await update.message.reply_text(
        "Image received. Processing your request, this might take a moment..."
    )

    try:
        # Call the image generation function
        generated_image_path = generate_image(
            image_path=input_image_path,
            prompt_text=prompt_text,
            workflow_path=(
                config.I2I_WORKFLOW_FILE_PATH
                if input_image_path
                else config.T2I_WORKFLOW_FILE_PATH
            ),
            server_address=config.COMFYUI_SERVER_ADDRESS
        )

        if generated_image_path and os.path.exists(generated_image_path):
            logger.info(f"Image generated successfully: {generated_image_path}\n\n")
            await update.message.reply_photo(
                photo=open(generated_image_path, 'rb'),
                caption=f"Here is your generated image!\n\nPrompt Text: {prompt_text}"
            )
        else:
            raise FileNotFoundError("The generated image file was not found.")

    except Exception as e:
        logger.error(f"Failed to generate image for user {update.effective_user.id}. Error: {e}\n\n")
        await update.message.reply_text(
            "Sorry, something went wrong while generating the image. Please try again later."
        )
    finally:
        # Clean up the downloaded image
        if os.path.exists(input_image_path):
            os.remove(input_image_path) 


@authorized
async def handle_text_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles incoming text prompts (no image).
    """
    if not is_active_hours():
        await update.message.reply_text(
           ACTIVE_MSG
        )
        return
        
    prompt_text = update.message.text
    if not prompt_text or prompt_text.startswith('/'):
        # Ignore commands or empty messages
        return        

    logger.info(f"Received text prompt from {update.effective_user.first_name}: '{prompt_text}'\n\n")
    await update.message.reply_text(
        "Prompt received. Generating image, this might take a moment..."
    )

    try:
        # Call the image generation function with no image
        
        if 'kreawf' in prompt_text.lower():
            wf_path = config.KREA_T2I_WORKFLOW_FILE_PATH
        elif 'kreasmp' in prompt_text.lower():
            wf_path = config.KREA_T2I_SIMPLIFIED_FILE_PATH
        else:
            wf_path = config.T2I_WORKFLOW_FILE_PATH

        prompt_text = re.sub(r'\b(kreawf|kreasmp)\b', '', prompt_text, flags=re.IGNORECASE).strip()

        logger.info(f'wf path: {wf_path}\n\n')

        generated_image_path = generate_image(
            image_path=None,
            prompt_text=prompt_text,
            workflow_path=wf_path,
            server_address=config.COMFYUI_SERVER_ADDRESS
        )        

        if generated_image_path and os.path.exists(generated_image_path):
            logger.info(f"Image generated successfully: {generated_image_path}\n\n")
            await update.message.reply_photo(
                photo=open(generated_image_path, 'rb'),
                caption=f"Here is your generated image!\n\nPrompt Text: {prompt_text}"
            )
        else:
            raise FileNotFoundError("The generated image file was not found.")

    except Exception as e:
        logger.error(f"Failed to generate image for user {update.effective_user.id}. Error: {e}\n\n")
        await update.message.reply_text(
            "Sorry, something went wrong while generating the image. Please try again later."
        )


def telEscChars(text):
  t=""
  s=""
  try:
    escChars = ( "}",
                "!",
                "|",
                "{",
                "`",
                "#",
                "=",
                "]",
                "~",
                "<",
                "_",
                "*",
                "[",
                ">",
                "+",
                "-",
                ".",
                "(",                
                ")")
    t = text
    for c in escChars:
      if not c in text:
        continue 
      t = t.replace(c, f'\{c}')
    return t if not s else s
  except Exception as e:
    print(e)
    print(text)
    print(s)
    return ""