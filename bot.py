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
            "🤖 *Group Monitor Bot*\n\n"
            "*Available Commands:*\n"
            "/start - Show this menu\n"
            "/help - Get help\n"
            "/status - Group health status\n"
            "/stats - Detailed statistics\n"
            "/top - Top active users\n"
            "/info - Bot information\n\n"
            "Add me to your group to start monitoring activity!",
            parse_mode='Markdown'
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
        
        await update.message.reply_text(
            "🛡️ *Group Monitor Activated!*\n\n"
            "I'm now tracking activity in this group.\n"
            "Use /help to see available commands.",
            parse_mode='Markdown'
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = (
        "📖 *Bot Help Guide*\n\n"
        "*Commands Available:*\n"
        "• /start - Show main menu\n"
        "• /help - This help message\n"
        "• /status - Group health & activity\n"
        "• /stats - Message statistics\n"
        "• /top - Most active users\n"
        "• /info - Bot information\n\n"
        "*How I Work:*\n"
        "• I track messages in groups\n"
        "• No admin rights needed\n"
        "• I store activity data locally\n"
        "• I don't store message content\n\n"
        "Just add me to any group and I'll start monitoring!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group status check"""
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ *This command works in groups only!*", parse_mode='Markdown')
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
        
        # Get total tracked members
        cursor.execute(
            'SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE group_id = ?',
            (update.effective_chat.id,)
        )
        total_tracked = cursor.fetchone()[0] or 0
        
        # Get today's messages
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cursor.execute(
            'SELECT COUNT(*) FROM user_activity WHERE group_id = ? AND last_active > ?',
            (update.effective_chat.id, today_start)
        )
        today_messages = cursor.fetchone()[0] or 0
        
        # Health assessment
        if active_members >= 10:
            health = "💚 Excellent"
        elif active_members >= 5:
            health = "💛 Good"
        elif active_members >= 2:
            health = "🟡 Normal"
        else:
            health = "🔴 Low"
        
        response = (
            f"🏥 *Group Health Status*\n\n"
            f"*Health:* {health}\n"
            f"*Active Members (24h):* {active_members}\n"
            f"*Total Tracked Members:* {total_tracked}\n"
            f"*Today's Messages:* {today_messages}\n"
            f"*Group:* {update.effective_chat.title}\n\n"
            f"⏰ *Last Updated:* {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Status error: {e}")
        await update.message.reply_text("❌ Error getting status")
    finally:
        conn.close()

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group statistics"""
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ *This command works in groups only!*", parse_mode='Markdown')
        return
    
    try:
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        # Get total messages
        cursor.execute(
            'SELECT SUM(message_count) FROM user_activity WHERE group_id = ?',
            (update.effective_chat.id,)
        )
        total_messages = cursor.fetchone()[0] or 0
        
        # Get active members (last 7 days)
        week_ago = datetime.now() - timedelta(days=7)
        cursor.execute(
            'SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE group_id = ? AND last_active > ?',
            (update.effective_chat.id, week_ago)
        )
        weekly_active = cursor.fetchone()[0] or 0
        
        # Get daily average
        cursor.execute(
            'SELECT AVG(message_count) FROM user_activity WHERE group_id = ?',
            (update.effective_chat.id,)
        )
        avg_messages = cursor.fetchone()[0] or 0
        
        response = (
            f"📊 *Group Statistics*\n\n"
            f"*Total Messages:* {total_messages}\n"
            f"*Weekly Active Users:* {weekly_active}\n"
            f"*Avg Messages per User:* {avg_messages:.1f}\n"
            f"*Group Size:* Unknown (bot needs admin for exact count)\n\n"
            f"*Tracking since:* {datetime.now().strftime('%Y-%m-%d')}"
        )
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await update.message.reply_text("❌ Error getting statistics")
    finally:
        conn.close()

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Top active users"""
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ *This command works in groups only!*", parse_mode='Markdown')
        return
    
    try:
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        # Get top 10 active users
        cursor.execute('''
            SELECT user_id, message_count 
            FROM user_activity 
            WHERE group_id = ? 
            ORDER BY message_count DESC 
            LIMIT 10
        ''', (update.effective_chat.id,))
        
        top_users = cursor.fetchall()
        
        if not top_users:
            await update.message.reply_text("📝 *No activity data yet!*", parse_mode='Markdown')
            return
        
        response = "🏆 *Top Active Users*\n\n"
        
        for i, (user_id, count) in enumerate(top_users, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            response += f"{medal} User `{user_id}`: *{count}* messages\n"
        
        response += f"\n*Total tracked users:* {len(top_users)}"
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Top error: {e}")
        await update.message.reply_text("❌ Error getting top users")
    finally:
        conn.close()

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot information"""
    info_text = (
        "🤖 *Group Monitor Bot*\n\n"
        "*Version:* 2.0\n"
        "*Purpose:* Track group activity and statistics\n"
        "*Features:*\n"
        "  • Message counting\n"
        "  • User activity tracking\n"
        "  • Group health monitoring\n"
        "  • No admin rights required\n\n"
        "*Privacy:*\n"
        "  • I don't store message content\n"
        "  • Only track message counts\n"
        "  • Data stored locally\n\n"
        "*Developer:* @YourUsername\n"
        "*Source:* Private"
    )
    await update.message.reply_text(info_text, parse_mode='Markdown')

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

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("info", info))
    
    # Add message handler for tracking
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_message))

    print("✅ Bot is running with updated menu...")
    print("🤖 Available commands: /start, /help, /status, /stats, /top, /info")
    application.run_polling()

if __name__ == '__main__':
    main()
