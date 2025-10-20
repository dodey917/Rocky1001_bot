import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import psycopg2

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')  # Your Telegram ID for alerts
DATABASE_URL = os.getenv('DATABASE_URL')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id SERIAL PRIMARY KEY,
                group_id BIGINT UNIQUE,
                group_name TEXT,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                group_id BIGINT,
                user_id BIGINT,
                username TEXT,
                message_text TEXT,
                message_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database error: {e}")

def save_group(chat_id, chat_title):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO groups (group_id, group_name) VALUES (%s, %s) ON CONFLICT (group_id) DO NOTHING",
            (chat_id, chat_title)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Save group error: {e}")

def save_message(chat_id, user_id, username, message_text):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (group_id, user_id, username, message_text) VALUES (%s, %s, %s, %s)",
            (chat_id, user_id, username, message_text[:500])  # Limit text length
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Save message error: {e}")

async def send_alert(context, message):
    """Send alert to owner"""
    try:
        alert_msg = f"🚨 New message in {message.chat.title}\n👤 User: @{message.from_user.username or 'No username'}\n💬 Message: {message.text[:100] if message.text else 'Media'}\n⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
        await context.bot.send_message(chat_id=CHAT_ID, text=alert_msg)
    except Exception as e:
        logger.error(f"Send alert error: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat = update.effective_chat
    
    # Save group info if it's a group
    if chat.type in ["group", "supergroup"]:
        save_group(chat.id, chat.title)
        await update.message.reply_text(
            "🛡️ Protection Bot Active!\n\n"
            "I'm now monitoring this group and will alert the owner of activities.\n\n"
            "Commands:\n"
            "/start - Show this message\n"
            "/status - Check bot status\n"
            "/scan - Scan messages\n"
            "/stats - Show statistics",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "🛡️ Protection Bot\n\n"
            "Add me to your group to start monitoring!",
            parse_mode='Markdown'
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    chat = update.effective_chat
    
    if chat.type in ["group", "supergroup"]:
        # Check if bot is admin in group
        try:
            bot_member = await chat.get_member(context.bot.id)
            is_admin = bot_member.status in ['administrator', 'creator']
            admin_status = "✅ Admin" if is_admin else "❌ Not Admin"
        except:
            admin_status = "❓ Unknown"
        
        status_msg = (
            f"🤖 Bot Status\n\n"
            f"🟢 Online\n"
            f"📊 Monitoring: Active\n"
            f"🔔 Alerts: Enabled\n"
            f"{admin_status}\n\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
    else:
        status_msg = "🤖 Bot is running and ready!"
    
    await update.message.reply_text(status_msg)

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /scan command"""
    chat = update.effective_chat
    
    if chat.type in ["group", "supergroup"]:
        try:
            await update.message.reply_text("🔍 Scanning recent messages...")
            
            # Get message count from database
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM messages WHERE group_id = %s", (chat.id,))
            message_count = cur.fetchone()[0]
            cur.close()
            conn.close()
            
            scan_result = (
                f"📊 Scan Results\n\n"
                f"📝 Messages logged: {message_count}\n"
                f"👥 Group: {chat.title}\n"
                f"✅ Scan completed!"
            )
            
            await update.message.reply_text(scan_result)
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
            await update.message.reply_text("❌ Scan failed!")
    else:
        await update.message.reply_text("This command works only in groups!")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM groups")
        group_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM messages")
        total_messages = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        stats_msg = (
            f"📈 Bot Statistics\n\n"
            f"👥 Groups: {group_count}\n"
            f"💬 Messages: {total_messages}\n"
            f"🕒 Last update: {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await update.message.reply_text(stats_msg)
        
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await update.message.reply_text("❌ Could not get statistics")

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all incoming messages in groups"""
    message = update.message
    
    if not message or not message.from_user:
        return
    
    # Skip bot messages
    if message.from_user.is_bot:
        return
    
    chat = update.effective_chat
    
    # Only process group messages
    if chat.type in ["group", "supergroup"]:
        # Save group info
        save_group(chat.id, chat.title)
        
        # Save message to database
        if message.text:
            save_message(chat.id, message.from_user.id, message.from_user.username, message.text)
            
            # Send alert for every message
            await send_alert(context, message)

async def handle_group_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bot being added to groups"""
    if update.message and update.message.new_chat_members:
        for user in update.message.new_chat_members:
            if user.id == context.bot.id:
                chat = update.effective_chat
                save_group(chat.id, chat.title)
                
                # Send welcome message
                await update.message.reply_text(
                    "🛡️ Thanks for adding me!\n\n"
                    "I will monitor this group and alert the owner of activities.\n\n"
                    "Use /start to see available commands."
                )
                
                # Alert owner
                alert_msg = f"🤖 Bot added to group: {chat.title}\n👥 Group ID: {chat.id}"
                await context.bot.send_message(chat_id=CHAT_ID, text=alert_msg)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Error: {context.error}")

def main():
    """Start the bot"""
    print("🛡️ Starting Protection Bot...")
    
    # Initialize database
    init_db()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers - IMPORTANT: Add them first
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Add message handlers - process after commands
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_group_events))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    print("✅ Bot is running...")
    print("🤖 Add the bot to your group as ADMIN for best results!")
    application.run_polling()

if __name__ == '__main__':
    main()
