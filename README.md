# ComfyUI Telegram Bot

A simple yet powerful Telegram bot that connects to a local ComfyUI server to generate new images from a user's photo and text prompt.

## Features

-   **Image-to-Image Generation**: Uses your input image and text prompt to create a new piece of art.
-   **Telegram Interface**: Interact with ComfyUI without leaving your favorite messaging app.
-   **Secure**: Includes an authorization system to ensure only approved users can access the bot.
-   **Easy to Configure**: All settings are managed in a single `config.py` file.

## Prerequisites

Before you begin, ensure you have the following set up:

1.  **Python 3.8+**: [Download Python](https://www.python.org/downloads/)
2.  **ComfyUI Server**:
    -   You must have a local instance of [ComfyUI](https://github.com/comfyanonymous/ComfyUI) installed.
    -   **Important**: Make sure your ComfyUI is up-to-date and is **running** before you start the bot.

## Installation & Setup

Follow these steps to get your bot up and running.

1.  **Clone the Repository:**
    ```bash
    git clone <your-repository-url>
    cd <your-repository-name>
    ```

2.  **Install Dependencies:**
    Create a virtual environment (recommended) and install the required Python packages.
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure the Bot:**
    -   Create a `config.py` file by copying the example file:
        ```bash
        # On Windows
        copy config.py.example config.py
        
        # On macOS/Linux
        cp config.py.example config.py
        ```
    -   Open `config.py` and fill in your details:
        -   `TELEGRAM_BOT_TOKEN`: Your bot's token from [@BotFather](https://t.me/BotFather).
        -   `AUTHORIZED_USER_IDS`: A list of Telegram User IDs that are allowed to use the bot. You can get your ID from [@userinfobot](https://t.me/userinfobot).
        -   `COMFYUI_SERVER_ADDRESS`: The address where your ComfyUI server is running (e.g., `"127.0.0.1:8188"`).

## How to Run

1.  **Start your ComfyUI server.**
2.  **Run the Telegram bot:**
    ```bash
    python main.py
    ```
    You should see a log message indicating that the bot has started polling for messages.

## Using the Bot

Once the bot is running, you can interact with it on Telegram:

-   **/start**: Displays a welcome message.
-   **/help**: Provides detailed instructions on how to use the bot.
-   **Send a Photo with a Caption**: This is the main function.
    1.  Attach an image to a message.
    2.  In the caption field, write a text prompt describing the transformation you want.
    3.  Send the message. The bot will process your request and send back the newly generated image. 