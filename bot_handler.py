import os
import logging
import re
import asyncio
import time
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from datetime import datetime

import config
from comfy_client import generate_image, is_any_job_running, get_pending_job_count, generate_audio

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


def cleanup_comfyui_files_async(prompt_id, generated_file_path=None):
    """
    Clean up ComfyUI output files asynchronously in the background.
    
    Args:
        prompt_id: The ComfyUI prompt ID to clean up
    """
    if prompt_id:
        try:
            from comfy_client import cleanup_comfyui_outputs
            asyncio.create_task(asyncio.to_thread(
                cleanup_comfyui_outputs, 
                prompt_id, 
                config.COMFYUI_SERVER_ADDRESS,
                config.COMFYUI_OUTPUT_DIR
            ))

            if generated_file_path and os.path.exists(generated_file_path):
                asyncio.create_task(asyncio.to_thread(os.remove, generated_file_path))
                logger.info(f"Scheduled cleanup of local file: {generated_file_path}")
        except Exception as e:
            logger.error(f"Error during ComfyUI cleanup: {e}")

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
async def _help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /help command and displays a detailed help message.
    """
    magic_status = "ON" if context.user_data.get('magic_prompt', True) else "OFF"  # Changed False to True
    magic_available = "✨ Available" if GEMINI_AVAILABLE else "❌ Not Available"
    
    _help_text = (
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
        "*\\-\\-upscale:*\n Will upscale the image x2 Using QWEN model\nFor WAN upscaler add the word wan21 in ur prompt\\(wan upscaler is BETA, currently slightly changes the picture, better to also set a low denoise for the seed 0\\.02\\)\\.\nFor QWEN 2509 upscaler add qwen2509 in ur prompt\\.\n\n"
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
        "*__Multi\\-Image Generation:__*\n"
        "Send 2\\-4 images together with a caption to generate using multiple input images\\.\n"
        "*Available Multi\\-Image Models:*\n"
        "• *qwen25092* \\- QWEN 2509 with 2 image inputs\n"
        "• *qwen25093* \\- QWEN 2509 with 3 image inputs\n"
        "• *qwen2509cn2* \\- QWEN 2509 with 2 images \\+ ControlNet\n"
        "• *qwen2509cn3* \\- QWEN 2509 with 3 images \\+ ControlNet\n"
        "• Default: QWEN 8\\-step with 4 image inputs\n\n"
        "*Multi\\-Image Example:*\n"
        "1\\. Select 2\\-4 images from your gallery\n"
        "2\\. Add caption: 'qwen25093 Combine these images into a surreal landscape'\n"
        "3\\. Send the image group\n\n"
        "*__Voice Cloning \\(Audio Generation\\):__*\n"
        "Send an audio file with a caption to clone the voice and generate new speech\\.\n"
        "*Supported Audio Formats:*\n"
        "mp3, wav, m4a, ogg, flac, aiff, webm, voice messages\n\n"
        "*Audio Example:*\n"
        "1\\. Send an audio file \\(or record a voice message\\)\n"
        "2\\. Add caption: 'Hello, this is a test of voice cloning technology'\n"
        "3\\. The bot will generate audio with the same voice saying your text\n\n"
        "*Available Audio Flags:*\n"
        "*\\-\\-seed:* Sets a specific seed for reproducibility\n"
        "*\\-\\-cfg:* Controls guidance scale for audio generation\n"
        "*\\-\\-steps:* Controls generation steps for audio\n\n"
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
        "Add 'wan22dslr4' before your prompt to use WAN 2\\.2 4\\-Steps DSLR Lora model\\:\n"
        "```\n"
        "wan22dslr4 A photo realistic portrait of a blonde hair nordic woman"
        "```\n\n"
        "Add 'qwen4' or 'qwen8' before your prompt to use Qwen model\\:\n"
        "```\n"
        "qwen4 A photo realistic portrait of a blonde hair nordic woman"
        "```\n\n"
        "Add 'kreawf' before your prompt to use Krea model\\:\n"
        "```\n"
        "kreawf A photo realistic portrait of a blonde hair nordic woman"
        "```\n\n"
        "*Additional Upscaler Models:*\n"
        "• *nunchakuflux* \\- Nunchaku Flux Upscaler\n"
        "• *nnchflxasd* \\- Flux Nunchaku Upscaler ASD\n"
        "• *fluxmaniaup* \\- FluxMania Upscaler 2048\n\n"
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
        "Add 'wan22dslr4' before your prompt to use WAN 2\\.2 4\\-Steps DSLR Lora model\\:\n"
        "```\n"
        "wan22dslr4 A photo realistic portrait of a blonde hair nordic woman"
        "```\n\n"
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


@authorized
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /help command and displays an interactive help menu.
    """
    magic_status = "ON" if context.user_data.get('magic_prompt', True) else "OFF"
    magic_available = "✨ Available" if GEMINI_AVAILABLE else "❌ Not Available"
    
    help_intro = (
        f"*Welcome to the AI Image Generation Bot\\!*\n\n"
        f"🤖 *Magic Prompt:* Currently {magic_status} \\({magic_available}\\)\n\n"
        f"*Choose a topic below for detailed help:*"
    )
    
    # Create inline keyboard buttons
    keyboard = [
        [
            InlineKeyboardButton("📝 Text to Image", callback_data="help_t2i"),
            InlineKeyboardButton("🖼️ Image to Image", callback_data="help_i2i")
        ],
        [
            InlineKeyboardButton("📸 Multi-Image", callback_data="help_multi"),
            InlineKeyboardButton("🔍 Upscalers", callback_data="help_upscale")
        ],
        [
            InlineKeyboardButton("🎵 Voice Cloning", callback_data="help_audio"),
            InlineKeyboardButton("⚙️ Flags & Settings", callback_data="help_flags")
        ],
        [
            InlineKeyboardButton("🧙‍♂️ Magic Prompt", callback_data="help_magic"),
            InlineKeyboardButton("📊 Queue Status", callback_data="help_queue")  # NEW BUTTON
        ],
        [
            InlineKeyboardButton("🏠 Main Menu", callback_data="help_main")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        help_intro, 
        parse_mode=ParseMode.MARKDOWN_V2, 
        reply_markup=reply_markup
    )

# Add this new callback handler function:
async def help_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks for help menu."""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    # Create back button
    back_keyboard = [[InlineKeyboardButton("🔙 Back to Help Menu", callback_data="help_main")]]
    back_markup = InlineKeyboardMarkup(back_keyboard)
    
    if callback_data == "help_main":
        # Show main help menu again
        magic_status = "ON" if context.user_data.get('magic_prompt', True) else "OFF"
        magic_available = "✨ Available" if GEMINI_AVAILABLE else "❌ Not Available"
        
        help_intro = (
            f"*Welcome to the AI Image Generation Bot\\!*\n\n"
            f"🤖 *Magic Prompt:* Currently {magic_status} \\({magic_available}\\)\n\n"
            f"*Choose a topic below for detailed help:*"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("📝 Text to Image", callback_data="help_t2i"),
                InlineKeyboardButton("🖼️ Image to Image", callback_data="help_i2i")
            ],
            [
                InlineKeyboardButton("📸 Multi-Image", callback_data="help_multi"),
                InlineKeyboardButton("🔍 Upscalers", callback_data="help_upscale")
            ],
            [
                InlineKeyboardButton("🎵 Voice Cloning", callback_data="help_audio"),
                InlineKeyboardButton("⚙️ Flags & Settings", callback_data="help_flags")
            ],
            [
                InlineKeyboardButton("🧙‍♂️ Magic Prompt", callback_data="help_magic"),
                InlineKeyboardButton("📊 Queue Status", callback_data="help_queue")  # ADD HERE TOO
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            help_intro,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
    # ADD THE NEW QUEUE STATUS HANDLER        
    elif callback_data == "help_queue":
        try:
            logger.info(f"Checking queue status for server: {config.COMFYUI_SERVER_ADDRESS}")

            # Get queue information with detailed logging
            is_running = False
            pending_count = 0

            try:
                is_running = is_any_job_running(config.COMFYUI_SERVER_ADDRESS)
                logger.info(f"is_any_job_running returned: {is_running}")

                pending_count = get_pending_job_count(config.COMFYUI_SERVER_ADDRESS)
                logger.info(f"get_pending_job_count returned: {pending_count}")

            except Exception as queue_error:
                logger.error(f"Error getting queue info: {queue_error}")
                raise queue_error

            # Create status message
            if is_running:
                if pending_count > 1:
                    status_emoji = "🔴"
                    status_text = f"Busy \\- {pending_count} jobs in queue"
                else:
                    status_emoji = "🟡" 
                    status_text = "Busy \\- 1 job running"
            else:
                status_emoji = "🟢"
                status_text = "Available \\- No jobs in queue"

            logger.info(f"Final status: {status_emoji} {status_text}")

            # Add current time to make the message unique on refresh
            from datetime import datetime
            current_time = datetime.now().strftime("%H:%M:%S")

            text = (
                f"*📊 ComfyUI Queue Status*\n\n"
                f"{status_emoji} *Server Status:* {status_text}\n\n"                
                f"*Last Updated:* {current_time}\n\n"                
                f"*What this means:*\n"
                f"• 🟢 Available: Your request will start immediately\n"
                f"• 🟡 Busy: One job running, minimal wait\n"
                f"• 🔴 Queue: Multiple jobs waiting, longer wait time\n\n"
                f"*Note:* Status updates in real\\-time when you click refresh\\."
            )

            # Add refresh button
            refresh_keyboard = [
                [InlineKeyboardButton("🔄 Refresh Status", callback_data="help_queue")],
                [InlineKeyboardButton("🔙 Back to Help Menu", callback_data="help_main")]
            ]
            refresh_markup = InlineKeyboardMarkup(refresh_keyboard)

            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=refresh_markup)

        except Exception as e:
            # Check if the error is about message not being modified
            if "Message is not modified" in str(e):
                # Just acknowledge the callback without doing anything
                logger.info("Queue status unchanged, no update needed")
                return
            else:
                logger.error(f"Error checking queue status: {e}")
                error_text = (
                    f"*📊 Queue Status*\n\n"
                    f"❌ *Error:* Unable to connect to ComfyUI server\n\n"
                    f"*Error Details:* `{str(e)}`\n\n"                    
                    f"*Possible causes:*\n"
                    f"• ComfyUI server is not running\n"
                    f"• Network connection issues\n"
                    f"• Server is temporarily unavailable\n\n"
                    f"Please try again later or contact the administrator\\."
                )

                # Add refresh and back buttons even on error
                error_keyboard = [
                    [InlineKeyboardButton("🔄 Try Again", callback_data="help_queue")],
                    [InlineKeyboardButton("🔙 Back to Help Menu", callback_data="help_main")]
                ]
                error_markup = InlineKeyboardMarkup(error_keyboard)

                await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=error_markup)

        except Exception as e:
            logger.error(f"Error checking queue status: {e}")
            error_text = (
                f"*📊 Queue Status*\n\n"
                f"❌ *Error:* Unable to connect to ComfyUI server\n\n"
                f"*Error Details:* `{str(e)}`\n\n"
                f"*Server Address:* `{config.COMFYUI_SERVER_ADDRESS}`\n\n"
                f"*Possible causes:*\n"
                f"• ComfyUI server is not running\n"
                f"• Network connection issues\n"
                f"• Server is temporarily unavailable\n\n"
                f"Please try again later or contact the administrator\\."
            )

            # Add refresh and back buttons even on error
            error_keyboard = [
                [InlineKeyboardButton("🔄 Try Again", callback_data="help_queue")],
                [InlineKeyboardButton("🔙 Back to Help Menu", callback_data="help_main")]
            ]
            error_markup = InlineKeyboardMarkup(error_keyboard)

            await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=error_markup)  
    
    elif callback_data == "help_t2i":
        text = (
            "*📝 Text to Image Generation*\n\n"
            "Simply send me a text prompt to generate an image\\. Default model is WAN2\\.1\\.\n\n"
            "*Available Models:*\n"
            "• Default: WAN2\\.1 \\- Default 10 steps\n"
            "• `kreawf` \\- Flux1\\-Krea\\-dev \\- Default 20 steps\n"
            "• `kreasmp` \\- Krea simplified \\- Default 20 steps\n"
            "• `kontext` \\- Flux1\\-Kontext\\-dev \\- Default 20 steps\n"
            "• `qwen4` / `qwen8` \\- QWEN models \\- No need to change steps uses LORAs for 4 and 8 steps\n"
            "• `wan22dslr4` \\- WAN 2\\.2 DSLR Lora \\- no need to change steps uses 4 steps LORA\n\n"
            "*Example:*\n"
            "```shell\n"
            "A photo realistic portrait of a woman\n"
            "```\n"
            "*Change model:*\n"
            "To change a model add the model name from the above options to your prompt\n"
            "```shell\n"
            "kreawf A cyberpunk cityscape at night\n"
            "```\n"
            "```shell\n"
            "A cyberpunk cityscape at night \\-\\-res 1920x1080 \\-\\-steps 20 \\-\\-qwen8\n"
            "```"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=back_markup)
    
    elif callback_data == "help_i2i":
        text = (
            "*🖼️ Image to Image Generation*\n\n"
            "Send an image with a caption to transform it\\. Default model is Flux1\\-Kontext\\-dev\\.\n\n"
            "*How to use:*\n"
            "1\\. Tap the paperclip icon\n"
            "2\\. Select an image\n"
            "3\\. Add a caption describing the transformation\n"
            "4\\. Send\\!\n\n"
            "*Available Models:*\n"
            "• Default: QWEN Edit 2509 \\- 4 steps LORA\n\n"
            "• `kontext` \\- FLUX Kontext Dev\n"
            "   default steps are 20\n\n"
            "• `qwen4` / `qwen8` \\- QWEN model\\, no need to change steps uses LORAs for 4 and 8 steps\n\n"
            "*Example:*\n"
            "Send a photo of your dog with caption:\n"
            "```shell\n"
            "Transform into a painting in Van Gogh style\n"
            "```"
            "```shell\n"
            "kontext Transform into a painting in Van Gogh style\n"
            "```"
            "```shell\n"
            "qwen8 Transform into a painting in Van Gogh style\n"
            "```"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=back_markup)
    
    elif callback_data == "help_multi":
        text = (
            "*📸 Multi\\-Image Generation*\n\n"
            "Send 2\\-4 images together with a caption to generate using multiple inputs\\.\n\n"
            "*Available Models:*\n"
            "• `qwen25092` \\- QWEN 2509 with 2 images\n"
            "• `qwen25093` \\- QWEN 2509 with 3 images\n"
            "• `qwen2509cn2` \\- QWEN 2509 \\+ ControlNet \\(2 images\\)\n"
            "• `qwen2509cn3` \\- QWEN 2509 \\+ ControlNet \\(3 images\\)\n"
            "• Default: QWEN 8\\-step with 4 images\n\n"
            "*ControlNet Flags \\(for cn2/cn3 models\\):*\n"
            "• `\\-\\-cnopenpose` \\- Use OpenPose ControlNet\n"
            "• `\\-\\-cndepth` \\- Use Depth ControlNet\n\n"
            "*How to use:*\n"
            "1\\. Select 2\\-4 images from gallery\n"
            "2\\. Add caption: `qwen25093 Combine into surreal art`\n"
            "3\\. Send as group\n\n"
            "*Example:*\n"
            "Send 3 images with caption:\n"
            "```shell\n"
            "qwen25093 the woman from image 1 wears the hoodie from image 2 and holds the bag from image 3\n"
            "```\n\n"
            "*NOTE\\:* when using control net\\, the second image is the reference image for the transformation\n\n"
            "*ControlNet Examples:*\n"
            "```shell\n"
            "qwen2509cn2 \\-\\-cnopenpose change pose to match reference\n"
            "```\n"
            "```shell\n"
            "qwen2509cn3 \\-\\-cndepth combine with depth guidance\n"
            "```\n\n"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=back_markup)
    
    elif callback_data == "help_upscale":
        text = (
            "*🔍 Upscaler Models*\n\n"
            "Use `\\-\\-upscale` flag with an image to upscale 2x\\.\n\n"
            "*Available Upscalers:*\n"
            "• Default: QWEN Upscaler\n"
            "    \\-\\-chngsmp for QWEN upscaler to change sampler type\n\n"
            "• `wan21` \\- WAN 2\\.1 Upscaler \\(Beta \\- takes longer approx 5 min\\)\n"
            "    Additional flags example:\n    \\-\\-upnoise 0\\.1 \\-\\-seednoise 0\\.02\n for wan21 upscaler\n\n"
            "• `nunchakuflux` \\- Nunchaku Flux\n"
            "• `nnchflxasd` \\- Flux Nunchaku ASD\n"
            "• `fluxmaniaup` \\- FluxMania 2048\n\n"
            "*Usage:*\n"
            "Send image with caption:\n"
            "```shell\n"
            "\\-\\-upscale wan21 enhance this image\n"
            "```\n"
            "```shell\n"
            "\\-\\-upscale\n"
            "```\n\n"
            "*Note:* WAN upscaler may slightly change the image\\. Use low denoise \\(0\\.02\\) for better results\\."
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=back_markup)
    
    elif callback_data == "help_audio":
        text = (
            "*🎵 Voice Cloning*\n\n"
            "Send an audio file with a caption to clone the voice\\.\n\n"
            "*Supported Formats:*\n"
            "mp3, wav, m4a, ogg, flac, aiff, webm, voice messages\n\n"
            "*How to use:*\n"
            "1\\. Send an audio file or record voice message\n"
            "2\\. Add caption with text to generate\n"
            "3\\. Bot will clone the voice saying your text\n\n"
            "*Example:*\n"
            "Send voice recording with caption:\n"
            "```shell\n"
            "Hello, this is a test of voice cloning\n"
            "```\n\n"
            "*Available Flags:*\n"
            "• `\\-\\-seed` \\- Set specific seed for reproducibility\n"
            "• `\\-\\-cfg` \\- Control guidance scale for audio generation\\. Default is 1\\.7\n"
            "• `\\-\\-steps` \\- Control generation steps for audio\\. Default is 30\n"
            "• `\\-\\-temperature X\\.X` \\- Control randomness \\(0\\.0\\-1\\.0\\)\\. Default is 0\\.85\n"
            "• `\\-\\-top_p X\\.X` \\- Control diversity \\(0\\.0\\-1\\.0\\)\\. Default is 0\\.95\n\n"
            "*Flag Examples:*\n"
            "```shell\n"
            "\\-\\-temperature 0\\.7 \\-\\-top_p 0\\.9 Now u will say what ill tell u to\n"
            "```\n"
            "```shell\n"
            "\\-\\-seed 12345 \\-\\-cfg 1\\.5 Hello world\n"
            "```"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=back_markup)    
    elif callback_data == "help_flags":
        text = (
            "*⚙️ Flags & Settings*\n\n"
            "*Common Flags:*\n"
            "• \\-\\-steps X \\- Number of generation steps\n"
            "• \\-\\-cfg X\\.X \\- Classifier\\-Free Guidance scale\n"
            "• \\-\\-seed XXXXX \\- Specific seed for reproducibility\n"
            "• \\-\\-res WIDTHxHEIGHT \\- Custom resolution\n"
            "• \\-\\-neg text \\- Negative prompt \\(WAN only\\)\n\n"
            "*Resolution Limits:*\n"
            "• Square \\(1:1\\): max 1400x1400\n"
            "• Landscape: max 1920x1080\n"
            "• Portrait: max 1080x1920\n\n"
            "*Example:*\n"
            "```shell\n"
            "\\-\\-cfg 2\\.5 \\-\\-steps 30 \\-\\-res 1920x1080 landscape photo\n"
            "```"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=back_markup)
    
    elif callback_data == "help_magic":
        magic_status = "ON" if context.user_data.get('magic_prompt', True) else "OFF"
        magic_available = "✨ Available" if GEMINI_AVAILABLE else "❌ Not Available"
        
        text = (
            f"*🧙‍♂️ Magic Prompt Feature*\n\n"
            f"*Status:* {magic_status} \\({magic_available}\\)\n\n"
            f"*What it does:*\n"
            f"• Automatically enhances your prompts using AI\n"
            f"• Analyzes images \\+ text for multimodal enhancement\n"
            f"• Improves generation quality and detail\n\n"
            f"*Commands:*\n"
            f"• /magic \\- Toggle on/off\n\n"
            f"*How it works:*\n"
            f"• Text prompts: Enhanced for better results\n"
            f"• Image\\+caption: Both analyzed together\n"
            f"• Automatic negative prompt generation\n\n"
            f"*Note:* When enabled, you'll see enhancement messages before generation starts\\."
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=back_markup)




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
            elif prompt_text and ('nunchakuflux' in prompt_text.lower() or 'nnchflxasd' in prompt_text.lower() or 'fluxmaniaup' in prompt_text.lower()):
                return "Nunchaku Flux Upscaler"
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
    if  update.edited_message:
        return
    # Check if this is part of a media group (multiple images)
    if update.message.media_group_id:
        return await handle_media_group(update, context)
    
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
        elif prompt_text and 'nunchakuflux' in prompt_text.lower():
            wf_path = config.NUNCHAKU_FLUX_UPSCALER
        elif prompt_text and 'nnchflxasd' in prompt_text.lower():
            wf_path = config.FLUX_NUNCHAKU_UPSCALER_ASD_PATH
        elif prompt_text and 'fluxmaniaup' in prompt_text.lower():
            wf_path = config.FLUXMANIA_UPSCALER_2048_FILE_PATH                     
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
    elif 'qwen2509' in prompt_text.lower():
        wf_path = config.QWEN_2509_4_STEP_I2I_1_INPUT_FILE_PATH
    else:
        wf_path = config.QWEN_2509_4_STEP_I2I_1_INPUT_FILE_PATH

    logger.info(f'\n\nwf path: {wf_path}\n\n')
    workflow_name = wf_path.split('/')[-1].split('.')[0]

    logger.info(f"Received image from {update.effective_user.first_name}. Prompt: '{prompt_text}'\n\n")
    await update.message.reply_text(
        "🎨 Image received. Processing your request, this might take a moment..."
    )

    if prompt_text:
        prompt_text = re.sub(r'\b(wan21|qwen4|qwen8|nunchakuflux|fluxmaniaup|nnchflxasd)\b', '', prompt_text, flags=re.IGNORECASE).strip()
        prompt_text = re.sub(r'qwen2509\w*', '', prompt_text, flags=re.IGNORECASE).strip()
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
            generated_image_path, duration_seconds, seed, prompt_id = await asyncio.to_thread(
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
                
                # Clean up ComfyUI output files after successful sending
                cleanup_comfyui_files_async(prompt_id, generated_image_path)
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
    elif 'wan22dslr4' in prompt_text.lower():
        wf_path = config.WAN_2_2_4STEPS_T2I_DSLR_LORA_FILE_PATH
    else:
        if 'grain' in flags:
            wf_path = config.WAN_T2I_WORKFLOW_FILE_PATH
        else:             
            wf_path = config.WAN_T2I_WORKFLOW__NOGRAIN_FILE_PATH

    prompt_text = re.sub(r'\b(kreawf|kreasmp|wan21|wan22dslr4|qwen4|qwen8)\b', '', prompt_text, flags=re.IGNORECASE).strip()
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
            generated_image_path, duration_seconds, seed, prompt_id = await asyncio.to_thread(
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
                
                # Clean up ComfyUI output files after successful sending
                cleanup_comfyui_files_async(prompt_id, generated_image_path)
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

async def _handle_resize(value, update):
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



async def handle_resize(value, update):
    """
    Handle the resize value from the prompt.
    Returns a tuple of (width, height) or None if invalid.
    """
    if value:
        try:
            width, height = map(int, value.split('x'))
            if (width <= 0 or height <= 0):
                await update.message.reply_text(
                    "Minimum resolution cannot be 0, setting values to default 1024x1024"
                )
                return
            
            # Skip limits for specific user
            if update.effective_user.id == 374504771:
                return
                
            # Check aspect ratio and apply appropriate limits
            aspect_ratio = width / height
            
            # Square aspect ratio (1:1) - allow up to 1400x1400
            if 0.9 <= aspect_ratio <= 1.1:  # Allow some tolerance for square
                if width > 1400 or height > 1400:
                    await update.message.reply_text(
                        "Maximum resolution for square (1:1) aspect ratio is 1400x1400, setting values to default 1024x1024"
                    )
            # Landscape aspect ratio - allow up to 1920x1080
            elif aspect_ratio > 1.1:
                if width > 1920 or height > 1080:
                    await update.message.reply_text(
                        "Maximum resolution for landscape is 1920x1080, setting values to default 1024x1024"
                    )
            # Portrait aspect ratio - allow up to 1080x1920
            else:  # aspect_ratio < 0.9
                if width > 1080 or height > 1920:
                    await update.message.reply_text(
                        "Maximum resolution for portrait is 1080x1920, setting values to default 1024x1024"
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

    # Extract --temperature flag and value (for audio generation)
    temperature_match = re.search(r'--temperature\s+([\d.]+)', prompt_text)
    if temperature_match:
        temp_val = float(temperature_match.group(1))
        # Validate range 0.0-1.0
        if 0.0 <= temp_val <= 1.0:
            flags['temperature'] = temp_val
        else:
            print(f"Warning: temperature value {temp_val} out of range (0.0-1.0), ignoring")
        prompt_text = prompt_text.replace(temperature_match.group(0), '')
    
    # Extract --top_p flag and value (for audio generation)
    top_p_match = re.search(r'--top_p\s+([\d.]+)', prompt_text)
    if top_p_match:
        top_p_val = float(top_p_match.group(1))
        # Validate range 0.0-1.0
        if 0.0 <= top_p_val <= 1.0:
            flags['top_p'] = top_p_val
        else:
            print(f"Warning: top_p value {top_p_val} out of range (0.0-1.0), ignoring")
        prompt_text = prompt_text.replace(top_p_match.group(0), '')  

    # Extract --cnopenpose and --cndepth flags (for ControlNet)
    if '--cnopenpose' in prompt_text:
        flags['cnopenpose'] = True
        prompt_text = prompt_text.replace('--cnopenpose', '')
    elif '--cndepth' in prompt_text:
        flags['cndepth'] = True
        prompt_text = prompt_text.replace('--cndepth', '')          
    
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
    # Telegram's photo size limit (10MB)
    PHOTO_SIZE_LIMIT = 10485760  # 10MB in bytes
    
    # Check file size
    file_size = os.path.getsize(image_path)
    send_as_document = file_size > PHOTO_SIZE_LIMIT
    
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
    
    # Add file size info if sending as document
    file_size_str = f"\n📁 File size: {file_size / 1024 / 1024:.1f}MB (sent as document)" if send_as_document else ""

    # Prepare the caption with more details
    user_caption = (        
        f"Generation Type: {workflow_type}\n\n"
        f"Prompt: {prompt_text}\n"
        f"{ai_model_str}\n\n"
        f"Cfg: {flags.get('cfg') if flags.get('cfg') is not None else '1.0'}\n"
        f"Steps: {flags.get('steps')}\n"
        f"Seed: {flags.get('seed') if flags.get('seed') is not None else seed}\n"
        f"{duration_str}"
        f"{file_size_str}\n\n"
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
        f"{duration_str}"
        f"{file_size_str}\n\n"
        f"Workflow: {workflow_name}"
    )

    # Send to user
    try:
        if send_as_document:
            # Send as document if file is too large
            if len(user_caption) <= 1024:
                await update.message.reply_document(
                    document=open(image_path, 'rb'),
                    caption=user_caption,
                    filename=f"generated_image_{workflow_name}.png"
                )
            else:
                await update.message.reply_document(
                    document=open(image_path, 'rb'),
                    filename=f"generated_image_{workflow_name}.png"
                )
                # Split and send the caption as text messages
                text_parts = split_long_text(user_caption, max_length=4096)
                for part in text_parts:
                    await update.message.reply_text(part)
        else:
            # Send as photo if file size is acceptable
            if len(user_caption) <= 1024:
                await update.message.reply_photo(
                    photo=open(image_path, 'rb'),
                    caption=user_caption
                )
            else:
                await update.message.reply_photo(
                    photo=open(image_path, 'rb')
                )
                # Split and send the caption as text messages
                text_parts = split_long_text(user_caption, max_length=4096)
                for part in text_parts:
                    await update.message.reply_text(part)
    except Exception as e:
        logger.error(f"Failed to send image to user: {e}")
        # Fallback: try sending as document if photo failed
        if not send_as_document:
            try:
                await update.message.reply_document(
                    document=open(image_path, 'rb'),
                    caption="Image sent as document due to size constraints.",
                    filename=f"generated_image_{workflow_name}.png"
                )
            except Exception as e2:
                logger.error(f"Failed to send image as document: {e2}")

    # Send to logging group if configured and nogroup flag is not set
    if not nogroup and hasattr(config, 'LOGGING_GROUP_ID') and config.LOGGING_GROUP_ID:
        try:
            if send_as_document:
                # Send as document if file is too large
                if len(group_caption) <= 1024:
                    await update.get_bot().send_document(
                        chat_id=config.LOGGING_GROUP_ID,
                        document=open(image_path, 'rb'),
                        caption=group_caption,
                        filename=f"generated_image_{workflow_name}.png"
                    )
                else:
                    await update.get_bot().send_document(
                        chat_id=config.LOGGING_GROUP_ID,
                        document=open(image_path, 'rb'),
                        filename=f"generated_image_{workflow_name}.png"
                    )
                    # Split and send the caption as text messages
                    text_parts = split_long_text(group_caption, max_length=4096)
                    for part in text_parts:
                        await update.get_bot().send_message(
                            chat_id=config.LOGGING_GROUP_ID,
                            text=part
                        )
            else:
                # Send as photo if file size is acceptable
                if len(group_caption) <= 1024:
                    await update.get_bot().send_photo(
                        chat_id=config.LOGGING_GROUP_ID,
                        photo=open(image_path, 'rb'),
                        caption=group_caption
                    )
                else:
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
            logger.error(f"Failed to send image to logging group: {e}")
            # Fallback: try sending as document if photo failed
            if not send_as_document:
                try:
                    await update.get_bot().send_document(
                        chat_id=config.LOGGING_GROUP_ID,
                        document=open(image_path, 'rb'),
                        caption="Image sent as document due to size constraints.",
                        filename=f"generated_image_{workflow_name}.png"
                    )
                except Exception as e2:
                    logger.error(f"Failed to send image as document to logging group: {e2}")


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
                                        enhancement_msg, model_name, flags, wf_path, workflow_name, image_path, image_paths=None):
    """Handle Magic Prompt enhancement in the background without blocking the bot."""
    ai_model_name = None
    
    try:
        gemini = get_gemini_client()
        wants_negative = negative_prompt_text is not None
        
        # For multi-image, use the first image for enhancement
        enhancement_image_path = image_path if image_path else (image_paths[0] if image_paths else None)
        
        enhanced_response, ai_model_name = await gemini.enhance_prompt(
            prompt_text, 
            enhancement_image_path,
            model_name=model_name,
            user_negative_prompt=negative_prompt_text,
            wants_negative=wants_negative
        )
        
        if context.user_data.get('magic_prompt', True):
            await check_pending_jobs(update)
        
        if enhanced_response and enhanced_response != prompt_text:
            enhanced_prompt, enhanced_neg_prompt = parse_enhanced_prompt(enhanced_response, negative_prompt_text)
            
            if enhanced_prompt != prompt_text:
                prompt_text = enhanced_prompt
            
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
    
    # Choose the appropriate generation function
    if image_paths:
        await generate_multi_image_task(update, context, prompt_text, negative_prompt_text, flags, wf_path, workflow_name, image_paths, ai_model_name)
    else:
        await generate_image_task(update, context, prompt_text, negative_prompt_text, flags, wf_path, workflow_name, image_path, ai_model_name)


async def generate_image_task(update, context, prompt_text, negative_prompt_text, flags, wf_path, workflow_name, image_path, ai_model_name=None):
    """Handle the actual image generation."""
    start_time = datetime.now()
    
    if not image_path:  # Text-to-image
        await handle_resize(value=flags.get('resize') if flags.get('resize') else None, update=update)
        
    try:
        if image_path:  # Image-to-image
            generated_image_path, duration_seconds, seed, prompt_id = await asyncio.to_thread(
                generate_image,
                image_path=image_path,
                prompt_text=prompt_text,
                workflow_path=wf_path,
                server_address=config.COMFYUI_SERVER_ADDRESS,
                flags=flags,
                fast_film_grain=flags.get('fast_film_grain', False),
                resize_resolution=flags.get('resize') if flags.get('resize') else None,
                allow_resize=update.effective_user.id == config.MY_USER_ID
            )
        else:  # Text-to-image
            generated_image_path, duration_seconds, seed, prompt_id = await asyncio.to_thread(
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
                ai_model_name=ai_model_name
            )
            
            # Clean up ComfyUI output files after successful sending
            cleanup_comfyui_files_async(prompt_id, generated_image_path)
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

async def handle_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles media groups (multiple images sent together).
    """
    if not is_active_hours():
        await update.message.reply_text(ACTIVE_MSG)
        return

    # Get media group ID
    media_group_id = update.message.media_group_id
    if not media_group_id:
        return  # Not a media group
    
    # Use context to store media group data
    if 'media_groups' not in context.bot_data:
        context.bot_data['media_groups'] = {}
    
    # Store this message in the media group
    if media_group_id not in context.bot_data['media_groups']:
        context.bot_data['media_groups'][media_group_id] = {
            'messages': [],
            'timer': None,
            'processed': False
        }
    
    # Add this message to the group
    context.bot_data['media_groups'][media_group_id]['messages'].append(update.message)
    
    # Cancel existing timer and set a new one
    if context.bot_data['media_groups'][media_group_id]['timer']:
        context.bot_data['media_groups'][media_group_id]['timer'].cancel()
    
    # Set timer to process after 2 seconds of no new images
    timer = asyncio.create_task(process_media_group_after_delay(
        context, media_group_id, update.effective_user.id
    ))
    context.bot_data['media_groups'][media_group_id]['timer'] = timer

async def process_media_group_after_delay(context, media_group_id, user_id):
    """Process media group after a short delay to ensure all images are received."""
    await asyncio.sleep(2)  # Wait 2 seconds for all images
    
    if (media_group_id not in context.bot_data['media_groups'] or
        context.bot_data['media_groups'][media_group_id]['processed']):
        return
    
    # Mark as processed
    context.bot_data['media_groups'][media_group_id]['processed'] = True
    
    messages = context.bot_data['media_groups'][media_group_id]['messages']
    
    # Check if we have 2-4 images
    if len(messages) < 2 or len(messages) > 4:
        # Send error message to the first message in the group
        first_message = messages[0]
        await first_message.reply_text(
            f"Multi-image generation supports 2-4 images only. You sent {len(messages)} images."
        )
        # Clean up
        del context.bot_data['media_groups'][media_group_id]
        return
    
    # Get caption from the first message that has one
    prompt_text = None
    for msg in messages:
        if msg.caption:
            prompt_text = msg.caption
            break
    
    if not prompt_text:
        first_message = messages[0]
        await first_message.reply_text(
            "Please provide a caption with your images. The caption will be used as the prompt."
        )
        # Clean up
        del context.bot_data['media_groups'][media_group_id]
        return
    
    # Process the multi-image request
    await process_multi_image_request(messages, prompt_text, context, user_id)
    
    # Clean up
    del context.bot_data['media_groups'][media_group_id]

async def process_multi_image_request(messages, prompt_text, context, user_id):
    """Process a multi-image generation request."""
    try:
        # Parse prompt flags
        prompt_text, neg_prompt_text, flags = parse_prompt_flags(prompt_text)
        
        # Create temporary directory
        temp_dir = "temp_downloads"
        os.makedirs(temp_dir, exist_ok=True)
        
        # Download all images
        image_paths = []
        for i, message in enumerate(messages):
            photo_file = await message.photo[-1].get_file()
            image_path = os.path.join(temp_dir, f"{photo_file.file_id}_{i}.jpg")
            await photo_file.download_to_drive(image_path)
            image_paths.append(image_path)
        
        # Determine workflow
        if 'qwen2509cn3' in prompt_text.lower():
            wf_path = config.QWEN_2509_4_STEP_I2I_3_INPUTS_CONTROLNET_FILE_PATH  
        elif 'qwen2509cn2' in prompt_text.lower():
            wf_path = config.QWEN_2509_4_STEP_I2I_2_INPUTS_CONTROLNET_FILE_PATH  
        elif 'qwen25093' in prompt_text.lower():
            wf_path = config.QWEN_2509_4_STEP_I2I_3_INPUTS_FILE_PATH    
        elif 'qwen25092' in prompt_text.lower():
            wf_path = config.QWEN_2509_4_STEP_I2I_2_INPUTS_FILE_PATH
        else:
            wf_path = config.QWEN_8_STEP_I2I_4_INPUTS_PATH
        workflow_name = wf_path.split('/')[-1].split('.')[0]
        
        # Determine model name for Magic Prompt
        model_name = "QWEN Multi-Image"
        
        # Limit steps
        if 'steps' in flags and flags['steps'] > config.MAX_STEPS:
            first_message = messages[0]
            await first_message.reply_text(
                f"The maximum number of steps allowed is {config.MAX_STEPS}. Your request will be processed with {config.MAX_STEPS} steps."
            )
            flags['steps'] = config.MAX_STEPS
        
        # Send processing message
        first_message = messages[0]
        await first_message.reply_text(
            f"🎨 {len(messages)} images received. Processing your multi-image request, this might take a moment..."
        )
        
        # Clean prompt text
        if prompt_text:
            prompt_text = re.sub(r'\b(wan21|qwen4|qwen8)\b', '', prompt_text, flags=re.IGNORECASE).strip()
            prompt_text = re.sub(r'qwen2509\w*', '', prompt_text, flags=re.IGNORECASE).strip()
        
        # Create a fake update object for compatibility with existing functions
        # Make sure to include the effective_user with proper id
        fake_effective_user = type('FakeUser', (), {
            'id': user_id,
            'first_name': first_message.from_user.first_name,
            'username': first_message.from_user.username
        })()
        
        fake_update = type('FakeUpdate', (), {
            'message': first_message,
            'effective_user': fake_effective_user,
            'effective_chat': first_message.chat,
            'get_bot': lambda *args, **kwargs: context.bot
        })()
        
        # Handle Magic Prompt enhancement
        if GEMINI_AVAILABLE and context.user_data.get('magic_prompt', True):
            enhancement_msg = await first_message.reply_text("✨ Enhancing your prompt with Magic Prompt (analyzing multiple images and text)...")
            
            # For multi-image, we'll use the first image for Magic Prompt
            asyncio.create_task(handle_magic_prompt_enhancement(
                fake_update, context, prompt_text, neg_prompt_text, 
                enhancement_msg, model_name, flags, wf_path, workflow_name, image_paths[0],
                image_paths  # Pass all image paths as additional parameter
            ))
        else:
            await check_pending_jobs(fake_update)
            await generate_multi_image_task(fake_update, context, prompt_text, neg_prompt_text, flags, wf_path, workflow_name, image_paths)
            
    except Exception as e:
        logger.error(f"Failed to process multi-image request: {e}")
        if messages:
            await messages[0].reply_text(
                "Sorry, something went wrong while processing your multi-image request. Please try again later."
            )

async def generate_multi_image_task(update, context, prompt_text, negative_prompt_text, flags, wf_path, workflow_name, image_paths, ai_model_name=None):
    """Handle the actual multi-image generation."""
    start_time = datetime.now()
    
    try:
        generated_image_path, duration_seconds, seed, prompt_id = await asyncio.to_thread(
            generate_image,
            image_path=None,  # Not used for multi-image
            image_paths=image_paths,  # Use the new parameter
            prompt_text=prompt_text,
            workflow_path=wf_path,
            server_address=config.COMFYUI_SERVER_ADDRESS,
            flags=flags,
            fast_film_grain=flags.get('fast_film_grain', False),
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
            logger.info(f"Multi-image generated successfully in {duration_seconds:.1f} seconds: {generated_image_path}\n\n")
            
            await send_image_with_logging(
                update,
                generated_image_path,
                prompt_text,
                f"Multi-Image-to-Image ({len(image_paths)} images)",
                flags,
                seed,
                duration_seconds,
                workflow_name,
                nogroup=flags.get('nogroup', False),
                ai_model_name=ai_model_name
            )
            
            # Clean up ComfyUI output files after successful sending
            cleanup_comfyui_files_async(prompt_id, generated_image_path)
        else:
            raise FileNotFoundError("The generated image file was not found.")

    except Exception as e:
        logger.error(f"Failed to generate multi-image for user {update.effective_user.id}. Error: {e}\n\n")
        await update.message.reply_text(
            "Sorry, something went wrong while generating the multi-image. Please try again later."
        )
    finally:
        # Clean up the downloaded images
        for image_path in image_paths:
            if os.path.exists(image_path):
                os.remove(image_path)










@authorized
async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles incoming audio files with captions for voice cloning.
    """
    if not is_active_hours():
        await update.message.reply_text(ACTIVE_MSG)
        return

    if not update.message.caption:
        await update.message.reply_text(
            "Please send an audio file with a caption. The caption will be used as the text for voice cloning."
        )
        return

    prompt_text = update.message.caption
    
    # Get the audio file - handle different audio message types
    audio_file = None
    if update.message.audio:
        audio_file = update.message.audio
        file_extension = "mp3"  # Default for audio
    elif update.message.voice:
        audio_file = update.message.voice
        file_extension = "ogg"  # Telegram voice messages are usually OGG
    elif update.message.document:
        # Check if document is an audio file
        if update.message.document.mime_type and update.message.document.mime_type.startswith('audio/'):
            audio_file = update.message.document
            # Get extension from filename or mime_type
            if update.message.document.file_name:
                file_extension = update.message.document.file_name.split('.')[-1].lower()
            else:
                # Map mime types to extensions
                mime_to_ext = {
                    'audio/mpeg': 'mp3',
                    'audio/mp3': 'mp3',
                    'audio/wav': 'wav',
                    'audio/ogg': 'ogg',
                    'audio/flac': 'flac',
                    'audio/m4a': 'm4a',
                    'audio/aiff': 'aiff',
                    'audio/webm': 'webm'
                }
                file_extension = mime_to_ext.get(update.message.document.mime_type, 'mp3')
        else:
            await update.message.reply_text(
                "Please send a valid audio file. Supported formats: .opus, .flac, .webm, .weba, .wav, .ogg, .m4a, .oga, .mid, .mp3, .aiff, .wma, .au"
            )
            return
    else:
        await update.message.reply_text(
            "Please send an audio file with a caption."
        )
        return

    # Parse flags from caption (reuse existing function)
    prompt_text, _, flags = parse_prompt_flags(prompt_text)

    # Create audio directory if it doesn't exist
    audio_dir = "temp_audio"  # You can configure this later
    os.makedirs(audio_dir, exist_ok=True)

    # Download the audio file
    try:
        telegram_file = await audio_file.get_file()
        input_audio_path = os.path.join(audio_dir, f"{telegram_file.file_id}.{file_extension}")
        await telegram_file.download_to_drive(input_audio_path)
    except Exception as e:
        logger.error(f"Failed to download audio file: {e}")
        await update.message.reply_text(
            "Sorry, failed to download the audio file. Please try again."
        )
        return

    logger.info(f"Received audio from {update.effective_user.first_name}. Text: '{prompt_text}'\n\n")
    await update.message.reply_text(
        "🎵 Audio received. Processing your voice cloning request, this might take a moment..."
    )

    # Process the audio
    async def process_and_respond():
        await check_pending_jobs(update)  # Add this line to check for pending jobs
        try:
            # Use the VibeVoice workflow
            wf_path = config.VIBEVOICE_CLONING_WORKFLOW_PATH
            workflow_name = "vibevoice_cloning"
            
            generated_audio_path, duration_seconds, seed, prompt_id = await asyncio.to_thread(
                generate_audio,
                audio_path=input_audio_path,
                prompt_text=prompt_text,
                workflow_path=wf_path,
                server_address=config.COMFYUI_SERVER_ADDRESS,
                flags=flags
            )

            if generated_audio_path and os.path.exists(generated_audio_path):
                logger.info(f"Audio generated successfully in {duration_seconds:.1f} seconds: {generated_audio_path}\n\n")
                await send_audio_with_logging(
                    update,
                    generated_audio_path,
                    prompt_text,
                    "Voice Cloning",
                    flags,
                    seed,  # Pass the seed value
                    duration_seconds,
                    workflow_name,
                    nogroup=flags.get('nogroup', False)
                )
                
                # Clean up ComfyUI output files after successful sending
                cleanup_comfyui_files_async(prompt_id, generated_audio_path)
            else:
                raise FileNotFoundError("The generated audio file was not found.")

        except Exception as e:
            logger.error(f"Failed to generate audio for user {update.effective_user.id}. Error: {e}\n\n")
            await update.message.reply_text(
                "Sorry, something went wrong while processing the audio. Please try again later."
            )
        finally:
            # Clean up the downloaded audio
            if os.path.exists(input_audio_path):
                os.remove(input_audio_path)

    asyncio.create_task(process_and_respond())

async def send_audio_with_logging(
    update: Update,
    audio_path: str,
    prompt_text: str,
    workflow_type: str = "Voice Cloning",
    flags=None,
    seed=None,  # Add seed parameter
    duration_seconds=None,
    workflow_name=None,
    nogroup=False
):
    """
    Sends the generated audio to both the user and the logging group.
    """
    # Telegram's file size limits
    AUDIO_SIZE_LIMIT = 52428800  # 50MB for audio files
    DOCUMENT_SIZE_LIMIT = 52428800  # 50MB for documents
    
    # Check file size
    file_size = os.path.getsize(audio_path)
    
    # Format duration string
    duration_str = ""
    if duration_seconds:
        if duration_seconds >= 60:
            minutes = int(duration_seconds // 60)
            seconds = int(duration_seconds % 60)
            duration_str = f"\n⏱️ Processing time: {minutes}m {seconds}s ({duration_seconds:.1f} secs)"
        else:
            duration_str = f"\n⏱️ Processing time: {duration_seconds:.1f}s"

    # Add file size info
    file_size_str = f"\n📁 File size: {file_size / 1024 / 1024:.1f}MB"

    # Prepare the caption
    user_caption = (
        f"Generation Type: {workflow_type}\n\n"
        f"Text: {prompt_text}\n\n"
        f"Cfg: {flags.get('cfg') if flags.get('cfg') is not None else 'Default'}\n"
        f"Steps: {flags.get('steps') if flags.get('steps') is not None else 'Default'}\n"
        f"Seed: {flags.get('seed') if flags.get('seed') is not None else seed}\n"
        f"Temperature: {flags.get('temperature') if flags.get('temperature') is not None else 'Default'}\n"
        f"Top P: {flags.get('top_p') if flags.get('top_p') is not None else 'Default'}\n"
        f"{duration_str}"
        f"{file_size_str}\n\n"
        f"Workflow: {workflow_name}"
    )

    group_caption = (
        f"Audio generated by: @{update.effective_user.username or 'Unknown'}\n"
        f"User ID: {update.effective_user.id}\n"
        f"Generation Type: {workflow_type}\n\n"
        f"Text: {prompt_text}\n\n"
        f"Cfg: {flags.get('cfg') if flags.get('cfg') is not None else 'Default'}\n"
        f"Steps: {flags.get('steps') if flags.get('steps') is not None else 'Default'}\n"
        f"Seed: {flags.get('seed') if flags.get('seed') is not None else seed}\n"
        f"{duration_str}"
        f"{file_size_str}\n\n"
        f"Workflow: {workflow_name}"
    )

    # Determine file extension for appropriate sending method
    file_extension = audio_path.split('.')[-1].lower()
    filename = f"generated_voice_{workflow_name}.{file_extension}"

    # Send to user
    try:
        if file_size <= AUDIO_SIZE_LIMIT and file_extension in ['mp3', 'wav', 'm4a', 'ogg','flac']:
            # Send as audio file (shows player controls)
            if len(user_caption) <= 1024:
                await update.message.reply_audio(
                    audio=open(audio_path, 'rb'),
                    caption=user_caption,
                    title=f"Voice Clone - {workflow_name}",
                    filename=filename
                )
            else:
                await update.message.reply_audio(
                    audio=open(audio_path, 'rb'),
                    title=f"Voice Clone - {workflow_name}",
                    filename=filename
                )
                # Send caption as text
                text_parts = split_long_text(user_caption, max_length=4096)
                for part in text_parts:
                    await update.message.reply_text(part)
        else:
            # Send as document if file is too large or unsupported audio format
            if len(user_caption) <= 1024:
                await update.message.reply_document(
                    document=open(audio_path, 'rb'),
                    caption=user_caption,
                    filename=filename
                )
            else:
                await update.message.reply_document(
                    document=open(audio_path, 'rb'),
                    filename=filename
                )
                # Send caption as text
                text_parts = split_long_text(user_caption, max_length=4096)
                for part in text_parts:
                    await update.message.reply_text(part)

    except Exception as e:
        logger.error(f"Failed to send audio to user: {e}")
        # Fallback: send as document
        try:
            await update.message.reply_document(
                document=open(audio_path, 'rb'),
                caption="Audio file sent as document.",
                filename=filename
            )
        except Exception as e2:
            logger.error(f"Failed to send audio as document: {e2}")

    # Send to logging group if configured and nogroup flag is not set
    if not nogroup and hasattr(config, 'LOGGING_GROUP_ID') and config.LOGGING_GROUP_ID:
        try:
            if file_size <= AUDIO_SIZE_LIMIT and file_extension in ['mp3', 'wav', 'm4a', 'ogg', 'flac']:
                # Send as audio file
                if len(group_caption) <= 1024:
                    await update.get_bot().send_audio(
                        chat_id=config.LOGGING_GROUP_ID,
                        audio=open(audio_path, 'rb'),
                        caption=group_caption,
                        title=f"Voice Clone - {workflow_name}",
                        filename=filename
                    )
                else:
                    await update.get_bot().send_audio(
                        chat_id=config.LOGGING_GROUP_ID,
                        audio=open(audio_path, 'rb'),
                        title=f"Voice Clone - {workflow_name}",
                        filename=filename
                    )
                    # Send caption as text
                    text_parts = split_long_text(group_caption, max_length=4096)
                    for part in text_parts:
                        await update.get_bot().send_message(
                            chat_id=config.LOGGING_GROUP_ID,
                            text=part
                        )
            else:
                # Send as document
                if len(group_caption) <= 1024:
                    await update.get_bot().send_document(
                        chat_id=config.LOGGING_GROUP_ID,
                        document=open(audio_path, 'rb'),
                        caption=group_caption,
                        filename=filename
                    )
                else:
                    await update.get_bot().send_document(
                        chat_id=config.LOGGING_GROUP_ID,
                        document=open(audio_path, 'rb'),
                        filename=filename
                    )
                    # Send caption as text
                    text_parts = split_long_text(group_caption, max_length=4096)
                    for part in text_parts:
                        await update.get_bot().send_message(
                            chat_id=config.LOGGING_GROUP_ID,
                            text=part
                        )
        except Exception as e:
            logger.error(f"Failed to send audio to logging group: {e}")