import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ALLOWED_USER_IDS = os.environ.get('ALLOWED_USER_IDS', '').split(',')
ALLOWED_USERNAMES = os.environ.get('ALLOWED_USERNAMES', '').split(',')
API_BASE_URL = os.environ.get('API_BASE_URL', 'http://localhost:5000')

def is_user_authorized(user_id: int, username: str) -> bool:
    """
    Check if user is authorized to use the bot
    """
    # Remove @ from username if present and convert to lowercase
    clean_username = username.lstrip('@').lower() if username else ""
    
    # Check if user ID is in allowed list
    if str(user_id) in ALLOWED_USER_IDS:
        return True
    
    # Check if username is in allowed list
    if clean_username and clean_username in [u.lstrip('@').lower() for u in ALLOWED_USERNAMES if u]:
        return True
    
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Check if user is authorized
    if not is_user_authorized(user_id, username):
        await update.message.reply_text(
            "❌ Unauthorized access. You are not allowed to use this bot."
        )
        logger.warning(f"Unauthorized access attempt from user_id: {user_id}, username: {username}")
        return
    
    welcome_text = """
🤖 Welcome to KMJ Universal Cleaning Bot!

I can help you with:
• Booking cleaning services
• Getting quotes
• Service information
• Contact details

Use /help to see all available commands.
    """
    await update.message.reply_text(welcome_text)
    logger.info(f"Authorized user started bot: user_id: {user_id}, username: {username}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Check if user is authorized
    if not is_user_authorized(user_id, username):
        await update.message.reply_text(
            "❌ Unauthorized access. You are not allowed to use this bot."
        )
        return
    
    help_text = """
📋 Available Commands:

/start - Start the bot
/help - Show this help message
/services - View our cleaning services
/quote - Get a free quote
/contact - Contact information
/book - Book a cleaning service
    """
    await update.message.reply_text(help_text)

async def services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available cleaning services."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Check if user is authorized
    if not is_user_authorized(user_id, username):
        await update.message.reply_text(
            "❌ Unauthorized access. You are not allowed to use this bot."
        )
        return
    
    services_text = """
🏠 Our Cleaning Services:

• Residential Cleaning
  - Deep cleaning
  - Regular maintenance
  - Move-in/out cleaning

• Commercial Cleaning
  - Office cleaning
  - Retail spaces
  - Industrial facilities

• Specialized Services
  - Carpet cleaning
  - Window washing
  - Post-construction cleaning

Use /quote to get a free estimate!
    """
    await update.message.reply_text(services_text)

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show contact information."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Check if user is authorized
    if not is_user_authorized(user_id, username):
        await update.message.reply_text(
            "❌ Unauthorized access. You are not allowed to use this bot."
        )
        return
    
    contact_text = """
📞 Contact KMJ Universal Cleaning:

Phone: +1 6209521146
Email: jamij54@gmail.com
Address: 7206 Bayview Circle, Manhattan, KS 66503

Business Hours:
Monday - Friday: 8:00 AM - 6:00 PM
Saturday: 9:00 AM - 2:00 PM

We're here to help! 🧹
    """
    await update.message.reply_text(contact_text)

async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the quote process."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Check if user is authorized
    if not is_user_authorized(user_id, username):
        await update.message.reply_text(
            "❌ Unauthorized access. You are not allowed to use this bot."
        )
        return
    
    quote_text = """
💰 Free Quote Request:

To get a personalized quote, please provide:
1. Type of service needed (residential/commercial/specialized)
2. Property size (sq ft)
3. Frequency (one-time/regular)
4. Any specific requirements

Please describe your cleaning needs and we'll get back to you with a quote within 24 hours!
    """
    await update.message.reply_text(quote_text)

async def book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the booking process."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Check if user is authorized
    if not is_user_authorized(user_id, username):
        await update.message.reply_text(
            "❌ Unauthorized access. You are not allowed to use this bot."
        )
        return
    
    book_text = """
📅 Book a Cleaning Service:

To schedule a cleaning service, please provide:
1. Preferred date and time
2. Service type
3. Property address
4. Contact information

We'll confirm your booking and send you all the details!
    """
    await update.message.reply_text(book_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all other messages."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Check if user is authorized
    if not is_user_authorized(user_id, username):
        await update.message.reply_text(
            "❌ Unauthorized access. You are not allowed to use this bot."
        )
        return
    
    # Process the message for authorized users
    user_message = update.message.text
    logger.info(f"Authorized user message - User: {username} ({user_id}): {user_message}")
    
    # You can add your message processing logic here
    response_text = f"Thank you for your message! We'll get back to you soon. 🧹"
    await update.message.reply_text(response_text)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and handle them appropriately."""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Only send error message to authorized users
    if update and update.effective_user:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if is_user_authorized(user_id, username):
            await update.message.reply_text(
                "❌ An error occurred. Please try again later."
            )

def main():
    """Start the bot."""
    # Check if required environment variables are set
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        return
    
    # Log authorized users for debugging
    logger.info(f"Allowed User IDs: {ALLOWED_USER_IDS}")
    logger.info(f"Allowed Usernames: {ALLOWED_USERNAMES}")
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("services", services))
    application.add_handler(CommandHandler("contact", contact))
    application.add_handler(CommandHandler("quote", quote))
    application.add_handler(CommandHandler("book", book))
    
    # Handle all other messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the Bot
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
