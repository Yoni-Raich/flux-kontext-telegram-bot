import websocket
import uuid
import json
import urllib.request
import urllib.parse
import requests
import os
import random

def find_node_by_class(workflow, class_type):
    for node_id, node in workflow.items():
        if node.get("class_type") == class_type:
            return node_id
    return None

def generate_image(prompt_text: str, workflow_path: str, server_address="127.0.0.1:8001", output_dir="output",image_path=None):
    """
    Generates an image using a ComfyUI workflow.

    Args:
        image_path (str): Path to the input image.
        prompt_text (str): The text prompt.
        workflow_path (str): Path to the ComfyUI workflow JSON file.
        server_address (str, optional): The address of the ComfyUI server. Defaults to "127.0.0.1:8001".
        output_dir (str, optional): Directory to save the output image. Defaults to "output".

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
    with open(workflow_path, 'r') as f:
        workflow = json.load(f)

    # Find the correct nodes dynamically
    text_node = find_node_by_class(workflow, "CLIPTextEncode")
    seed_node = find_node_by_class(workflow, "RandomNoise") or find_node_by_class(workflow, "KSampler")
    save_node = find_node_by_class(workflow, "SaveImage")

    # Update prompt text
    if text_node:
        workflow[text_node]["inputs"]["text"] = prompt_text

    # Update seed for randomness
    if seed_node:
        # Try both possible keys for seed
        if "noise_seed" in workflow[seed_node]["inputs"]:
            workflow[seed_node]["inputs"]["noise_seed"] = random.randint(0, 2**64 - 1)
        elif "seed" in workflow[seed_node]["inputs"]:
            workflow[seed_node]["inputs"]["seed"] = random.randint(0, 2**64 - 1)

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
                if message.get('type') == 'executing' and message.get('data', {}).get('node') is None:
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
    with urllib.request.urlopen(history_url) as response:
        history = json.loads(response.read())

    if prompt_id not in history:
        print("Prompt ID not found in history.\n\n")
        return None

    prompt_history = history[prompt_id]
    outputs = prompt_history.get('outputs', {})
    
    # Find the output from the SaveImage node (9)
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
        return os.path.abspath(final_image_path)
    else:
        print("Output image not found in history.\n\n")
        return None

if __name__ == '__main__':
    # Create a dummy image for testing if it doesn't exist
    if not os.path.exists("input_image.png"):
        try:
            from PIL import Image
            img = Image.new('RGB', (1024, 1024), color = 'red')
            img.save('input_image.png')
            print("Created a dummy input_image.png\n\n")
        except ImportError:
            print("Please create an 'input_image.png' file or install Pillow (pip install Pillow) to create one automatically.\n\n")
            exit(1)


    image_file = "input_image.png"
    prompt = "A majestic cat sitting on a throne, cinematic lighting"
    workflow_file = os.path.join("workflows", "flux_kontext_workflow.json")

    if not os.path.exists(image_file):
        print(f"Error: Input image '{image_file}' not found.")
    elif not os.path.exists(workflow_file):
        print(f"Error: Workflow '{workflow_file}' not found.")
    else:
        generated_image_path = generate_image(image_file, prompt, workflow_file)
        if generated_image_path:
            print(f"\\nSuccessfully generated image: {generated_image_path}")
        else:
            print("\\nFailed to generate image.")