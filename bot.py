import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')  # Your Telegram ID for alerts

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class SimpleProtectionBot:
    def __init__(self):
        self.bad_words = [
            'fuck', 'shit', 'asshole', 'bitch', 'porn', 'nude', 'sex',
            'drugs', 'weed', 'cocaine', 'http://', 'https://', '.com'
        ]
    
    def check_message(self, text):
        """Check if message contains bad content"""
        if not text:
            return False, []
        
        text_lower = text.lower()
        found_words = []
        
        for word in self.bad_words:
            if word in text_lower:
                found_words.append(word)
        
        return len(found_words) > 0, found_words

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "🛡️ *Protection Bot Active*\n\n"
        "I'm protecting this group from spam and bad content.\n"
        "I will automatically delete inappropriate messages.",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await update.message.reply_text(
        "🤖 *Protection Bot Help*\n\n"
        "Commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help\n"
        "/status - Check bot status\n\n"
        "I automatically delete spam and inappropriate messages.",
        parse_mode='Markdown'
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    status_msg = (
        "🟢 *Bot Status: ACTIVE*\n\n"
        "✅ Protection: Enabled\n"
        "✅ Auto Delete: Enabled\n"
        "✅ Alert System: Active\n\n"
        f"Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all incoming messages"""
    message = update.message
    
    # Skip if message is from bot
    if message.from_user and message.from_user.is_bot:
        return
    
    bot = SimpleProtectionBot()
    
    # Check text message
    text_content = ""
    if message.text:
        text_content = message.text
    elif message.caption:
        text_content = message.caption
    
    # Check for bad content
    has_bad_content, found_words = bot.check_message(text_content)
    
    if has_bad_content:
        try:
            # Delete the bad message
            await message.delete()
            
            # Send alert to owner
            alert_msg = (
                f"🚨 *Security Alert*\n\n"
                f"Message deleted in: {message.chat.title}\n"
                f"User: @{message.from_user.username or 'No username'}\n"
                f"User ID: {message.from_user.id}\n"
                f"Bad words: {', '.join(found_words)}\n"
                f"Time: {datetime.now().strftime('%H:%M:%S')}"
            )
            
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=alert_msg,
                parse_mode='Markdown'
            )
            
            # Notify group about deletion
            warning_msg = (
                f"⚠️ Message from @{message.from_user.username or 'a user'} "
                f"was deleted for containing inappropriate content."
            )
            await message.chat.send_message(warning_msg)
            
        except Exception as e:
            logger.error(f"Error handling bad message: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Error: {context.error}")
    
    # Send error alert to owner
    try:
        error_msg = f"❌ Bot Error: {context.error}"
        await context.bot.send_message(chat_id=CHAT_ID, text=error_msg)
    except:
        pass

def main():
    """Start the bot"""
    print("🛡️ Starting Protection Bot...")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    
    # Add message handler
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    print("✅ Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
