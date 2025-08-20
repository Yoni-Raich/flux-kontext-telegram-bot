import google.generativeai as genai
import logging
from typing import Optional, List, Dict, Any
import asyncio
import config
import base64
from PIL import Image
import io
import os

logger = logging.getLogger(__name__)

# System prompt for prompt improvement
SYSTEM_PROMPT = """
You are an expert at creating detailed prompts for AI image generation for {model_name} model. Your task is to improve the user's prompt to generate higher quality, more detailed images.

Guidelines:
1. Keep the core meaning and intent of the original prompt
2. Add descriptive details about lighting, composition, and style
3. Include technical photography terms when appropriate
4. Enhance with artistic style suggestions
5. Make the prompt more specific and detailed
6. If an image is provided, consider its content when improving the prompt

{negative_prompt_instruction}

Return only the improved prompt{negative_format_instruction} do not return any other comments or not related text beside the prompts!.
"""

IMAGE_SYSTEM_PROMPT = """
You are a master-level visual prompt engineer for {model_name} model — a state-of-the-art image generation and editing model. Your mission is to transform user intent and reference inputs into high-impact, visually coherent narrative prompts optimized for in-context image synthesis.

## YOUR ENHANCED EDITING FLOW

1. **Extract Creative Intent and Preferences**
   - Identify the user's emotional tone, composition goals, preferred color palettes, and artistic style references (e.g., "baroque oil painting", "cinematic lens flares", "muted pastel tones").
   - If these are unclear or missing, ask direct clarifying questions to ground the creative direction.

2. **Analyze Reference Image (if provided)**
   - Determine the subject, pose, facial identity (if applicable), texture details, environment, lighting setup, and focal depth.
   - Note stylistic traits (e.g., "grainy texture," "soft backlight," "motion blur"), layout balance, and visual storytelling cues.

3. **Align with Desired Edits**
   - Parse the user's prompt to classify the intent:  
     (a) **Style Transfer**  
     (b) **Text Editing**  
     (c) **Object/Clothing Replacement**  
     (d) **Background Swapping**  
     (e) **Character Consistency / Iterative Editing**  
   - Distinguish between local edits (preserve context) and generative edits (rebuild context with fidelity).

4. **Apply Layered Descriptive Detailing**
   - Use clear, actionable phrasing with compound descriptors (e.g., "fractured obsidian armor," "luminescent ink swirling in liquid gravity").
   - Describe the subject first, then environment, then atmosphere, and finally style.

5. **Construct the Prompt Structure**
   Compose a **single cohesive paragraph** that follows this flow:
   - **[Subject & Action]**: "A serene astronaut floats weightlessly…"
   - **[Environment & Context]**: "…inside a stained-glass cathedral orbiting Jupiter."
   - **[Atmosphere & Lighting]**: "Reflections of nebulae ripple across her golden visor under soft, prismatic light."
   - **[Artistic Style & Medium]**: "Hyperreal concept art with painterly textures and soft volumetric fog."

{negative_prompt_instruction}

## OUTPUT GUIDELINES
- Return **only** the narrative prompt{negative_format_instruction} — no commentary, no greetings, no explanations.
- Ensure prompts are compatible with iterative editing and character-preserving workflows.

"""


class GeminiClient:
    def __init__(self):
        """Initialize Gemini client with API key from config."""
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")
        
        genai.configure(api_key=api_key)

        ###########################################################
        # Print the available models
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(m.name)
        ###########################################################

        # Get model lists from config if available, otherwise use defaults
        self.vision_models = getattr(config, 'GEMINI_VISION_MODELS_TO_TRY', config.GEMINI_VISION_MODELS_TO_TRY)
        self.text_models = getattr(config, 'GEMINI_TEXT_MODELS_TO_TRY', config.GEMINI_TEXT_MODELS_TO_TRY)
        
        # Initialize available models
        self.available_vision_models = self._initialize_models(self.vision_models, "vision")
        self.available_text_models = self._initialize_models(self.text_models, "text")
    
    def _initialize_models(self, model_names: List[str], model_type: str) -> List[Dict[str, Any]]:
        """
        Initialize and validate Gemini models.
        
        Args:
            model_names: List of model names to try
            model_type: Type of models ("vision" or "text")
            
        Returns:
            List of successfully initialized models
        """
        models_to_try = []
        
        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                models_to_try.append({
                    "name": f"Gemini ({model_name})", 
                    "model": model,
                    "model_name": model_name
                })
                logger.info(f"Successfully initialized {model_type} model: {model_name}")
            except Exception as e:
                logger.warning(f"Could not initialize Gemini {model_type} model {model_name}. Error: {e}")
        
        if not models_to_try:
            logger.error(f"No {model_type} models could be initialized.")
        else:
            logger.info(f"Initialized {len(models_to_try)} {model_type} models.")
            
        return models_to_try
    
    def _encode_image_to_base64(self, image_path: str) -> Optional[str]:
        """
        Encode an image file to base64 string.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Base64 encoded string or None if error
        """
        try:
            with open(image_path, 'rb') as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Error encoding image to base64: {e}")
            return None
    
    async def enhance_prompt_text_only(self, user_prompt: str, target_model: Optional[str] = None, user_negative_prompt: Optional[str] = None, wants_negative: bool = False) -> str:
        """
        Enhance a text prompt without image analysis using multiple models.
        
        Args:
            user_prompt: Original user prompt
            target_model: Target model name for optimization
            user_negative_prompt: User's negative prompt (if provided)
            wants_negative: Whether user wants negative prompt generation
            
        Returns:
            Enhanced prompt or original prompt if all models fail
        """
        if not self.available_text_models:
            logger.error("No text models available. Returning original prompt.")
            return user_prompt
        
        # Prepare negative prompt instructions based on user preference
        if wants_negative:
            if user_negative_prompt:
                negative_instruction = f"7. IMPORTANT: The user provided this negative prompt: '{user_negative_prompt}'. Please enhance and improve this negative prompt as well to better avoid unwanted elements."
                format_instruction = " and enhanced negative prompt"
            else:
                negative_instruction = "7. IMPORTANT: Generate an appropriate negative prompt to avoid common unwanted elements like blur, distortion, poor anatomy, etc."
                format_instruction = " and negative prompt"
        else:
            negative_instruction = "7. IMPORTANT: Do NOT generate any negative prompt. Focus only on enhancing the positive prompt."
            format_instruction = ""
        
        # Create a shuffled copy of available models to try randomly
        import random
        models_to_try = self.available_text_models.copy()
        random.shuffle(models_to_try)
        failed_models = set()
        
        # Try each model randomly, avoiding failed ones
        for model_info in models_to_try:
            model_name = model_info["name"]
            model_id = model_info["model_name"]
            
            # Skip if this model already failed in this loop
            if model_id in failed_models:
                continue
                
            model = model_info["model"]
            
            # Format the system prompt with the target model name and negative prompt instructions
            formatted_system_prompt = SYSTEM_PROMPT.format(
                model_name=target_model or "AI image generation",
                negative_prompt_instruction=negative_instruction,
                negative_format_instruction=format_instruction
            )
            
            enhancement_instruction = f"""
            {formatted_system_prompt}
            
            User's prompt: '{user_prompt}'
            """
            
            logger.info(f"Attempting to enhance text prompt with {model_name} for target model: {target_model}...")
     
            try:
                response = await asyncio.to_thread(
                    model.generate_content,
                    enhancement_instruction
                )
                
                if response and response.text and response.text.strip():
                    enhanced = response.text.strip()
                    logger.info(f"Successfully enhanced text prompt with {model_name}.")
                    return enhanced, model_info["model_name"]
                else:
                    logger.warning(f"{model_name} returned an empty response. Marking as failed and trying next model.")
                    failed_models.add(model_id)
                    
            except Exception as e:
                logger.error(f"Failed to get response from {model_name}. Error: {e}. Marking as failed and trying next model...")
                failed_models.add(model_id)
                continue
        
        logger.critical("All text models failed. Returning the original prompt.")
        return user_prompt

    
    async def improve_prompt_multimodal(self, original_prompt: str, image_path: str, target_model: Optional[str] = None, user_negative_prompt: Optional[str] = None, wants_negative: bool = False) -> str:
        """
        Improves a prompt using Gemini Vision models that analyze both text and image.

        Args:
            original_prompt: The user's original text prompt.
            image_path: The path to the user's image.
            target_model: Target model name for optimization.
            user_negative_prompt: User's negative prompt (if provided)
            wants_negative: Whether user wants negative prompt generation

        Returns:
            The improved prompt, or the original prompt if all models fail.
        """
        if not self.available_vision_models:
            logger.error("No vision models available. Returning original prompt.")
            return original_prompt
        
        # Prepare negative prompt instructions based on user preference
        if wants_negative:
            if user_negative_prompt:
                negative_instruction = f"6. **IMPORTANT**: The user provided this negative prompt: '{user_negative_prompt}'. Please enhance and improve this negative prompt as well to better avoid unwanted elements."
                format_instruction = " and enhanced negative prompt on a separate line starting with 'Negative prompt:'"
            else:
                negative_instruction = "6. **IMPORTANT**: Generate an appropriate negative prompt to avoid common unwanted elements. Always append this on a separate line starting with 'Negative prompt:'"
                format_instruction = " and negative prompt on a separate line starting with 'Negative prompt:'"
        else:
            negative_instruction = "6. **IMPORTANT**: Do NOT generate any negative prompt. Focus only on enhancing the positive prompt."
            format_instruction = ""
        
        try:
            # Load and prepare the image
            image = Image.open(image_path)
            
            # Convert to RGB if necessary
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Create a shuffled copy of available models to try randomly
            import random
            models_to_try = self.available_vision_models.copy()
            random.shuffle(models_to_try)
            failed_models = set()
            
            # Try each model randomly, avoiding failed ones
            for model_info in models_to_try:
                model_name = model_info["name"]
                model_id = model_info["model_name"]
                
                # Skip if this model already failed in this loop
                if model_id in failed_models:
                    continue
                    
                model = model_info["model"]
                
                # Format the system prompt with the target model name and negative prompt instructions
                formatted_system_prompt = IMAGE_SYSTEM_PROMPT.format(
                    model_name=target_model or "AI image generation",
                    negative_prompt_instruction=negative_instruction,
                    negative_format_instruction=format_instruction
                )
                
                # Create the prompt with both text and image
                prompt_parts = [
                    f"{formatted_system_prompt}\n\nUser's prompt: '{original_prompt}'",
                    image
                ]
                
                logger.info(f"Attempting to improve prompt with {model_name} for target model: {target_model}...")
                try:
                    response = await asyncio.to_thread(
                        model.generate_content,
                        prompt_parts
                    )
                    
                    if response and response.text and response.text.strip():
                        improved_prompt = response.text.strip()
                        logger.info(f"Successfully improved prompt with {model_name}.")
                        return improved_prompt
                    else:
                        logger.warning(f"{model_name} returned an empty response. Marking as failed and trying next model.")
                        failed_models.add(model_id)
                        
                except Exception as e:
                    logger.error(f"Failed to get response from {model_name}. Error: {e}. Marking as failed and trying next model...")
                    failed_models.add(model_id)
                    continue
            
            logger.critical("All vision models failed. Returning the original prompt.")
            return original_prompt
                
        except Exception as e:
            logger.error(f"Error preparing image for multimodal enhancement: {e}")
            return original_prompt
    
    async def enhance_prompt(self, user_prompt: str, image_path: Optional[str] = None, model_name: Optional[str] = None, user_negative_prompt: Optional[str] = None, wants_negative: bool = False) -> str:
        """
        Main method to enhance prompts - uses multimodal if image provided, text-only otherwise.
        
        Args:
            user_prompt: Original user prompt
            image_path: Optional path to image for multimodal enhancement
            model_name: Optional name of the target model for optimization
            user_negative_prompt: User's negative prompt (if provided with --neg flag)
            wants_negative: Whether user wants negative prompt (True if --neg flag used)
            
        Returns:
            Enhanced prompt or original prompt if error
        """
        if image_path:
            return await self.improve_prompt_multimodal(user_prompt, image_path, model_name, user_negative_prompt, wants_negative)
        else:
            return await self.enhance_prompt_text_only(user_prompt, model_name, user_negative_prompt, wants_negative)

    
    def get_model_status(self) -> Dict[str, Any]:
        """
        Get status information about available models.
        
        Returns:
            Dictionary with model availability information
        """
        return {
            "vision_models_available": len(self.available_vision_models),
            "text_models_available": len(self.available_text_models),
            "vision_models": [model["model_name"] for model in self.available_vision_models],
            "text_models": [model["model_name"] for model in self.available_text_models]
        }

# Global instance
gemini_client = None

def get_gemini_client() -> GeminiClient:
    """Get or create Gemini client instance."""
    global gemini_client
    if gemini_client is None:
        gemini_client = GeminiClient()
    return gemini_client

def get_model_status() -> Dict[str, Any]:
    """Get status of available Gemini models."""
    client = get_gemini_client()
    return client.get_model_status()