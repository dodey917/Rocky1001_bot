import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ALLOWED_USER_IDS = [uid.strip() for uid in os.environ.get('ALLOWED_USER_IDS', '').split(',') if uid.strip()]
ALLOWED_USERNAMES = [uname.strip().lstrip('@').lower() for uname in os.environ.get('ALLOWED_USERNAMES', '').split(',') if uname.strip()]

def is_user_authorized(user_id: int, username: str) -> bool:
    """
    Check if user is authorized to use the bot
    """
    # Clean and prepare the username
    clean_username = username.lstrip('@').lower() if username else ""
    
    # Check if user ID is in allowed list
    if str(user_id) in ALLOWED_USER_IDS:
        logger.info(f"User authorized by ID: {user_id}")
        return True
    
    # Check if username is in allowed list
    if clean_username and clean_username in ALLOWED_USERNAMES:
        logger.info(f"User authorized by username: {clean_username}")
        return True
    
    logger.warning(f"Unauthorized access - User ID: {user_id}, Username: {username}")
    return False

async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is authorized and send message if not"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "No username"
    
    if not is_user_authorized(user_id, username):
        await update.message.reply_text(
            "❌ Unauthorized access. This bot is not available for public use."
        )
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    # Check authorization first
    if not await check_authorization(update, context):
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username
    
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
    # Check authorization first
    if not await check_authorization(update, context):
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
    # Check authorization first
    if not await check_authorization(update, context):
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
    # Check authorization first
    if not await check_authorization(update, context):
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
    # Check authorization first
    if not await check_authorization(update, context):
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
    # Check authorization first
    if not await check_authorization(update, context):
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
    # Check authorization first
    if not await check_authorization(update, context):
        return
    
    # Process the message for authorized users only
    user_message = update.message.text
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    logger.info(f"Authorized user message - User: {username} ({user_id}): {user_message}")
    
    response_text = "Thank you for your message! We'll get back to you soon. 🧹"
    await update.message.reply_text(response_text)

async def handle_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all unauthorized access attempts."""
    user_id = update.effective_user.id
    username = update.effective_user.username or "No username"
    
    logger.warning(f"BLOCKED unauthorized access - User ID: {user_id}, Username: {username}")
    
    # Do not respond at all to unauthorized users
    # This prevents them from knowing the bot exists
    return

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
    
    if not ALLOWED_USER_IDS and not ALLOWED_USERNAMES:
        logger.warning("No authorized users configured! Bot will reject all users.")
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers for authorized commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("services", services))
    application.add_handler(CommandHandler("contact", contact))
    application.add_handler(CommandHandler("quote", quote))
    application.add_handler(CommandHandler("book", book))
    
    # Handle messages from authorized users
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add a catch-all handler for unauthorized users that does nothing
    # This prevents any response to unauthorized users
    application.add_handler(MessageHandler(filters.ALL, handle_unauthorized), group=1)
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the Bot
    logger.info("Bot is starting with strict authorization...")
    application.run_polling()

if __name__ == '__main__':
    main()
