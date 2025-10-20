import os
import logging
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import sqlite3
from datetime import datetime, timedelta

# Render environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ALERT_CHAT_ID = os.environ.get('ALERT_CHAT_ID')

# Validate required environment variables
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
if not ALERT_CHAT_ID:
    raise ValueError("ALERT_CHAT_ID environment variable is required")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup - Render provides persistent storage
def init_db():
    conn = sqlite3.connect('/tmp/protection_bot.db')  # Use /tmp for Render compatibility
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            group_title TEXT,
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS risky_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            user_id INTEGER,
            username TEXT,
            message_text TEXT,
            risk_type TEXT,
            action_taken TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_warnings (
            user_id INTEGER,
            group_id INTEGER,
            warning_count INTEGER DEFAULT 0,
            last_warning TIMESTAMP,
            is_banned BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (user_id, group_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ban_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            alert_type TEXT,
            alert_message TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

init_db()

class BanProtection:
    def __init__(self):
        self.spam_keywords = [
            'http://', 'https://', '.com', '.org', '.net', '.xyz',
            'buy now', 'click here', 'limited offer', 'discount',
            'make money', 'earn cash', 'work from home', 'investment',
            'bitcoin', 'crypto', 'free money', 't.me/joinchat/'
        ]
        
        self.bad_words = [
            'fuck', 'shit', 'asshole', 'bitch', 'dick', 'porn',
            'nude', 'sex', 'drugs', 'weed', 'cocaine', 'heroin'
        ]
        
        self.scam_phrases = [
            'send money', 'bank transfer', 'password', 'login',
            'verify account', 'security check', 'admin contact',
            'telegram support', 'official group', 'card number'
        ]
    
    def check_message_risk(self, text):
        """Check message for ban risks"""
        if not text:
            return "safe", []
        
        text_lower = text.lower()
        risks = []
        risk_level = "safe"
        
        # Check for spam
        spam_count = sum(1 for keyword in self.spam_keywords if keyword in text_lower)
        if spam_count >= 2:
            risks.append("spam_links")
            risk_level = "high"
        elif spam_count == 1:
            risks.append("suspicious_link")
            risk_level = "medium"
        
        # Check for bad words
        bad_word_count = sum(1 for word in self.bad_words if word in text_lower)
        if bad_word_count >= 2:
            risks.append("inappropriate_content")
            risk_level = "high"
        elif bad_word_count == 1:
            risks.append("mild_inappropriate")
            risk_level = "medium"
        
        # Check for scam phrases
        if any(phrase in text_lower for phrase in self.scam_phrases):
            risks.append("scam_attempt")
            risk_level = "high"
        
        # Check for excessive caps
        if len(text) > 10:
            caps_count = sum(1 for char in text if char.isupper())
            if caps_count / len(text) > 0.7:
                risks.append("caps_spam")
                risk_level = "medium"
        
        return risk_level, risks

async def send_ban_alert(context, group_title, username, user_id, message_text, risk_type, action_taken):
    """Send ban risk alert to owner"""
    try:
        alert_msg = (
            f"🚨 *BAN RISK ALERT*\n\n"
            f"*Group:* {group_title}\n"
            f"*User:* @{username or 'No username'} (ID: `{user_id}`)\n"
            f"*Risk Type:* {risk_type}\n"
            f"*Action Taken:* {action_taken}\n"
            f"*Message:* {message_text[:200]}\n\n"
            f"⏰ *Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        await context.bot.send_message(
            chat_id=ALERT_CHAT_ID,
            text=alert_msg,
            parse_mode='Markdown'
        )
        
        # Save alert to database
        conn = sqlite3.connect('/tmp/protection_bot.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO ban_alerts (group_id, alert_type, alert_message) VALUES (?, ?, ?)',
            (user_id, risk_type, alert_msg)
        )
        conn.commit()
        conn.close()
        
        logger.info(f"Alert sent for {risk_type} in {group_title}")
        
    except Exception as e:
        logger.error(f"Alert error: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "🛡️ *Group Protection Bot*\n\n"
            "*I protect your groups from ban risks!*\n\n"
            "*Commands:*\n"
            "/start - Show this menu\n"
            "/status - Protection status\n"
            "/alerts - Recent ban alerts\n"
            "/stats - Protection statistics\n"
            "/warned - List warned users\n\n"
            "*Features:*\n"
            "• Auto-detect spam & scams\n"
            "• Remove inappropriate content\n"
            "• Alert owner of ban risks\n"
            "• Track warned users\n\n"
            "Add me to your group as ADMIN to enable full protection!",
            parse_mode='Markdown'
        )
    else:
        # Save group info
        conn = sqlite3.connect('/tmp/protection_bot.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO groups (group_id, group_title) VALUES (?, ?)',
            (update.effective_chat.id, update.effective_chat.title)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            "🛡️ *Protection Activated!*\n\n"
            "I'm now monitoring this group for ban risks.\n"
            "I will delete risky messages and alert the owner.\n\n"
            "Use /status to check protection status.",
            parse_mode='Markdown'
        )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Protection status"""
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ *This command works in groups only!*", parse_mode='Markdown')
        return
    
    try:
        conn = sqlite3.connect('/tmp/protection_bot.db')
        cursor = conn.cursor()
        
        # Get stats for this group
        cursor.execute(
            'SELECT COUNT(*) FROM risky_messages WHERE group_id = ?',
            (update.effective_chat.id,)
        )
        risky_count = cursor.fetchone()[0] or 0
        
        cursor.execute(
            'SELECT COUNT(*) FROM user_warnings WHERE group_id = ?',
            (update.effective_chat.id,)
        )
        warned_users = cursor.fetchone()[0] or 0
        
        # Check if bot is admin
        try:
            bot_member = await update.effective_chat.get_member(context.bot.id)
            is_admin = bot_member.status in ['administrator', 'creator']
            admin_status = "✅ Admin" if is_admin else "❌ Not Admin"
        except Exception as e:
            logger.error(f"Admin check error: {e}")
            admin_status = "❓ Unknown"
        
        status_msg = (
            f"🛡️ *Protection Status*\n\n"
            f"*Group:* {update.effective_chat.title}\n"
            f"*Bot Status:* {admin_status}\n"
            f"*Risky Messages Blocked:* {risky_count}\n"
            f"*Users Warned:* {warned_users}\n"
            f"*Alerts Sent:* Active\n\n"
        )
        
        if admin_status == "❌ Not Admin":
            status_msg += "*⚠️ Make me ADMIN for full protection!*"
        else:
            status_msg += "*✅ Full protection enabled!*"
        
        await update.message.reply_text(status_msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Status error: {e}")
        await update.message.reply_text("❌ Error getting status")
    finally:
        conn.close()

async def alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recent ban alerts"""
    try:
        conn = sqlite3.connect('/tmp/protection_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT alert_type, alert_message, timestamp 
            FROM ban_alerts 
            ORDER BY timestamp DESC 
            LIMIT 5
        ''')
        
        recent_alerts = cursor.fetchall()
        
        if not recent_alerts:
            await update.message.reply_text("📊 *No alerts yet!*", parse_mode='Markdown')
            return
        
        response = "🚨 *Recent Ban Alerts*\n\n"
        
        for alert_type, alert_msg, timestamp in recent_alerts:
            time_ago = datetime.now() - datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            hours_ago = int(time_ago.total_seconds() / 3600)
            
            response += f"• *{alert_type}* - {hours_ago}h ago\n"
        
        response += f"\n*Total alerts sent to owner:* {len(recent_alerts)}"
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Alerts error: {e}")
        await update.message.reply_text("❌ Error getting alerts")
    finally:
        conn.close()

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Protection statistics"""
    try:
        conn = sqlite3.connect('/tmp/protection_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM groups')
        protected_groups = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM risky_messages')
        total_blocked = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM user_warnings')
        total_warned = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM ban_alerts')
        total_alerts = cursor.fetchone()[0] or 0
        
        stats_msg = (
            f"📊 *Protection Statistics*\n\n"
            f"*Protected Groups:* {protected_groups}\n"
            f"*Messages Blocked:* {total_blocked}\n"
            f"*Users Warned:* {total_warned}\n"
            f"*Alerts Sent:* {total_alerts}\n\n"
            f"*Last Update:* {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        
        await update.message.reply_text(stats_msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await update.message.reply_text("❌ Error getting statistics")
    finally:
        conn.close()

async def warned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List warned users"""
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ *This command works in groups only!*", parse_mode='Markdown')
        return
    
    try:
        conn = sqlite3.connect('/tmp/protection_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id, warning_count, last_warning 
            FROM user_warnings 
            WHERE group_id = ? 
            ORDER BY warning_count DESC 
            LIMIT 10
        ''', (update.effective_chat.id,))
        
        warned_users = cursor.fetchall()
        
        if not warned_users:
            await update.message.reply_text("✅ *No warned users in this group!*", parse_mode='Markdown')
            return
        
        response = "⚠️ *Warned Users*\n\n"
        
        for user_id, count, last_warn in warned_users:
            response += f"• User `{user_id}`: {count} warnings\n"
        
        response += f"\n*Total warned users:* {len(warned_users)}"
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Warned error: {e}")
        await update.message.reply_text("❌ Error getting warned users")
    finally:
        conn.close()

async def protect_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Monitor and protect against ban risks"""
    if not update.message or not update.effective_user:
        return
    
    if update.effective_chat.type not in ["group", "supergroup"]:
        return
    
    try:
        # Save group info
        conn = sqlite3.connect('/tmp/protection_bot.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO groups (group_id, group_title) VALUES (?, ?)',
            (update.effective_chat.id, update.effective_chat.title)
        )
        
        protection = BanProtection()
        message_text = update.message.text or update.message.caption or ""
        
        risk_level, risks = protection.check_message_risk(message_text)
        
        if risk_level != "safe":
            # Save risky message
            cursor.execute(
                'INSERT INTO risky_messages (group_id, user_id, username, message_text, risk_type, action_taken) VALUES (?, ?, ?, ?, ?, ?)',
                (update.effective_chat.id, update.effective_user.id, update.effective_user.username, message_text, ', '.join(risks), "Monitoring")
            )
            
            action_taken = "Monitoring"
            
            # Try to delete message if bot is admin
            try:
                bot_member = await update.effective_chat.get_member(context.bot.id)
                if bot_member.status in ['administrator', 'creator']:
                    await update.message.delete()
                    action_taken = "Message deleted"
                    
                    # Update action taken in database
                    cursor.execute(
                        'UPDATE risky_messages SET action_taken = ? WHERE group_id = ? AND user_id = ? AND message_text = ?',
                        (action_taken, update.effective_chat.id, update.effective_user.id, message_text)
                    )
                    
                    # Add user warning
                    cursor.execute('''
                        INSERT OR REPLACE INTO user_warnings 
                        (user_id, group_id, warning_count, last_warning)
                        VALUES (?, ?, COALESCE((SELECT warning_count FROM user_warnings WHERE user_id = ? AND group_id = ?), 0) + 1, ?)
                    ''', (update.effective_user.id, update.effective_chat.id, update.effective_user.id, update.effective_chat.id, datetime.now()))
            except Exception as e:
                logger.error(f"Delete failed: {e}")
                action_taken = "Delete failed (need admin)"
            
            # Send alert to owner
            await send_ban_alert(
                context,
                update.effective_chat.title,
                update.effective_user.username,
                update.effective_user.id,
                message_text,
                ', '.join(risks),
                action_taken
            )
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"Protection error: {e}")

def main():
    """Start the protection bot"""
    logger.info("🛡️ Starting Ban Protection Bot...")
    logger.info(f"📧 Alerts will be sent to: {ALERT_CHAT_ID}")
    
    # Create application with better error handling
    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("alerts", alerts))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("warned", warned))
    
    # Add message protection handler - process all non-command messages
    application.add_handler(MessageHandler(
        filters.ALL & ~filters.COMMAND, 
        protect_messages
    ))

    # Start the bot with error handling
    try:
        logger.info("✅ Bot is running and monitoring...")
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")
        raise

if __name__ == '__main__':
    main()
