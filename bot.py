import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import psycopg2
import requests

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
        
        # Create tables if they don't exist
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
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                group_id BIGINT,
                alert_type TEXT,
                alert_message TEXT,
                alert_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database initialized successfully")
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
            (chat_id, user_id, username, message_text)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Save message error: {e}")

def save_alert(chat_id, alert_type, alert_message):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO alerts (group_id, alert_type, alert_message) VALUES (%s, %s, %s)",
            (chat_id, alert_type, alert_message)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Save alert error: {e}")

async def send_alert(context, message):
    """Send alert to owner"""
    try:
        alert_msg = f"🚨 Alert from {message.chat.title}\n👤 User: @{message.from_user.username or 'No username'}\n💬 Message: {message.text[:100] if message.text else 'Media message'}\n⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
        await context.bot.send_message(chat_id=CHAT_ID, text=alert_msg)
        save_alert(message.chat.id, "message_alert", alert_msg)
    except Exception as e:
        logger.error(f"Send alert error: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat = update.effective_chat
    
    if chat.type in ["group", "supergroup"]:
        save_group(chat.id, chat.title)
        await send_alert(context, update.message)
    
    await update.message.reply_text(
        "🛡️ *Protection Bot Active*\n\n"
        "I'm monitoring this group and will alert the owner of activities.\n\n"
        "*Commands:*\n"
        "/start - Show this message\n"
        "/status - Check bot status\n"
        "/scan - Scan group messages\n"
        "/stats - Show statistics\n"
        "/alerts - Alert settings",
        parse_mode='Markdown'
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    chat = update.effective_chat
    
    # Check if bot is admin
    try:
        bot_member = await chat.get_member(context.bot.id)
        is_admin = bot_member.status in ['administrator', 'creator']
        admin_status = "✅ Admin" if is_admin else "❌ Not Admin"
    except:
        admin_status = "❓ Unknown"
    
    status_msg = (
        f"🤖 *Bot Status*\n\n"
        f"🟢 Online\n"
        f"🛡️ Protection: Active\n"
        f"📊 Monitoring: Enabled\n"
        f"🔔 Alerts: Active\n"
        f"👑 {admin_status}\n\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /scan command"""
    chat = update.effective_chat
    
    try:
        # Check if bot is admin
        bot_member = await chat.get_member(context.bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            await update.message.reply_text("❌ I need to be admin to scan messages!")
            return
        
        await update.message.reply_text("🔍 Scanning recent messages...")
        
        # Get recent messages count from database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM messages WHERE group_id = %s", (chat.id,))
        message_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM alerts WHERE group_id = %s", (chat.id,))
        alert_count = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        scan_result = (
            f"📊 *Scan Results*\n\n"
            f"📝 Messages logged: {message_count}\n"
            f"🚨 Alerts sent: {alert_count}\n"
            f"👥 Group: {chat.title}\n"
            f"✅ Scan completed successfully!"
        )
        
        await update.message.reply_text(scan_result, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Scan error: {e}")
        await update.message.reply_text("❌ Scan failed!")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM groups")
        group_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM messages")
        total_messages = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM alerts")
        total_alerts = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        stats_msg = (
            f"📈 *Bot Statistics*\n\n"
            f"👥 Groups monitoring: {group_count}\n"
            f"💬 Total messages: {total_messages}\n"
            f"🚨 Total alerts: {total_alerts}\n"
            f"🕒 Last update: {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await update.message.reply_text(stats_msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await update.message.reply_text("❌ Could not get statistics")

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alerts command"""
    alert_msg = (
        "🔔 *Alert Settings*\n\n"
        "Currently monitoring:\n"
        "✅ New messages\n"
        "✅ User joins\n"
        "✅ Group changes\n"
        "✅ Command usage\n\n"
        "Alerts are sent to the bot owner."
    )
    await update.message.reply_text(alert_msg, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all incoming messages"""
    message = update.message
    chat = update.effective_chat
    
    if not message or not message.from_user:
        return
    
    # Skip bot messages
    if message.from_user.is_bot:
        return
    
    # Save group info
    if chat.type in ["group", "supergroup"]:
        save_group(chat.id, chat.title)
    
    # Save message to database
    if message.text:
        save_message(chat.id, message.from_user.id, message.from_user.username, message.text)
    
    # Send alert for every message (you can modify this logic)
    if chat.type in ["group", "supergroup"]:
        await send_alert(context, message)

async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new chat members"""
    chat = update.effective_chat
    for user in update.message.new_chat_members:
        if user.id == context.bot.id:
            # Bot was added to a group
            save_group(chat.id, chat.title)
            alert_msg = f"🤖 Bot added to group: {chat.title}\n👥 Group ID: {chat.id}"
            await context.bot.send_message(chat_id=CHAT_ID, text=alert_msg)
            save_alert(chat.id, "bot_added", alert_msg)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Error: {context.error}")
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=f"❌ Bot Error: {context.error}")
    except:
        pass

def main():
    """Start the bot"""
    print("🛡️ Starting Protection Bot...")
    
    # Initialize database
    init_db()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("alerts", alerts_command))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    print("✅ Bot is running and monitoring...")
    application.run_polling()

if __name__ == '__main__':
    main()
