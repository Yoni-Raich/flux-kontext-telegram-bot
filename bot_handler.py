import os
import logging
import re
import asyncio
import time
from telegram import Update, BotCommand
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from datetime import datetime

import config
from comfy_client import generate_image, is_any_job_running, get_pending_job_count

# Try to import Gemini client, make it optional
try:
    from gemini_client import get_gemini_client
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logging.warning("Gemini client not available. Magic Prompt feature will be disabled.")

ACTIVE_HOUR_START = 20  # 8PM
ACTIVE_HOUR_END = 7     # 7AM
ACTIVE_MSG= f"Sorry, Kids are playing Fortnite :)\nthe bot is only active between {ACTIVE_HOUR_START} and {ACTIVE_HOUR_END} (GMT+2 Jerusalem). Please try again later."

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
        "Welcome to the Image Generation Bot\n\n"
        "To get started, please send me a prompt or an image with a text caption"
        "The caption will be used as the prompt to generate a new image based on your input\n\n"
        "Average time is ~180-200 seconds on kontext, 380-450 on krea\n\n"
        "Note that for Text-to-Image generation the default model is Kontext-dev, if u want to use krea model start the message with 'kreawf' (this would take longer) or use lighter krea workflow with 'kreasmp'\n\n"
        "Use /magic to toggle automatic prompt enhancement\n\n"
        "For more detailed instructions, type /help"
    )
    await update.message.reply_text(start_message, parse_mode=ParseMode.MARKDOWN_V2)

@authorized
async def magic_prompt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Toggles the Magic Prompt feature for a user.
    """
    if not GEMINI_AVAILABLE:
        await update.message.reply_text(
            "❌ Magic Prompt is not available. Gemini API is not configured.\n\n"
            "To enable this feature:\n"
            "1. Get a Gemini API key from Google AI Studio\n"
            "2. Add GEMINI_API_KEY to your config.py\n"
            "3. Install google-generativeai package"
        )
        return

    # Default to True if not set
    current_status = context.user_data.get('magic_prompt', True)  # Default to True instead of False
    new_status = not current_status
    context.user_data['magic_prompt'] = new_status
    
    status_text = "ON" if new_status else "OFF"
    emoji = "✨" if new_status else "🪄"
    
    await update.message.reply_text(
        f"{emoji} Magic Prompt has been turned *{status_text}*\\.\n\n"
        f"When enabled, your prompts will be automatically enhanced using AI before image generation\\.\n\n"
        f"For images with captions, both the image and text will be analyzed for better enhancement\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

@authorized
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /help command and displays a detailed help message.
    """
    magic_status = "ON" if context.user_data.get('magic_prompt', True) else "OFF"  # Changed False to True
    magic_available = "✨ Available" if GEMINI_AVAILABLE else "❌ Not Available"
    
    help_text = (
        "*How to Use This Bot:*\n\n"
        "*__Commands:__*\n"
        "/start \\- Start the bot and see welcome message\n"
        "/help \\- Show this help message\n"
        f"/magic \\- Toggle Magic Prompt \\(Currently: {magic_status}, {magic_available}\\)\n\n"
        "*__Magic Prompt Feature:__*\n"
        "Use /magic to toggle automatic prompt enhancement\\. When enabled:\n"
        "• Text prompts are enhanced with AI for better results\n"
        "• Image\\+caption prompts are analyzed multimodally \\(both image and text\\) for optimal enhancement\n\n"
        "*__Image To Image Generation:__*\n"
        "The default model is Flux1\\-Kontext\\-dev\n\n"
        "1\\. *Send an Image*: Tap the paperclip icon in the message bar to attach a photo\\.\n"
        "2\\. *Add a Caption*: Before sending the image, type a description in the 'Add a caption\\.\\.' field\\. This text will be used as the prompt for the new image\\.\n"
        "3\\. *Send It*: Press send and wait for the magic to happen\\!\n\n"
        "*Example:*\n"
        "Send a picture of your dog with the caption: 'A painting in the style of Van Gogh'\n\n"
        "*Available Flags:*\n"
        "*\\-\\-steps:*\n Default is 20\\. Controls iteration steps\\.\n\n"
        "*\\-\\-cfg:*\n Default is 1\\.0\\. Controls Classifier\\-Free Guidance scale\\.\n\n"
        "*\\-\\-upscale:*\n Will upscale the image x2 Using QWEN model\nFor WAN upscaler add the word wan21 in ur prompt\\(wan upscaler is BETA, currently slightly changes the picture, better to also set a low denoise for the seed 0\\.02\\)\\.\n\n"
        "*\\-\\-seednoise:*\n Sets a specific seed noise for reproducibility \\(0\\.0\\-1\\.0\\)\\.\n\n"
        "*\\-\\-upnoise:*\n Sets a specific up noise for upscale reproducibility \\(0\\.0\\-1\\.0\\)\\. \\(Only for WAN Upscaler\\)\n\n"
        "*Upscale Example:*\n"
        "Send a picture and in the caption either:"
        "```\n"
        "\\-\\-upscale"
        "```\n\n"
        "```\n"
        "\\-\\-upscale A photo realistic portrait of a blonde hair nordic woman"
        "```\n\n"
        "*__Text To Image Generation:__*\n"
        "Simply send me a prompt\\. The default model is WAN2\\.1\n"
        "*Example:*\n"
        "```\n"
        "A photo realistic portrait of a blonde hair nordic woman"
        "```\n\n"
        "*Available Flags:*\n"
        "*\\-\\-steps:*\n Default is 20 for Krea and Flux models, 10 for WAN2\\.1\\. 4 and 8 for QWEN\\(no need to increase on these flows\\)\\. Controls iteration steps\\.\n\n"
        "*\\-\\-cfg:*\n Default is 1\\.0\\. Controls Classifier\\-Free Guidance scale\\.\n\n"
        "*\\-\\-res:*\n Default resolution is 1024x1024, maximum resolution is 1920x1080\n\n"
        "*\\-\\-neg:*\n Controls the negative prompt for image generation\\. \\(Only for Wan model\\)\n\n"
        "*\\-\\-seed:*\n Sets a specific seed for reproducibility\\.\n\n"
        "*\\-\\-seednoise:*\n Sets a specific seed noise for reproducibility \\(0\\.0\\-1\\.0\\)\\.\n\n"        
        "*Using Other Models:*\n"
        "Add 'qwen4' or 'qwen8' before your prompt to use Qwen model\\:\n"
        "```\n"
        "qwen4 A photo realistic portrait of a blonde hair nordic woman"
        "```\n\n"
        "Add 'kreawf' before your prompt to use Krea model\\:\n"
        "```\n"
        "kreawf A photo realistic portrait of a blonde hair nordic woman"
        "```\n\n"
        "*Examples with Flags:*\n"
        "With steps:\n"
        "```\n"
        "\\-\\-steps 30 A photo realistic portrait of a blonde hair nordic woman"
        "```\n\n"
        "With cfg:\n"
        "```\n"
        "\\-\\-cfg 2\\.5 A photo realistic portrait of a blonde hair nordic woman"
        "```\n\n"
        "With both flags:\n"
        "```\n"
        "\\-\\-cfg 2\\.5 \\-\\-steps 30 A photo realistic portrait of a blonde hair nordic woman\n"
        "```\n\n"
        "With Krea model and flags:\n"
        "```\n"
        "kreawf \\-\\-cfg 2\\.5 \\-\\-steps 30 A photo realistic portrait of a blonde hair nordic woman\n"
        "```\n\n"
        "With res flag:\n"
        "```\n"
        "\\-\\-cfg 2\\.5 \\-\\-steps 30 \\-\\-res 1920x1080 A photo realistic portrait of a blonde hair nordic woman\n"
        "```\n\n"
        "With neg flag:\n"
        "```\n"
        "A photo realistic portrait of a blonde hair nordic woman \\-\\-neg blur, cartoon, historical"
        "```\n\n"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)


def determine_model_name(prompt_text, flags, is_image_to_image=False):
    """
    Determine which model will be used based on the workflow selection logic.
    
    Args:
        prompt_text: The prompt text (after Magic Prompt enhancement)
        flags: Parsed flags from the prompt
        is_image_to_image: Whether this is image-to-image generation
    
    Returns:
        String name of the model that will be used
    """
    if is_image_to_image:
        # Image-to-Image logic
        if 'upscale' in flags:
            if prompt_text and 'wan21' in prompt_text.lower():
                return "WAN 2.1 Upscaler"
            return "QWEN"
        elif 'simpleup' in flags:
            return "AI Image Generator"
        elif 'kontext' in prompt_text.lower():
            return "Flux1-Kontext-dev"
        elif 'qwen4' in prompt_text.lower():
            return "QWEN"
        else:
            return "Flux1-Kontext-dev"  # Default for I2I
    else:
        # Text-to-Image logic
        if 'kreawf' in prompt_text.lower():
            return "Flux1-Krea-dev"
        elif 'kreasmp' in prompt_text.lower():
            return "Flux1-Krea-dev"
        elif 'kontext' in prompt_text.lower():
            return "Flux1-Kontext-dev"
        else:
            if 'grain' in flags:
                return "WAN 2.1"
            else:
                return "WAN 2.1"


@authorized
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles incoming images with captions.
    """
    if not is_active_hours():
        await update.message.reply_text(ACTIVE_MSG)
        return

    if not update.message.caption:
        await update.message.reply_text(
            "Please send an image with a caption. The caption will be used as the prompt."
        )
        return        

    prompt_text = update.message.caption
    photo_file = await update.message.photo[-1].get_file()

    prompt_text, neg_prompt_text, flags = parse_prompt_flags(prompt_text)

    # Create a temporary directory for downloads if it doesn't exist
    temp_dir = "temp_downloads"
    os.makedirs(temp_dir, exist_ok=True)

    input_image_path = os.path.join(temp_dir, f"{photo_file.file_id}.jpg")
    await photo_file.download_to_drive(input_image_path)

    # Determine which model will be used BEFORE Magic Prompt enhancement
    model_name = determine_model_name(prompt_text, flags, is_image_to_image=True)


    # Limit the steps to MAX_STEPS
    if 'steps' in flags:
        if flags['steps'] > config.MAX_STEPS:
            await update.message.reply_text(
                f"The maximum number of steps allowed is {config.MAX_STEPS}. Your request will be processed with {config.MAX_STEPS} steps."
            )
            flags['steps'] = config.MAX_STEPS

    if 'upscale' in flags:
        if prompt_text and 'wan21' in prompt_text.lower():
            wf_path = config.WAN_2_1_UPSCALER_FILE_PATH
        else:
            wf_path = config.QWEN_UPSCALER_FILE_PATH
    elif 'simpleup' in flags:
        wf_path = config.SIMPLE_UPSCALER_PATH
    elif 'kontext' in prompt_text.lower():
        wf_path = config.I2I_WORKFLOW_FILE_PATH
    elif 'qwen4' in prompt_text.lower():
        wf_path = config.QWEN_4_STEP_I2I_FILE_PATH
    elif 'qwen8' in prompt_text.lower():
        wf_path = config.QWEN_8_STEP_I2I_FILE_PATH
    else:
        wf_path = config.I2I_WORKFLOW_FILE_PATH

    logger.info(f'\n\nwf path: {wf_path}\n\n')
    workflow_name = wf_path.split('/')[-1].split('.')[0]

    logger.info(f"Received image from {update.effective_user.first_name}. Prompt: '{prompt_text}'\n\n")
    await update.message.reply_text(
        "🎨 Image received. Processing your request, this might take a moment..."
    )

    if prompt_text:
        prompt_text = re.sub(r'\b(wan21|qwen4|qwen8)\b', '', prompt_text, flags=re.IGNORECASE).strip()
    async def process_and_respond(): 
        nonlocal prompt_text, neg_prompt_text 
        # Check if Magic Prompt is enabled for this user - using multimodal enhancement
        if GEMINI_AVAILABLE and context.user_data.get('magic_prompt', True):
            # Send initial message about enhancement
            enhancement_msg = await update.message.reply_text("✨ Enhancing your prompt with Magic Prompt (analyzing both image and text)...")
            
            # Start enhancement in background - don't await it
            asyncio.create_task(handle_magic_prompt_enhancement(
                update, context, prompt_text, neg_prompt_text, 
                enhancement_msg, model_name, flags, wf_path, workflow_name, input_image_path
            ))
            return  # Exit here - enhancement will handle the rest
        
        await check_pending_jobs(update)    
        try:
            generated_image_path, duration_seconds, seed = await asyncio.to_thread(
            generate_image,
            image_path=input_image_path,
            prompt_text=prompt_text,
            workflow_path=wf_path,
            server_address=config.COMFYUI_SERVER_ADDRESS,
            flags=flags,
            resize_resolution=flags.get('resize')  if flags.get('resize') else None,
            allow_resize=update.effective_user.id == config.MY_USER_ID,
            fast_film_grain=flags.get('fast_film_grain', False)  # Use the flag if provided
            )

            if generated_image_path and os.path.exists(generated_image_path):
                logger.info(f"Image generated successfully in {duration_seconds:.1f} seconds: {generated_image_path}\n\n")
                await send_image_with_logging(
                    update,
                    generated_image_path,
                    prompt_text,
                    "Image-to-Image",
                    flags,
                    seed,
                    duration_seconds,
                    workflow_name=workflow_name,
                    nogroup=flags.get('nogroup', False)
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

    asyncio.create_task(process_and_respond())





@authorized
async def handle_text_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles incoming text prompts (no image).
    """
    if not is_active_hours():
        await update.message.reply_text(ACTIVE_MSG)
        return        

    prompt_text = update.message.text
    if not prompt_text or prompt_text.startswith('/'):
        return

    prompt_text, negative_prompt_text, flags = parse_prompt_flags(prompt_text)

    # Determine which model will be used BEFORE Magic Prompt enhancement
    model_name = determine_model_name(prompt_text, flags, is_image_to_image=False)

    # Limit the steps to MAX_STEPS
    if 'steps' in flags:
        if flags['steps'] > config.MAX_STEPS:
            await update.message.reply_text(
                f"The maximum number of steps allowed is {config.MAX_STEPS}. Your request will be processed with {config.MAX_STEPS} steps."
            )
            flags['steps'] = config.MAX_STEPS

    logger.info(f"Received text prompt from {update.effective_user.first_name}: '{prompt_text}'\n\nNegative: {negative_prompt_text}")
    await update.message.reply_text(
        "🎨 Prompt received. Generating image, this might take a moment..."
    )

    if 'kreawf' in prompt_text.lower():
        wf_path = config.KREA_T2I_WORKFLOW_FILE_PATH
    elif 'kreasmp' in prompt_text.lower():
        wf_path = config.KREA_T2I_SIMPLIFIED_FILE_PATH
    elif 'kontext' in prompt_text.lower():
        wf_path = config.T2I_WORKFLOW_FILE_PATH
    elif 'qwen4' in prompt_text.lower():
        wf_path = config.QWEN_4_STEP_T2I_FILE_PATH
    elif 'qwen8' in prompt_text.lower():
        wf_path = config.QWEN_8_STEP_T2I_FILE_PATH
    else:
        if 'grain' in flags:
            wf_path = config.WAN_T2I_WORKFLOW_FILE_PATH
        else:             
            wf_path = config.WAN_T2I_WORKFLOW__NOGRAIN_FILE_PATH

    prompt_text = re.sub(r'\b(kreawf|kreasmp|wan21|qwen4|qwen8)\b', '', prompt_text, flags=re.IGNORECASE).strip()
    logger.info(f'wf path: {wf_path}\n\n')
    workflow_name = wf_path.split('/')[-1].split('.')[0]

    async def process_and_respond():
        nonlocal prompt_text, negative_prompt_text
        # Check if Magic Prompt is enabled for this user - text-only enhancement
        if GEMINI_AVAILABLE and context.user_data.get('magic_prompt', True):
            # Send initial message about enhancement
            enhancement_msg = await update.message.reply_text("✨ Enhancing your prompt with Magic Prompt...")
            
            # Start enhancement in background - don't await it
            asyncio.create_task(handle_magic_prompt_enhancement(
                update, context, prompt_text, negative_prompt_text, 
                enhancement_msg, model_name, flags, wf_path, workflow_name, None  # None for text-only
            ))
            return  # Exit here - enhancement will handle the rest
        
        await check_pending_jobs(update)
        # Record start time
        start_time = datetime.now()
        await handle_resize(value=flags.get('resize')  if flags.get('resize') else None, update=update)
        
        try:            
            generated_image_path, duration_seconds, seed = await asyncio.to_thread(
            generate_image,
            image_path=None,
            prompt_text=prompt_text,
            neg_prompt_text=negative_prompt_text,
            workflow_path=wf_path,
            server_address=config.COMFYUI_SERVER_ADDRESS,
            flags=flags,
            resize_resolution=flags.get('resize')  if flags.get('resize') else None,
            allow_resize=update.effective_user.id == config.MY_USER_ID
            )
            time.sleep(1)
            # Use ComfyUI's duration if available, otherwise calculate fallback
            if duration_seconds is None:
                end_time = datetime.now()
                duration = end_time - start_time
                duration_seconds = duration.total_seconds()
    
            if generated_image_path and os.path.exists(generated_image_path):
                logger.info(f"Image generated successfully in {duration_seconds:.1f} seconds: {generated_image_path}\n\n")                  
                await send_image_with_logging(
                    update,
                    generated_image_path,
                    prompt_text,
                    "Text-to-Image",
                    flags,
                    seed,
                    duration_seconds,
                    workflow_name,
                    nogroup=flags.get('nogroup', False)
                )
            else:
                raise FileNotFoundError("The generated image file was not found.")

        except Exception as e:
            logger.error(f"Failed to generate image for user {update.effective_user.id}. Error: {e}\n\n")
            await update.message.reply_text(
                "Sorry, something went wrong while generating the image. Please try again later."
            )

    asyncio.create_task(process_and_respond())

# Function to set bot commands (menu buttons)
async def set_bot_commands(application):
    """Set the bot commands that appear in the menu."""
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show help message"),
        BotCommand("magic", "Toggle Magic Prompt enhancement"),
    ]
    await application.bot.set_my_commands(commands)

async def handle_resize(value, update):
    """
    Handle the resize value from the prompt.
    Returns a tuple of (width, height) or None if invalid.
    """
    if value:
        try:
            width, height = map(int, value.split('x'))
            if ((width > 1920 or height > 1080) and update.effective_user.id != 374504771) or (width<=0 or height<=0):
                await update.message.reply_text(
                    "Maximum resolution is 1920x1080, Minimum resolution cannot be 0, setting values to default 1024x1024"
                )
        except ValueError:
            print(f"Invalid resize value: {value}")

def parse_prompt_flags(prompt_text):
    import re
    
    flags = {}

    # Extract --seed flag and value
    seed_match = re.search(r'--seed\s+(\d+)', prompt_text)
    if seed_match:
        flags['seed'] = int(seed_match.group(1))
        prompt_text = prompt_text.replace(seed_match.group(0), '')

    # Extract --steps flag and value
    steps_match = re.search(r'--steps\s+(\d+)', prompt_text)
    if steps_match:
        flags['steps'] = int(steps_match.group(1))
        prompt_text = prompt_text.replace(steps_match.group(0), '')
    
    # Extract --cfg flag and value
    cfg_match = re.search(r'--cfg\s+([\d.]+)', prompt_text)
    if cfg_match:
        flags['cfg'] = float(cfg_match.group(1))
        prompt_text = prompt_text.replace(cfg_match.group(0), '')
    
    # Extract --neg flag and value
    neg_match = re.search(r'--neg\s+(.+)', prompt_text)
    if neg_match :
        neg_prompt_text = neg_match.group(1).replace(neg_match.group(0), '')
        neg_prompt_text = ' '.join(neg_prompt_text.split())
        prompt_text = prompt_text.replace(neg_match.group(0), '')
        prompt_text = prompt_text.replace(neg_prompt_text, '')
    
    # Extract denoise for seed and upscaler
    seednoise_match = re.search(r'--seednoise\s+([\d.]+)', prompt_text)
    upscale_noise_match = re.search(r'--upnoise\s+([\d.]+)', prompt_text)
    if seednoise_match:
        flags['seednoise'] = float(seednoise_match.group(1))
        prompt_text = prompt_text.replace(seednoise_match.group(0), '')

    if upscale_noise_match:
        flags['upscale_noise'] = float(upscale_noise_match.group(1))
        prompt_text = prompt_text.replace(upscale_noise_match.group(0), '')

    # Extract --nogroup flag
    if '--nogroup' in prompt_text:
        flags['nogroup'] = True
        prompt_text = prompt_text.replace('--nogroup', '')

    if '--grain' in prompt_text:
        flags['grain'] = True
        prompt_text = prompt_text.replace('--grain', '')

    if '--simpleup' in prompt_text:
        flags['simpleup'] = True
        prompt_text = prompt_text.replace('--simpleup', '')

    upscale_match = re.search(r'--upscale\s+(.+)', prompt_text)     
    if upscale_match:
        flags['upscale'] = True
        prompt_text = prompt_text.replace('--upscale', '')
        
    if re.search(r'--chngsmp\b', prompt_text):
        flags['chngsmp'] = True
        prompt_text = re.sub(r'--chngsmp\b', '', prompt_text)
    elif 'upscale' in prompt_text.lower():
        flags['upscale'] = True
        prompt_text = prompt_text.replace('--upscale', '')

    resize_match = re.search(r'--res\s+(\d+x\d+)', prompt_text)
    if resize_match:
        flags['resize'] = resize_match.group(1)
        prompt_text = prompt_text.replace(resize_match.group(0), '')

    # Clean up extra spaces
    prompt_text = ' '.join(prompt_text.split())
    
    return prompt_text.strip() if prompt_text else None, neg_prompt_text.strip() if neg_match else None, flags

async def check_pending_jobs(update: Update):
    if is_any_job_running(config.COMFYUI_SERVER_ADDRESS):
        await update.message.reply_text(
            f"The system is currently processing other image requests. Your request is queued ({get_pending_job_count(config.COMFYUI_SERVER_ADDRESS)} in line) and will be processed as soon as possible."
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

def split_long_text(text, max_length=4096):
    """
    Splits text into multiple parts if it exceeds Telegram's limit.
    Returns a list of text parts.
    """
    if len(text) <= max_length:
        return [text]
    
    parts = []
    current_part = ""
    
    # Try to split by sentences first
    sentences = text.split('. ')
    
    for sentence in sentences:
        # Add the period back except for the last sentence
        if sentence != sentences[-1]:
            sentence += '.'
        
        # If adding this sentence would exceed the limit
        if len(current_part) + len(sentence) + 1 > max_length:
            if current_part:
                parts.append(current_part.strip())
            current_part = sentence
        else:
            if current_part:
                current_part += ' ' + sentence
            else:
                current_part = sentence
    
    # Add the last part
    if current_part:
        parts.append(current_part.strip())
    
    # If a single sentence is still too long, split by words
    final_parts = []
    for part in parts:
        if len(part) > max_length:
            words = part.split()
            temp_part = ""
            for word in words:
                if len(temp_part) + len(word) + 1 > max_length:
                    final_parts.append(temp_part.strip())
                    temp_part = word
                else:
                    temp_part += ' ' + word if temp_part else word
            if temp_part:
                final_parts.append(temp_part.strip())
        else:
            final_parts.append(part)
    
    return final_parts

async def send_image_with_logging(
    update: Update,
    image_path: str,
    prompt_text: str,
    workflow_type: str = "Text-to-Image",
    flags=None,
    seed=None,
    duration_seconds=None,
    workflow_name=None,
    nogroup=False,
    ai_model_name=None  # Add AI model name parameter
):
    """
    Sends the generated image to both the user and the logging group.
    """
    # Format duration string
    duration_str = ""
    if duration_seconds:
        if duration_seconds >= 60:
            minutes = int(duration_seconds // 60)
            seconds = int(duration_seconds % 60)
            duration_str = f"\n⏱️ Time duration: {minutes}m {seconds}s ({duration_seconds:.1f} secs)"
        else:
            duration_str = f"\n⏱️ Time duration: {duration_seconds:.1f}s"

    # Add AI model info if available
    ai_model_str = f"\n🤖 Enhanced by: {ai_model_name}" if ai_model_name else ""

    # Prepare the caption with more details
    user_caption = (        
        f"Generation Type: {workflow_type}\n\n"
        f"Prompt: {prompt_text}\n"
        f"{ai_model_str}\n\n"
        f"Cfg: {flags.get('cfg') if flags.get('cfg') is not None else '1.0'}\n"
        f"Steps: {flags.get('steps')}\n"
        f"Seed: {flags.get('seed') if flags.get('seed') is not None else seed}\n"
        f"{duration_str}\n\n"
        f"Workflow: {workflow_name}"
    )

    group_caption = (
        f"Image generated by: @{update.effective_user.username or 'Unknown'}\n"
        f"User ID: {update.effective_user.id}\n"
        f"Generation Type: {workflow_type}\n\n"
        f"Prompt: {prompt_text}\n"
        f"{ai_model_str}\n\n"
        f"Cfg: {flags.get('cfg') if flags.get('cfg') is not None else '1.0'}\n"
        f"Steps: {flags.get('steps')}\n"
        f"Seed: {flags.get('seed') if flags.get('seed') is not None else seed}\n"
        f"{duration_str}\n\n"
        f"Workflow: {workflow_name}"
    )

    # Send to user
    if len(user_caption) <= 1024:
        # Caption fits, send with image
        await update.message.reply_photo(
            photo=open(image_path, 'rb'),
            caption=user_caption
        )
    else:
        # Caption too long, send image without caption, then send text
        await update.message.reply_photo(
            photo=open(image_path, 'rb')
        )
        # Split and send the caption as text messages
        text_parts = split_long_text(user_caption, max_length=4096)
        for part in text_parts:
            await update.message.reply_text(part)

    # Send to logging group if configured and nogroup flag is not set
    if not nogroup and hasattr(config, 'LOGGING_GROUP_ID') and config.LOGGING_GROUP_ID:
        try:
            if len(group_caption) <= 1024:
                # Caption fits, send with image
                await update.get_bot().send_photo(
                    chat_id=config.LOGGING_GROUP_ID,
                    photo=open(image_path, 'rb'),
                    caption=group_caption
                )
            else:
                # Caption too long, send image without caption, then send text
                await update.get_bot().send_photo(
                    chat_id=config.LOGGING_GROUP_ID,
                    photo=open(image_path, 'rb')
                )
                # Split and send the caption as text messages
                text_parts = split_long_text(group_caption, max_length=4096)
                for part in text_parts:
                    await update.get_bot().send_message(
                        chat_id=config.LOGGING_GROUP_ID,
                        text=part
                    )
        except Exception as e:
            logger.error(f"Failed to send image to logging group: {e}\n\n")


def parse_enhanced_prompt(enhanced_response, user_provided_neg_prompt=None):
    """
    Parse the enhanced response from Gemini to separate positive and negative prompts.
    
    Args:
        enhanced_response: The full response from Gemini
        user_provided_neg_prompt: User's negative prompt from --neg flag (if any)
    
    Returns:
        tuple: (positive_prompt, negative_prompt)
    """
    if not enhanced_response:
        return enhanced_response, user_provided_neg_prompt

    # Check if the response contains "negative prompt:"
    if "negative prompt:" in enhanced_response.lower():
        # Split the response into positive and negative parts
        parts = enhanced_response.lower().split("negative prompt:", 1)
        positive_prompt = parts[0].strip()
        ai_negative_prompt = parts[1].strip() if len(parts) > 1 else ""
        return positive_prompt, ai_negative_prompt
    else:
        # No negative prompt in AI response
        return enhanced_response, user_provided_neg_prompt
    

async def handle_magic_prompt_enhancement(update, context, prompt_text, negative_prompt_text, 
                                        enhancement_msg, model_name, flags, wf_path, workflow_name, image_path):
    """Handle Magic Prompt enhancement in the background without blocking the bot."""
    ai_model_name = None  # Initialize to track the enhancer model
    
    try:
        gemini = get_gemini_client()
        wants_negative = negative_prompt_text is not None
        
        # Call the async function directly - don't use asyncio.to_thread for async functions
        enhanced_response, ai_model_name = await gemini.enhance_prompt(
            prompt_text, 
            image_path,  # None for text-only, path for multimodal
            model_name=model_name,
            user_negative_prompt=negative_prompt_text,
            wants_negative=wants_negative
        )
        if context.user_data.get('magic_prompt', True):
            await check_pending_jobs(update)
        
        if enhanced_response and enhanced_response != prompt_text:
            # Parse the enhanced response
            enhanced_prompt, enhanced_neg_prompt = parse_enhanced_prompt(enhanced_response, negative_prompt_text)
            
            if enhanced_prompt != prompt_text:
                # Use clean enhanced prompt for ComfyUI
                prompt_text = enhanced_prompt
                # Show enhancement message to user
                #await enhancement_msg.edit_text(f"🪄 **Enhanced prompt:** {enhanced_prompt}\n\n*Enhanced by: {ai_model_name}*", parse_mode=ParseMode.MARKDOWN)
            
            if wants_negative and enhanced_neg_prompt:
                negative_prompt_text = enhanced_neg_prompt
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"🪄 **Enhanced negative prompt:** {negative_prompt_text}",
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            await enhancement_msg.edit_text("✨ Using original prompt (no enhancement needed)")
            
    except Exception as e:
        logger.error(f"Error enhancing prompt: {e}")
        await enhancement_msg.edit_text("⚠️ Using original prompt due to enhancement error.")
    
    # Now start the actual image generation with enhanced (or original) prompt and AI model info
    await generate_image_task(update, context, prompt_text, negative_prompt_text, flags, wf_path, workflow_name, image_path, ai_model_name)


async def generate_image_task(update, context, prompt_text, negative_prompt_text, flags, wf_path, workflow_name, image_path, ai_model_name=None):
    """Handle the actual image generation."""
    start_time = datetime.now()
    
    if not image_path:  # Text-to-image
        await handle_resize(value=flags.get('resize') if flags.get('resize') else None, update=update)
        
    try:
        if image_path:  # Image-to-image
            generated_image_path, duration_seconds, seed = await asyncio.to_thread(
                generate_image,
                image_path=image_path,
                prompt_text=prompt_text,
                workflow_path=wf_path,
                server_address=config.COMFYUI_SERVER_ADDRESS,
                flags=flags,
                fast_film_grain=flags.get('fast_film_grain', False)
            )
        else:  # Text-to-image
            generated_image_path, duration_seconds, seed = await asyncio.to_thread(
                generate_image,
                image_path=None,
                prompt_text=prompt_text,
                neg_prompt_text=negative_prompt_text,
                workflow_path=wf_path,
                server_address=config.COMFYUI_SERVER_ADDRESS,
                flags=flags,
                resize_resolution=flags.get('resize') if flags.get('resize') else None,
                allow_resize=update.effective_user.id == config.MY_USER_ID
            )
        
        time.sleep(1)
        
        # Use ComfyUI's duration if available, otherwise calculate fallback
        if duration_seconds is None:
            end_time = datetime.now()
            duration = end_time - start_time
            duration_seconds = duration.total_seconds()

        if generated_image_path and os.path.exists(generated_image_path):
            logger.info(f"Image generated successfully in {duration_seconds:.1f} seconds: {generated_image_path}\n\n")
            
            generation_type = "Image-to-Image" if image_path else "Text-to-Image"
            await send_image_with_logging(
                update,
                generated_image_path,
                prompt_text,
                generation_type,
                flags,
                seed,
                duration_seconds,
                workflow_name,
                nogroup=flags.get('nogroup', False),
                ai_model_name=ai_model_name  # Pass the AI model name to the logging function
            )
        else:
            raise FileNotFoundError("The generated image file was not found.")

    except Exception as e:
        logger.error(f"Failed to generate image for user {update.effective_user.id}. Error: {e}\n\n")
        await update.message.reply_text(
            "Sorry, something went wrong while generating the image. Please try again later."
        )
    finally:
        # Clean up the downloaded image for image-to-image
        if image_path and os.path.exists(image_path):
            os.remove(image_path)