import time
import websocket
import uuid
import json
import urllib.request
import urllib.parse
import requests
import os
import random

def find_node_by_class(workflow, class_type, neg_text=False):
    for node_id, node in workflow.items():
        if node.get("class_type") == class_type:
            # Special handling for CLIPTextEncode
            if class_type == "CLIPTextEncode":
                # Check if title contains "positive" (case-insensitive)
                title = node.get("_meta", {}).get("title", "").lower()
                if "positive" in title or ("clip text encode" in title and "negative" not in title):
                    return node_id
                elif neg_text:
                    return node_id
            else:
                # For other class types, return immediately
                return node_id
    return None

def find_load_image_nodes_by_title(workflow):
    """
    Find LoadImage nodes by their titles for multi-image workflows.
    Returns a dictionary mapping titles to node IDs.
    """
    load_image_nodes = {}
    for node_id, node_data in workflow.items():
        if (node_data.get("class_type") == "LoadImage" and 
            "title" in node_data.get("_meta", {})):
            title = node_data["_meta"]["title"]
            if "Load Image" in title:
                load_image_nodes[title] = node_id
    return load_image_nodes

def generate_image(prompt_text: str, 
                   workflow_path: str, 
                   server_address="127.0.0.1:8001", 
                   output_dir="output", 
                   image_path=None, 
                   image_paths=None,  # New parameter for multiple images
                   flags=None, 
                   fast_film_grain=False, 
                   neg_prompt_text=None, 
                   resize_resolution=None,
                   allow_resize=False):
    """
    Generates an image using a ComfyUI workflow.

    Args:
        image_path (str): Path to the input image (single image).
        image_paths (list): List of paths to input images (multiple images).
        prompt_text (str): The text prompt.
        workflow_path (str): Path to the ComfyUI workflow JSON file.
        server_address (str, optional): The address of the ComfyUI server. Defaults to "127.0.0.1:8001".
        output_dir (str, optional): Directory to save the output image. Defaults to "output".
        steps (int, optional): The number of steps for the image generation.
        cfg (float, optional): The CFG scale for the image generation.

    Returns:
        str: The path to the generated image, or None if generation failed.
    """
    client_id = str(uuid.uuid4())
    
    uploaded_filenames = []
    
    # Handle multiple images
    if image_paths:
        print(f"Uploading {len(image_paths)} images...\n\n")
        for i, img_path in enumerate(image_paths):
            with open(img_path, 'rb') as f:
                files = {'image': (os.path.basename(img_path), f, 'image/jpeg')}
                data = {'overwrite': 'true', 'subfolder': ''}
                response = requests.post(f"http://{server_address}/upload/image", files=files, data=data)

            if response.status_code != 200:
                print(f"Error uploading image {i+1}: {response.text}\n\n")
                return None

            upload_response = response.json()
            uploaded_filenames.append(upload_response['name'])
            print(f"Image {i+1} uploaded as: {upload_response['name']}\n\n")
    elif image_path:
        # Single image upload (existing code)
        print("Uploading image...\n\n")
        with open(image_path, 'rb') as f:
            files = {'image': (os.path.basename(image_path), f, 'image/jpeg')}
            data = {'overwrite': 'true', 'subfolder': ''}
            response = requests.post(f"http://{server_address}/upload/image", files=files, data=data)

        if response.status_code != 200:
            print(f"Error uploading image: {response.text}\n\n")
            return None

        upload_response = response.json()
        uploaded_filenames.append(upload_response['name'])
        print(f"Image uploaded as: {upload_response['name']}\n\n")

    # 2. Load and update the workflow
    with open(workflow_path, 'r', encoding='utf-8') as f:
        workflow = json.load(f)

    # Find the correct nodes dynamically
    text_node = find_node_by_class(workflow, "CLIPTextEncode") or find_node_by_class(workflow, "TextEncodeQwenImageEdit") or find_node_by_class(workflow, "PrimitiveStringMultiline") or find_node_by_class(workflow, "TextEncodeQwenImageEditPlus")
    if neg_prompt_text:
        neg_prompt_text_node = find_node_by_class(workflow, "CLIPTextEncode", neg_text=True)
    ksampler_node = find_node_by_class(workflow, "KSampler")
    basicscheduler_node = find_node_by_class(workflow, "BasicScheduler")
    seed_node = find_node_by_class(workflow, "RandomNoise") or find_node_by_class(workflow, "KSampler")
    save_node = find_node_by_class(workflow, "SaveImage")
    upscaler_node = find_node_by_class(workflow, "UltimateSDUpscale")
    denoise_node = find_node_by_class(workflow, "BasicScheduler") or find_node_by_class(workflow, "KSampler")

    if flags.get('chngsmp'):
        update_sampler(workflow, ksampler_node)

    # Update prompt text
    update_prompt_text(workflow, text_node, prompt_text, 
                      neg_prompt_text_node if neg_prompt_text else None, neg_prompt_text)

    # Update steps/cfg
    update_sampling_params(workflow, ksampler_node, basicscheduler_node, flags or {})

    # Update seed
    seed_val = update_seed(workflow, seed_node, upscaler_node, flags or {})

    # Update denoise parameters
    update_denoise(workflow, denoise_node, upscaler_node, flags or {})

    # Update resolution if provided
    update_resolution(workflow, resize_resolution, allow_resize)

    # Update ControlNet switch if flags are present
    update_controlnet_switch(workflow, flags or {})    

    # Handle image assignment to LoadImage nodes
    if uploaded_filenames:
        if len(uploaded_filenames) > 1:
            # Multi-image workflow - find LoadImage nodes by title
            load_image_nodes = find_load_image_nodes_by_title(workflow)
            
            # Map images to the numbered LoadImage nodes
            title_mappings = [
                "Load Image 1",
                "Load Image 2", 
                "Load Image 3",
                "Load Image 4"
            ]
            
            for i, filename in enumerate(uploaded_filenames):
                if i < len(title_mappings):
                    title = title_mappings[i]
                    if title in load_image_nodes:
                        node_id = load_image_nodes[title]
                        workflow[node_id]["inputs"]["image"] = filename
                        print(f"Assigned {filename} to {title} (node {node_id})\n\n")
        else:
            # Single image workflow (existing logic)
            load_image_node = find_node_by_class(workflow, "LoadImage")
            if load_image_node:
                workflow[load_image_node]["inputs"]["image"] = uploaded_filenames[0]

    # 3. Queue the prompt
    prompt_payload = {"prompt": workflow, "client_id": client_id}
    headers = {'Content-Type': 'application/json'}
    response = requests.post(f"http://{server_address}/prompt", data=json.dumps(prompt_payload), headers=headers)

    if response.status_code != 200:
        print(f"Error queueing prompt: {response.text}\n\n")
        return None
    
    queue_response = response.json()
    prompt_id = queue_response['prompt_id']
    print(f"Prompt queued with ID: {prompt_id}\n\n")

    # 4. Wait for execution and get the result via WebSocket
    ws_url = f"ws://{server_address}/ws?clientId={client_id}"
    ws = websocket.WebSocket()
    ws.connect(ws_url)

    final_image_path = None
    print("Waiting for image generation...\n\n")
    try:
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if (message.get('type') == 'executing' and message.get('data', {}).get('node') is None) or (message.get('type') == 'executed' and message.get('data', {}).get('prompt_id') == prompt_id and message.get('data', {}).get('node') is None):
                    if message.get('data', {}).get('prompt_id') == prompt_id:
                        print("Execution finished.\n\n")
                        break # Execution is done for our prompt
            else:
                # This is binary data for a preview image, we can ignore it
                continue
    finally:
        ws.close()

    # 5. Retrieve the output image from history    
    history_url = f"http://{server_address}/history/{prompt_id}"
    for attempt in range(5):
        with urllib.request.urlopen(history_url) as response:
            history = json.loads(response.read())
        if history and prompt_id in history:
            break
        else:
            print('History not found, retrying...')
            time.sleep(1)

    if prompt_id not in history:
        print("Prompt ID not found in history.\n\n")
        return None, None, None, None

    prompt_history = history[prompt_id]

    # Calculate duration using your existing function
    duration = get_duration_from_history(prompt_history)
    if duration:
        print(f"Generation took: {duration:.1f} seconds\n\n")
    
    outputs = prompt_history.get('outputs', {})
    
    # Find the output from the SaveImage node
    if save_node and 'images' in outputs.get(save_node, {}):
        image_info = outputs[save_node]['images'][0]
        filename = image_info['filename']
        subfolder = image_info['subfolder']
        img_type = image_info['type']

        # Get image data
        image_data_url = f"http://{server_address}/view?filename={urllib.parse.quote_plus(filename)}&subfolder={urllib.parse.quote_plus(subfolder)}&type={img_type}"
        with urllib.request.urlopen(image_data_url) as response:
            image_data = response.read()

        # Save the image
        os.makedirs(output_dir, exist_ok=True)
        final_image_path = os.path.join(output_dir, filename)
        with open(final_image_path, 'wb') as f:
            f.write(image_data)
        
        print(f"Image saved to: {final_image_path}\n\n")
        return os.path.abspath(final_image_path), duration, seed_val, prompt_id
    else:
        print("Output image not found in history.\n\n")
        return None, None, None, None
    

def update_sampler(workflow, node_id):
    """
    Update the sampler type for the given node in the workflow.
    """
    if node_id in workflow:
        workflow[node_id]['inputs']['sampler_name'] = 'dpmpp_2m'
        workflow[node_id]['inputs']['scheduler'] = 'karras'
    else:
        print(f"Node ID {node_id} not found in workflow.")


def _set_resize(workflow, node_id, width, height, allow_resize=False):
    """
    Set the resize value for the prompt.
    Returns a string in the format 'widthxheight'.
    """
    try:
        if (width > 1920 or height > 1080) and not allow_resize:
            workflow[node_id]['inputs']['width'] = 1024
            workflow[node_id]['inputs']['height'] = 1024
        else:
            workflow[node_id]['inputs']['width'] = width
            workflow[node_id]['inputs']['height'] = height
    except Exception as e:
        print(f"Invalid width value: {width}")
        print(f"Error: {e}")



def set_resize(workflow, node_id, width, height, allow_resize=False):
    """
    Set the resize value for the prompt.
    Applies aspect ratio-based resolution limits.
    """
    try:
        if allow_resize:
            # Skip limits for specific users
            workflow[node_id]['inputs']['width'] = width
            workflow[node_id]['inputs']['height'] = height
            return
        
        # Calculate aspect ratio
        aspect_ratio = width / height
        
        # Check aspect ratio and apply appropriate limits
        # Square aspect ratio (1:1) - allow up to 1400x1400
        if 0.9 <= aspect_ratio <= 1.1:  # Allow some tolerance for square
            if width > 1400 or height > 1400:
                workflow[node_id]['inputs']['width'] = 1024
                workflow[node_id]['inputs']['height'] = 1024
                print(f"Resolution {width}x{height} exceeds square limit (1400x1400), using 1024x1024")
            else:
                workflow[node_id]['inputs']['width'] = width
                workflow[node_id]['inputs']['height'] = height
        # Landscape aspect ratio - allow up to 1920x1080
        elif aspect_ratio > 1.1:
            if width > 1920 or height > 1080:
                workflow[node_id]['inputs']['width'] = 1024
                workflow[node_id]['inputs']['height'] = 1024
                print(f"Resolution {width}x{height} exceeds landscape limit (1920x1080), using 1024x1024")
            else:
                workflow[node_id]['inputs']['width'] = width
                workflow[node_id]['inputs']['height'] = height
        # Portrait aspect ratio - allow up to 1080x1920
        else:  # aspect_ratio < 0.9
            if width > 1080 or height > 1920:
                workflow[node_id]['inputs']['width'] = 1024
                workflow[node_id]['inputs']['height'] = 1024
                print(f"Resolution {width}x{height} exceeds portrait limit (1080x1920), using 1024x1024")
            else:
                workflow[node_id]['inputs']['width'] = width
                workflow[node_id]['inputs']['height'] = height
                
    except Exception as e:
        print(f"Invalid width/height values: {width}x{height}")
        print(f"Error: {e}")
        # Set defaults on error
        workflow[node_id]['inputs']['width'] = 1024
        workflow[node_id]['inputs']['height'] = 1024

        


def handle_resize(value):
    """
    Handle the resize value from the prompt.
    Returns a tuple of (width, height) or None if invalid.
    """
    if value:
        try:
            width, height = map(int, value.split('x'))
            return width, height
        except ValueError:
            print(f"Invalid resize value: {value}")
            return None
    return None

def is_any_job_running(server_address="127.0.0.1:8001"):
    """
    Returns True if there is any pending or executing job in the ComfyUI queue.
    """
    try:
        response = requests.get(f"http://{server_address}/queue")
        if response.status_code != 200:
            return False
        queue = response.json()
        # Check if there are any jobs in 'pending' or 'executing'
        if queue.get("queue_running") or queue.get("queue_pending"):
            return True
        return False
    except Exception as e:
        print(f"Error checking ComfyUI queue: {e}")
        return False

def get_pending_job_count(server_address="127.0.0.1:8001"):
    """
    Returns the number of pending jobs in the ComfyUI queue.
    """
    try:
        response = requests.get(f"http://{server_address}/queue")
        if response.status_code != 200:
            return 0
        queue = response.json()
        q_length=len(queue.get("queue_pending", []))
        return q_length+1 if q_length > 0 else 1
    except Exception as e:
        print(f"Error checking ComfyUI queue: {e}")
        return 0
    

def get_duration_from_history(prompt_history):
    """Calculate generation duration from prompt history data."""
    status_messages = prompt_history.get('status', {}).get('messages', [])
    start_time = None
    end_time = None
    
    for message in status_messages:
        if message[0] == 'execution_start':
            start_time = message[1]['timestamp']
        elif message[0] == 'execution_success':
            end_time = message[1]['timestamp']
    
    if start_time and end_time:
        return (end_time - start_time) / 1000  # Convert ms to seconds
    
    return None

def update_prompt_text(workflow, text_node, prompt_text, neg_prompt_text_node=None, neg_prompt_text=None):
    """Update the prompt text in the workflow."""
    if text_node:
        # Check if the node has 'text' or 'prompt' input field
        if "text" in workflow[text_node]["inputs"]:
            workflow[text_node]["inputs"]["text"] = prompt_text
        elif "prompt" in workflow[text_node]["inputs"]:
            workflow[text_node]["inputs"]["prompt"] = prompt_text
        elif "value" in workflow[text_node]["inputs"]:  # For PrimitiveStringMultiline
            workflow[text_node]["inputs"]["value"] = prompt_text
        else:
            print(f"Warning: Node {text_node} doesn't have 'text' or 'prompt' input field")
     
    if neg_prompt_text and neg_prompt_text_node:
        workflow[neg_prompt_text_node]["inputs"]["text"] = neg_prompt_text

def update_sampling_params(workflow, ksampler_node, basicscheduler_node, flags):
    """Update steps and cfg parameters in the workflow."""
    if flags.get('steps') is not None:
        if ksampler_node and "steps" in workflow[ksampler_node]["inputs"]:
            workflow[ksampler_node]["inputs"]["steps"] = flags['steps']
        elif basicscheduler_node and "steps" in workflow[basicscheduler_node]["inputs"]:
            workflow[basicscheduler_node]["inputs"]["steps"] = flags['steps']
    
    if flags.get('cfg') is not None and ksampler_node and "cfg" in workflow[ksampler_node]["inputs"]:
        workflow[ksampler_node]["inputs"]["cfg"] = flags['cfg']

def update_seed(workflow, seed_node, upscaler_node, flags):
    """Update seed values in the workflow. Returns the seed value used."""
    seed_val = None
    if not seed_node:
        return seed_val

    if "noise_seed" in workflow[seed_node]["inputs"]:
        if flags.get('seed') is not None:
            workflow[seed_node]["inputs"]["noise_seed"] = flags['seed']
            seed_val = workflow[seed_node]["inputs"]["noise_seed"]
        else:
            workflow[seed_node]["inputs"]["noise_seed"] = random.randint(0, 2**53 - 1)
            seed_val = workflow[seed_node]["inputs"]["noise_seed"]
        
        if upscaler_node and flags.get('seed') is not None:
            workflow[upscaler_node]["inputs"]["seed"] = seed_val
    
    elif "seed" in workflow[seed_node]["inputs"]:
        if flags.get('seed') is not None:
            workflow[seed_node]["inputs"]["seed"] = flags['seed']
            seed_val = workflow[seed_node]["inputs"]["seed"]
        else:
            workflow[seed_node]["inputs"]["seed"] = random.randint(0, 2**53 - 1)
            seed_val = workflow[seed_node]["inputs"]["seed"]
    
    return seed_val

def update_denoise(workflow, denoise_node, upscaler_node, flags):
    """Update denoise parameters in the workflow."""
    if flags.get('seednoise') is not None and denoise_node:
        workflow[denoise_node]["inputs"]["denoise"] = flags['seednoise']

    if upscaler_node and flags.get('upscale_noise') is not None:
        workflow[upscaler_node]["inputs"]["denoise"] = flags['upscale_noise']

def update_resolution(workflow, resize_resolution, allow_resize=False):
    """Update resolution parameters in the workflow."""
    if not resize_resolution:
        return
    
    width, height = handle_resize(resize_resolution)
    if not (width and height):
        return

    for node_type in ["EmptyHunyuanLatentVideo", "EmptySD3LatentImage", "EmptyLatentImage"]:
        if node_type in str(workflow):
            resize_node = find_node_by_class(workflow, node_type)
            if resize_node:
                set_resize(workflow=workflow, node_id=resize_node, 
                         width=width, height=height, allow_resize=allow_resize)
                break


def generate_audio(
    audio_path: str,
    prompt_text: str,
    workflow_path: str,
    server_address: str,
    flags: dict = None
):
    """
    Generate audio using VibeVoice workflow.
    """
    client_id = str(uuid.uuid4())
    if flags is None:
        flags = {}
    
    try:
        # 1. Instead of uploading, we'll use the local file path directly
        # ComfyUI LoadAudio nodes typically work with absolute file paths
        print("Preparing audio file for ComfyUI...\n\n")
        
        # Convert to absolute path
        abs_audio_path = os.path.abspath(audio_path)
        print(f"Using audio file: {abs_audio_path}\n\n")

        # 2. Load the workflow
        with open(workflow_path, 'r') as f:
            workflow = json.load(f)
        
        # Find nodes dynamically using the existing function
        load_audio_node = find_node_by_class(workflow, "LoadAudio")
        string_multiline_node = find_node_by_class(workflow, "PrimitiveStringMultiline")
        vibevoice_node = find_node_by_class(workflow, "VibeVoiceMultipleSpeakersNode")
        save_audio_node = find_node_by_class(workflow, "SaveAudio")
        
        # Set the absolute audio file path in LoadAudio node
        if load_audio_node:
            workflow[load_audio_node]["inputs"]["audio"] = abs_audio_path
            print(f"Set LoadAudio node ({load_audio_node}) audio input to: {abs_audio_path}\n\n")
        else:
            raise Exception("LoadAudio node not found in workflow")
        
        # Set the text in PrimitiveStringMultiline node
        if string_multiline_node:
            workflow[string_multiline_node]["inputs"]["value"] = prompt_text
            print(f"Set text input to: {prompt_text}\n\n")
        else:
            raise Exception("PrimitiveStringMultiline node not found in workflow")
        
        # Set other parameters from flags if provided and track the seed used
        seed_val = None
        if vibevoice_node:
            if flags.get('seed'):
                # Ensure user-provided seed is within valid range
                user_seed = flags['seed']
                if user_seed > 4294967295:
                    user_seed = user_seed % 4294967295
                workflow[vibevoice_node]["inputs"]["seed"] = user_seed
                seed_val = user_seed
            else:
                # Generate random seed within valid range for audio workflows
                generated_seed = random.randint(0, 4294967295)
                workflow[vibevoice_node]["inputs"]["seed"] = generated_seed
                seed_val = generated_seed
            
            if flags.get('cfg'):
                workflow[vibevoice_node]["inputs"]["cfg_scale"] = flags['cfg']
            if flags.get('steps'):
                workflow[vibevoice_node]["inputs"]["diffusion_steps"] = flags['steps']
            if flags.get('temperature'):
                workflow[vibevoice_node]["inputs"]["temperature"] = flags['temperature']
            if flags.get('top_p'):
                workflow[vibevoice_node]["inputs"]["top_p"] = flags['top_p']
            print(f"Configured VibeVoice node ({vibevoice_node}) with seed: {seed_val}\n\n")
        else:
            print("Warning: VibeVoiceMultipleSpeakersNode not found in workflow")
        
        # Debug: Print the final workflow configuration for the LoadAudio node
        if load_audio_node:
            print(f"LoadAudio node configuration: {workflow[load_audio_node]['inputs']}\n\n")
        
        # 3. Queue the workflow
        ws = websocket.WebSocket()
        ws.connect(f"ws://{server_address}/ws?clientId={client_id}")
        
        start_time = time.time()
        
        prompt_payload = {"prompt": workflow, "client_id": client_id}
        headers = {'Content-Type': 'application/json'}
        response = requests.post(f"http://{server_address}/prompt", data=json.dumps(prompt_payload), headers=headers)
        
        if response.status_code != 200:
            print(f"Queue response: {response.text}\n\n")
            raise Exception(f"Failed to queue workflow: {response.text}")
        
        prompt_id = response.json()['prompt_id']
        print(f"Audio prompt queued with ID: {prompt_id}\n\n")
        
        # 4. Wait for completion and get the output
        print("Waiting for audio generation...\n\n")
        try:
            while True:
                out = ws.recv()
                if isinstance(out, str):
                    message = json.loads(out)
                    if message.get('type') == 'executing':
                        data = message.get('data', {})
                        if data.get('node') is None and data.get('prompt_id') == prompt_id:
                            print("Audio generation finished.\n\n")
                            break # Execution is done for our prompt
                        elif data.get('node') is not None:
                            print(f"Executing node: {data.get('node')}")
                    elif message.get('type') == 'execution_error':
                        print(f"Execution error: {message}")
                        raise Exception(f"Workflow execution failed: {message}")
                else:
                    continue
        finally:
            ws.close()
        
        # 5. Get the generated audio file from history
        history_url = f"http://{server_address}/history/{prompt_id}"
        for attempt in range(5):
            with urllib.request.urlopen(history_url) as response:
                history = json.loads(response.read())
            if history and prompt_id in history:
                break
            else:
                print('History not found, retrying...')
                time.sleep(1)

        if prompt_id not in history:
            raise Exception("Prompt ID not found in history.")

        history_data = history[prompt_id]
        print(f"History data: {json.dumps(history_data, indent=2)}\n\n")
        
        # Calculate duration using existing function
        duration = get_duration_from_history(history_data)
        if duration:
            print(f"Audio generation took: {duration:.1f} seconds\n\n")
        else:
            end_time = time.time()
            duration = end_time - start_time
        
        outputs = history_data.get('outputs', {})
        print(f"Available outputs: {list(outputs.keys())}\n\n")
        
        # Find the SaveAudio node output using the node ID we found
        output_audio = None
        if save_audio_node and save_audio_node in outputs:
            node_output = outputs[save_audio_node]
            print(f"SaveAudio node output: {node_output}\n\n")
            if 'audio' in node_output:
                for audio_info in node_output['audio']:
                    filename = audio_info['filename']
                    subfolder = audio_info.get('subfolder', '')
                    
                    # Download the audio file
                    audio_url = f"http://{server_address}/view?filename={urllib.parse.quote_plus(filename)}&subfolder={urllib.parse.quote_plus(subfolder)}&type=output"
                    print(f"Attempting to download from: {audio_url}\n\n")
                    audio_response = requests.get(audio_url)
                    
                    if audio_response.status_code == 200:
                        # Save to output directory
                        os.makedirs("output", exist_ok=True)
                        output_path = os.path.join("output", filename)
                        with open(output_path, 'wb') as f:
                            f.write(audio_response.content)
                        
                        output_audio = os.path.abspath(output_path)
                        print(f"Audio saved to: {output_audio}\n\n")
                        break
                    else:
                        print(f"Failed to download audio: {audio_response.status_code} - {audio_response.text}")
        
        # Fallback: search all outputs for audio files if direct lookup failed
        if not output_audio:
            print("Searching all outputs for audio files...\n\n")
            for node_id in outputs:
                node_output = outputs[node_id]
                print(f"Checking node {node_id}: {node_output}\n\n")
                if 'audio' in node_output:
                    for audio_info in node_output['audio']:
                        filename = audio_info['filename']
                        subfolder = audio_info.get('subfolder', '')
                        
                        # Download the audio file
                        audio_url = f"http://{server_address}/view?filename={urllib.parse.quote_plus(filename)}&subfolder={urllib.parse.quote_plus(subfolder)}&type=output"
                        print(f"Attempting to download from: {audio_url}\n\n")
                        audio_response = requests.get(audio_url)
                        
                        if audio_response.status_code == 200:
                            # Save to output directory
                            os.makedirs("output", exist_ok=True)
                            output_path = os.path.join("output", filename)
                            with open(output_path, 'wb') as f:
                                f.write(audio_response.content)
                            
                            output_audio = os.path.abspath(output_path)
                            print(f"Audio saved to: {output_audio}\n\n")
                            break
                        else:
                            print(f"Failed to download audio: {audio_response.status_code} - {audio_response.text}")
                
                if output_audio:
                    break
        
        if not output_audio:
            raise Exception("No audio output found in workflow results")
        
        return output_audio, duration, seed_val, prompt_id
        
    except Exception as e:
        print(f"Error in generate_audio: {e}")
        raise e
    


def update_controlnet_switch(workflow, flags):
    """Update ControlNet switch based on flags."""
    # Find the Switch any [Crystools] node for ControlNet
    switch_node = None
    for node_id, node_data in workflow.items():
        if (node_data.get('class_type') == 'Switch any [Crystools]' and
            'TRUE ---> OPENPOSE     FALSE ---> DEPTH' in node_data.get('_meta', {}).get('title', '')):
            switch_node = node_id
            break
    
    if switch_node:
        if flags.get('cnopenpose'):
            workflow[switch_node]["inputs"]["boolean"] = True
            print(f"Set ControlNet to OPENPOSE mode (boolean=True)")
        elif flags.get('cndepth'):
            workflow[switch_node]["inputs"]["boolean"] = False
            print(f"Set ControlNet to DEPTH mode (boolean=False)")
        else:
            # Default behavior - you can set a default here
            print(f"No ControlNet flag specified, using default")
    else:
        print("Warning: ControlNet Switch node not found in workflow")


def extract_comfyui_output_files(history_data, comfyui_output_dir="D:\\Repos\\ComfyUI_venv\\ComfyUI\\output"):
    """
    Extract output file paths from ComfyUI history data.
    
    Args:
        history_data: The history data from ComfyUI API
        comfyui_output_dir: Path to ComfyUI output directory
    
    Returns:
        list: List of absolute file paths to delete
    """
    files_to_delete = []
    
    outputs = history_data.get('outputs', {})
    
    for node_id, node_output in outputs.items():
        # Handle image outputs
        if 'images' in node_output:
            for image_info in node_output['images']:
                filename = image_info['filename']
                subfolder = image_info.get('subfolder', '')
                img_type = image_info.get('type', 'output')
                
                if img_type == 'output':  # Only delete actual output files, not temp files
                    if subfolder:
                        file_path = os.path.join(comfyui_output_dir, subfolder, filename)
                    else:
                        file_path = os.path.join(comfyui_output_dir, filename)
                    files_to_delete.append(file_path)
        
        # Handle audio outputs
        if 'audio' in node_output:
            for audio_info in node_output['audio']:
                filename = audio_info['filename']
                subfolder = audio_info.get('subfolder', '')
                audio_type = audio_info.get('type', 'output')
                
                if audio_type == 'output':  # Only delete actual output files, not temp files
                    if subfolder:
                        file_path = os.path.join(comfyui_output_dir, subfolder, filename)
                    else:
                        file_path = os.path.join(comfyui_output_dir, filename)
                    files_to_delete.append(file_path)
    
    return files_to_delete

def delete_comfyui_files(file_paths):
    """
    Delete files from ComfyUI output directory.
    
    Args:
        file_paths: List of file paths to delete
    """
    deleted_files = []
    failed_files = []
    
    for file_path in file_paths:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                deleted_files.append(file_path)
                print(f"Deleted ComfyUI output file: {file_path}")
            else:
                print(f"File not found (already deleted?): {file_path}")
        except Exception as e:
            failed_files.append((file_path, str(e)))
            print(f"Failed to delete {file_path}: {e}")
    
    if deleted_files:
        print(f"Successfully deleted {len(deleted_files)} ComfyUI output files")
    if failed_files:
        print(f"Failed to delete {len(failed_files)} files")
    
    return deleted_files, failed_files

def cleanup_comfyui_outputs(prompt_id, server_address, comfyui_output_dir="D:\\Repos\\ComfyUI_venv\\ComfyUI\\output", comfyui_input_dir="D:\\Repos\\ComfyUI_venv\\ComfyUI\\input"):
    """
    Clean up ComfyUI output files for a given prompt ID.
    
    Args:
        prompt_id: The ComfyUI prompt ID
        server_address: ComfyUI server address
        comfyui_output_dir: Path to ComfyUI output directory
    """
    try:
        # Get history from ComfyUI
        history_url = f"http://{server_address}/history/{prompt_id}"
        with urllib.request.urlopen(history_url) as response:
            history = json.loads(response.read())
        
        if prompt_id not in history:
            print(f"Prompt ID {prompt_id} not found in history for cleanup")
            return
        
        history_data = history[prompt_id]
        
        # Extract output files
        files_to_delete = extract_comfyui_output_files(history_data, comfyui_output_dir)
        files_to_delete.extend(extract_comfyui_output_files(history_data, comfyui_input_dir))
        
        if files_to_delete:
            print(f"Found {len(files_to_delete)} ComfyUI output files to delete")
            # Delete the files
            delete_comfyui_files(files_to_delete)
        else:
            print("No ComfyUI output files found to delete")
            
    except Exception as e:
        print(f"Error during ComfyUI cleanup: {e}")

