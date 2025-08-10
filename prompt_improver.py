import os
import logging
import base64
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_models import ChatOllama

# --- Configuration ---
# Load environment variables from .env file
load_dotenv()

# Set up logging to see the process in the console
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Models Configuration ---
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
# Vision-capable Gemini models to try
GEMINI_VISION_MODELS_TO_TRY = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-04-17",
    "gemini-2.5-flash-lite-preview-06-17"
]
# A local Ollama vision model to use if all Gemini models fail.
# Ensure you have a multimodal model like 'gemma2' pulled in Ollama.
OLLAMA_VISION_FALLBACK_MODEL = os.getenv("OLLAMA_VISION_FALLBACK_MODEL", "gemma2")


# --- System Prompt ---
# This prompt is expertly crafted for the FLUX.1 text-to-image model.
SYSTEM_PROMPT = """
You are a master-level visual prompt engineer for FLUX.1 Kontext — a state-of-the-art image generation and editing model. Your mission is to transform user intent and reference inputs into high-impact, visually coherent narrative prompts optimized for in-context image synthesis.

## YOUR ENHANCED EDITING FLOW

1. **Extract Creative Intent and Preferences**
   - Identify the user’s emotional tone, composition goals, preferred color palettes, and artistic style references (e.g., "baroque oil painting", "cinematic lens flares", "muted pastel tones").
   - If these are unclear or missing, ask direct clarifying questions to ground the creative direction.

2. **Analyze Reference Image (if provided)**
   - Determine the subject, pose, facial identity (if applicable), texture details, environment, lighting setup, and focal depth.
   - Note stylistic traits (e.g., “grainy texture,” “soft backlight,” “motion blur”), layout balance, and visual storytelling cues.

3. **Align with Desired Edits**
   - Parse the user's prompt to classify the intent:  
     (a) **Style Transfer**  
     (b) **Text Editing**  
     (c) **Object/Clothing Replacement**  
     (d) **Background Swapping**  
     (e) **Character Consistency / Iterative Editing**  
   - Distinguish between local edits (preserve context) and generative edits (rebuild context with fidelity).

4. **Apply Layered Descriptive Detailing**
   - Use clear, actionable phrasing with compound descriptors (e.g., “fractured obsidian armor,” “luminescent ink swirling in liquid gravity”).
   - Describe the subject first, then environment, then atmosphere, and finally style.

5. **Construct the Prompt Structure**
   Compose a **single cohesive paragraph** that follows this flow:
   - **[Subject & Action]**: “A serene astronaut floats weightlessly…”
   - **[Environment & Context]**: “…inside a stained-glass cathedral orbiting Jupiter.”
   - **[Atmosphere & Lighting]**: “Reflections of nebulae ripple across her golden visor under soft, prismatic light.”
   - **[Artistic Style & Medium]**: “Hyperreal concept art with painterly textures and soft volumetric fog.”

6. **Include a Precision-Tuned Negative Prompt**
   - Always append this on a separate line:
     ```
     Negative prompt: ugly, deformed, disfigured, poor anatomy, bad hands, extra limbs, blurry, pixelated, low contrast.
     ```

## OUTPUT GUIDELINES
- Return **only** the narrative prompt and negative prompt — no commentary, no greetings, no explanations.
- Ensure prompts are compatible with iterative editing and character-preserving workflows.

"""


# --- Helper Function ---
def _encode_image_to_base64(image_path: str) -> str:
    """Encodes an image file to a base64 string."""
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to encode image at {image_path}. Error: {e}")
        return None

# --- Main Function ---
def improve_prompt(original_prompt: str, image_path: str) -> str:
    """
    Improves a prompt using multimodal LLMs that analyze both text and an image.

    Args:
        original_prompt (str): The user's original text prompt.
        image_path (str): The path to the user's image.

    Returns:
        str: The improved prompt, or the original prompt if all models fail.
    """
    base64_image = _encode_image_to_base64(image_path)
    if not base64_image:
        logger.error("Could not encode image. Returning original prompt.")
        return original_prompt

    # --- Build the multimodal message ---
    message_content = [
        {"type": "text", "text": f"{SYSTEM_PROMPT}\n\nUser's prompt: '{original_prompt}'"},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
        }
    ]
    multimodal_message = HumanMessage(content=message_content)

    # --- Initialize Models and Chains ---
    models_to_try = []
    # 1. Gemini Models
    if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GOOGLE_API_KEY_HERE":
        for model_name in GEMINI_VISION_MODELS_TO_TRY:
            try:
                llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=GEMINI_API_KEY)
                models_to_try.append({"name": f"Gemini ({model_name})", "model": llm})
            except Exception as e:
                logger.warning(f"Could not initialize Gemini model {model_name}. Error: {e}")
    else:
        logger.warning("GOOGLE_API_KEY not found or not set. Skipping Gemini models.")
        
    # 2. Ollama Fallback Model
    try:
        ollama_llm = ChatOllama(model=OLLAMA_VISION_FALLBACK_MODEL)
        models_to_try.append({"name": f"Ollama ({OLLAMA_VISION_FALLBACK_MODEL})", "model": ollama_llm})
        logger.info(f"Ollama vision fallback '{OLLAMA_VISION_FALLBACK_MODEL}' is configured.")
    except Exception as e:
        logger.warning(f"Could not initialize Ollama vision model. Error: {e}")

    if not models_to_try:
        logger.error("No vision models could be initialized. Returning original prompt.")
        return original_prompt

    # --- Invoke Models Sequentially ---
    output_parser = StrOutputParser()
    for model_info in models_to_try:
        model_name = model_info["name"]
        chain = model_info["model"] | output_parser
        
        logger.info(f"Attempting to improve prompt with {model_name}...")
        try:
            improved_prompt = chain.invoke([multimodal_message])
            if improved_prompt and improved_prompt.strip():
                logger.info(f"Successfully improved prompt with {model_name}.")
                return improved_prompt.strip()
            else:
                logger.warning(f"{model_name} returned an empty response. Trying next model.")
        except Exception as e:
            logger.error(f"Failed to get response from {model_name}. Error: {e}. Trying next model...")
            continue
            
    logger.critical("All vision models failed. Returning the original prompt.")
    return original_prompt

if __name__ == '__main__':
    # For direct testing: create a dummy image and test the function
    if not os.path.exists("input_image.png"):
        try:
            from PIL import Image
            img = Image.new('RGB', (100, 100), color = 'blue')
            img.save('test_image.jpg')
            logger.info("Created a dummy test_image.jpg for testing.")
        except ImportError:
            logger.error("Pillow not installed. Cannot create a test image.")
    
    if os.path.exists("input_image.png"):
        test_prompt = "make it look like a cartoon"
        print(f"\n--- Testing Multimodal Prompt Improver ---")
        print(f"Original Prompt: {test_prompt}")
        print(f"Image: input_image.png")
        improved = improve_prompt(test_prompt, "input_image.png")
        print(f"Improved Prompt: {improved}")
        os.remove("input_image.png") 