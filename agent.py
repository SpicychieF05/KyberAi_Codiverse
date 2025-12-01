import json
import logging
import os
import aiosqlite
from typing import Final
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv
from multi_api_client import MultiAPIClient
from tech_news import tech_news_fetcher

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
TOKEN: Final[str] = os.getenv("TELEGRAM_BOT_TOKEN") or ""
BOT_USERNAME: Final = "@CodiverseBot"

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not found in environment variables")

# Initialize Multi-API Client
api_client = MultiAPIClient()

# Load Persona
try:
    with open("persona.json", "r") as f:
        PERSONA = json.load(f)
except FileNotFoundError:
    logger.error("persona.json not found!")
    PERSONA = {}

# Load FAQ Data
try:
    with open("faq_data.json", "r") as f:
        FAQ_DATA = json.load(f)
except FileNotFoundError:
    logger.error("faq_data.json not found!")
    FAQ_DATA = {}

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the bot and shows the main menu."""
    if not update.message:
        return
    
    user = update.effective_user
    user_name = user.first_name if user else "there"
    
    welcome_msg = (
        f"Hello {user_name}! 👋\n"
        f"I am Codiverse TechBot - Your Tech & Coding Assistant.\n\n"
        f"I can help you with:\n"
        f"💻 Coding help & debugging\n"
        f"📰 Latest tech news & trends\n"
        f"🔧 Tech troubleshooting\n"
        f"🚀 Development tips & best practices\n\n"
        f"What would you like to explore?"
    )
    
    reply_keyboard = [["📰 Tech News", "💻 Coding Help"], ["🔥 Trending", "❓ Help"]]
    
    await update.message.reply_text(
        welcome_msg,
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays help information."""
    if not update.message:
        return
    
    help_text = (
        "**🤖 Codiverse TechBot - Your Tech Companion**\n\n"
        "**📰 News Commands:**\n"
        "/news - Top tech news (Hacker News + RapidAPI)\n"
        "/news coding - Latest coding articles from DEV.to\n"
        "/news python - Python-specific news\n"
        "/news javascript - JavaScript news\n"
        "/news rapidapi - Tech news from RapidAPI\n"
        "/github - Trending GitHub repositories\n\n"
        "**💻 Coding Help:**\n"
        "Ask me about any programming language, debugging, or code review\n\n"
        "**🔥 Trending:**\n"
        "/trending - Hot topics in tech right now\n\n"
        "**Other Commands:**\n"
        "/stats - Bot usage statistics\n"
        "/help - Show this help message\n\n"
        "Just type your question or select from the menu!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin stats command"""
    if not update.message:
        return
    
    try:
        async with aiosqlite.connect('api_stats.db') as db:
            async with db.execute("SELECT provider, COUNT(*) as calls, AVG(response_time) as avg_time, SUM(success) as successes FROM usage GROUP BY provider") as cursor:
                rows = await cursor.fetchall()
                stats_text = "📊 API Usage Stats:\n\n"
                for provider, calls, avg_time, successes in rows:
                    success_rate = (successes/calls)*100 if calls else 0
                    stats_text += f"*{provider.title()}*: {calls} calls | {avg_time:.2f}s avg | {success_rate:.1f}% success\n"
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"Error fetching stats: {e}")

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches latest tech news"""
    if not update.message:
        return
    
    # Get category from command args or default to general
    category = " ".join(context.args) if context.args else "general"
    count = 10
    
    await update.message.reply_text(f"🔍 Fetching latest {category} news... Please wait.")
    
    try:
        news_items = await tech_news_fetcher.get_tech_news(category, count)
        message = tech_news_fetcher.format_news_message(news_items, category)
        await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        await update.message.reply_text("Sorry, I couldn't fetch the news right now. Please try again later.")

async def trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows trending repositories on GitHub"""
    if not update.message:
        return
    
    language = " ".join(context.args) if context.args else ""
    await update.message.reply_text(f"🔥 Fetching trending {'repositories' if not language else f'{language} projects'}... Please wait.")
    
    try:
        trending = await tech_news_fetcher.get_github_trending(language, 10)
        message = tech_news_fetcher.format_news_message(trending, f"Trending {language.title() if language else 'GitHub'}")
        await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error fetching trending: {e}")
        await update.message.reply_text("Sorry, I couldn't fetch trending repos right now. Please try again later.")

async def github_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows trending GitHub repositories"""
    await trending_command(update, context)

# --- General Message Handler ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles general messages using Multi-API Client with Failover."""
    if not update.message or not update.message.text or not update.effective_chat:
        return
    
    text = update.message.text
    session_id = str(update.effective_chat.id)
    
    if "website" in text.lower() and "visit" in text.lower():
         await update.message.reply_text("You can visit us at: https://codiverse-dev.vercel.app")
         return

    # Construct System Prompt
    system_prompt = f"""
    You are Codiverse TechBot, a tech and coding assistant.
    
    **Your Persona:**
    {json.dumps(PERSONA, indent=2)}
    
    **FAQ Knowledge Base:**
    {json.dumps(FAQ_DATA, indent=2)}
    
    **Instructions:**
    - Answer coding, tech, and development questions with precision and clarity.
    - Provide code examples when appropriate.
    - Explain technical concepts in an accessible way.
    - If the answer is not in your knowledge base, provide best practices or suggest resources.
    - Keep responses concise and well-formatted for Telegram chat.
    - For news requests, redirect to /news command.
    """
    
    # Combine system prompt and user message
    full_message = f"{system_prompt}\n\nUser Query: {text}"

    # Generate response using MultiAPIClient
    response, used_provider = await api_client.generate_response(session_id, full_message)
    
    # Check for provider switch notification
    ctx = api_client.session_context.get(session_id, {})
    prev_provider = ctx.get('last_provider')
    
    status_msg = ""
    # Only show switch message if we have a previous provider and it changed
    # Note: Logic in generate_response already updates last_provider, so we might need to track it before call if we want to be precise, 
    # but for now let's just show the provider used if debug needed or keep it clean.
    # The guide suggests showing it.
    
    # await update.message.reply_text(f"{response}\n\n(Generated by {used_provider})")
    await update.message.reply_text(response)

# --- Error Handler ---

async def error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.warning(f'Update "{update}" caused error "{context.error}"')


# --- Main Application ---

if __name__ == "__main__":
    print("Starting bot...")
    app = Application.builder().token(TOKEN).build()

    # Conversation Handler for New Project
    # Removed - No longer collecting project data
    
    # Conversation Handler for Status Check
    # Removed - No longer tracking status

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("trending", trending_command))
    app.add_handler(CommandHandler("github", github_command))
    
    # Button handlers for quick access
    app.add_handler(MessageHandler(filters.Regex("^📰 Tech News$"), lambda u, c: news_command(u, c)))
    app.add_handler(MessageHandler(filters.Regex("^🔥 Trending$"), lambda u, c: trending_command(u, c)))
    app.add_handler(MessageHandler(filters.Regex("^💻 Coding Help$"), lambda u, c: help_command(u, c)))

    # General Messages (Fallback)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Errors
    app.add_error_handler(error)

    # Polls the bot
    print("Polling...")
    app.run_polling(poll_interval=3)
