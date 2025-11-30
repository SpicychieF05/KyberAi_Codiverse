# DodoAi - Codiverse Telegram Chatbot

DodoAi is a smart support specialist bot for Codiverse on Telegram. It helps users start new projects, check project status, and answers general queries using AI.

## Features

- **AI-Powered Responses**: Uses OpenRouter (DeepSeek) to answer questions based on a custom persona and FAQ.
- **Lead Generation**: Collects user project details and saves them directly to Google Sheets.
- **Project Tracking**: Generates a unique Codiverse Member ID (CMID) for users to track their project status.

## Setup

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/SpicychieF05/DodoAi_Codiverse.git
    cd DodoAi_Codiverse
    ```

2.  **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment:**
    Create a `.env` file with the following keys:
    ```env
    TELEGRAM_BOT_TOKEN=your_telegram_bot_token
    OPENROUTER_API_KEY=your_openrouter_api_key
    GOOGLE_SHEETS_CREDENTIALS=your_base64_encoded_service_account_json
    LEADS_SHEETS_SPREADSHEET_ID=your_spreadsheet_id
    ```

## Usage

Run the bot:

```bash
python agent.py
```
