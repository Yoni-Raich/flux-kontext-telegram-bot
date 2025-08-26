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

def generate_image(prompt_text: str, 
                   workflow_path: str, 
                   server_address="127.0.0.1:8001", 
                   output_dir="output", 
                   image_path=None, 
                   flags=None, 
                   fast_film_grain=False, 
                   neg_prompt_text=None, 
                   resize_resolution=None,
                   allow_resize=False):
    """
    Generates an image using a ComfyUI workflow.

    Args:
        image_path (str): Path to the input image.
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
    
    if image_path:
        # 1. Upload the image
        print("Uploading image...\n\n")
        with open(image_path, 'rb') as f:
            files = {'image': (os.path.basename(image_path), f, 'image/jpeg')}
            data = {'overwrite': 'true', 'subfolder': ''}
            response = requests.post(f"http://{server_address}/upload/image", files=files, data=data)

        if response.status_code != 200:
            print(f"Error uploading image: {response.text}\n\n")
            return None

        upload_response = response.json()
        image_filename = upload_response['name']
        print(f"Image uploaded as: {image_filename}\n\n")

    # 2. Load and update the workflow
    with open(workflow_path, 'r', encoding='utf-8') as f:
        workflow = json.load(f)

    # Find the correct nodes dynamically
    text_node = find_node_by_class(workflow, "CLIPTextEncode") or find_node_by_class(workflow, "TextEncodeQwenImageEdit")
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


    # For image-to-image, update LoadImage node if present
    if image_path:
        load_image_node = find_node_by_class(workflow, "LoadImage")
        if load_image_node:
            workflow[load_image_node]["inputs"]["image"] = image_filename

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
        return None, None, None

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
        return os.path.abspath(final_image_path), duration, seed_val
    else:
        print("Output image not found in history.\n\n")
        return None, None, None
    

def update_sampler(workflow, node_id):
    """
    Update the sampler type for the given node in the workflow.
    """
    if node_id in workflow:
        workflow[node_id]['inputs']['sampler_name'] = 'dpmpp_2m'
        workflow[node_id]['inputs']['scheduler'] = 'karras'
    else:
        print(f"Node ID {node_id} not found in workflow.")


def set_resize(workflow, node_id, width, height, allow_resize=False):
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