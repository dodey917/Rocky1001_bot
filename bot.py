import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import sqlite3
from datetime import datetime, timedelta

# Setup
BOT_TOKEN = os.getenv('BOT_TOKEN')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            group_title TEXT,
            last_updated TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_activity (
            user_id INTEGER,
            group_id INTEGER,
            last_active TIMESTAMP,
            message_count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, group_id)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "🤖 Bot is running!\n\n"
            "Commands:\n"
            "/start - Start bot\n"
            "/status - Group status\n"
            "/stats - Group stats\n\n"
            "Add me to groups to monitor activity!"
        )
    else:
        # Save group info
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO groups (group_id, group_title, last_updated) VALUES (?, ?, ?)',
            (update.effective_chat.id, update.effective_chat.title, datetime.now())
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text("🔍 Bot is now monitoring this group!")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group status check"""
    if update.effective_chat.type == "private":
        await update.message.reply_text("This command works in groups only!")
        return
    
    try:
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        # Get active members (last 24 hours)
        twenty_four_hours_ago = datetime.now() - timedelta(hours=24)
        cursor.execute(
            'SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE group_id = ? AND last_active > ?',
            (update.effective_chat.id, twenty_four_hours_ago)
        )
        active_members = cursor.fetchone()[0] or 0
        
        # Get total members who ever sent messages
        cursor.execute(
            'SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE group_id = ?',
            (update.effective_chat.id,)
        )
        total_tracked = cursor.fetchone()[0] or 0
        
        response = (
            f"📊 Group Status\n\n"
            f"Active members (24h): {active_members}\n"
            f"Total tracked: {total_tracked}\n"
            f"Group: {update.effective_chat.title}\n"
            f"Last update: {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Status error: {e}")
        await update.message.reply_text("Error getting status")
    finally:
        conn.close()

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group statistics"""
    if update.effective_chat.type == "private":
        await update.message.reply_text("This command works in groups only!")
        return
    
    try:
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        # Get top active users
        cursor.execute('''
            SELECT user_id, message_count 
            FROM user_activity 
            WHERE group_id = ? 
            ORDER BY message_count DESC 
            LIMIT 5
        ''', (update.effective_chat.id,))
        
        top_users = cursor.fetchall()
        
        # Get total messages
        cursor.execute(
            'SELECT SUM(message_count) FROM user_activity WHERE group_id = ?',
            (update.effective_chat.id,)
        )
        total_messages = cursor.fetchone()[0] or 0
        
        response = f"📈 Group Stats\n\nTotal messages: {total_messages}\n\nTop users:\n"
        
        for user_id, count in top_users:
            response += f"• User {user_id}: {count} messages\n"
        
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await update.message.reply_text("Error getting stats")
    finally:
        conn.close()

async def track_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track all messages in groups"""
    if not update.message or not update.effective_user:
        return
    
    if update.effective_chat.type not in ["group", "supergroup"]:
        return
    
    try:
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        # Save group info
        cursor.execute(
            'INSERT OR REPLACE INTO groups (group_id, group_title, last_updated) VALUES (?, ?, ?)',
            (update.effective_chat.id, update.effective_chat.title, datetime.now())
        )
        
        # Track user activity
        cursor.execute('''
            INSERT OR REPLACE INTO user_activity 
            (user_id, group_id, last_active, message_count)
            VALUES (?, ?, ?, COALESCE((SELECT message_count FROM user_activity WHERE user_id = ? AND group_id = ?), 0) + 1)
        ''', (
            update.effective_user.id, 
            update.effective_chat.id, 
            datetime.now(),
            update.effective_user.id,
            update.effective_chat.id
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"Track error: {e}")

def main():
    """Start the bot"""
    if not BOT_TOKEN:
        print("❌ No BOT_TOKEN found!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_message))

    print("✅ Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
