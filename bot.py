import os
import logging
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import pg8000
from pg8000.native import Connection, DatabaseError

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME')
GROUP_ID = os.getenv('GROUP_ID')
DATABASE_URL = os.getenv('DATABASE_URL')

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database connection
def get_db_connection():
    try:
        # Parse DATABASE_URL (format: postgresql://user:password@host:port/database)
        db_url = DATABASE_URL.replace('postgresql://', '').split('@')
        user_pass = db_url[0].split(':')
        host_port_db = db_url[1].split('/')
        host_port = host_port_db[0].split(':')
        
        conn = Connection(
            user=user_pass[0],
            password=user_pass[1],
            host=host_port[0],
            port=int(host_port[1]),
            database=host_port_db[1]
        )
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

# Risk detection functions
class RiskDetector:
    @staticmethod
    def detect_spam(text):
        spam_indicators = [
            'http://', 'https://', '.com', '.org', '.net',
            'buy now', 'click here', 'limited offer', 'discount',
            'make money', 'earn cash', 'work from home'
        ]
        return any(indicator in text.lower() for indicator in spam_indicators)
    
    @staticmethod
    def detect_inappropriate_content(text):
        inappropriate_words = [
            'fuck', 'shit', 'asshole', 'bitch', 'dick', 'porn',
            'nude', 'sex', 'drugs', 'weed', 'cocaine'
        ]
        return any(word in text.lower() for word in inappropriate_words)
    
    @staticmethod
    def detect_caps_spam(text):
        if len(text) < 10:
            return False
        caps_count = sum(1 for char in text if char.isupper())
        return (caps_count / len(text)) > 0.7
    
    @staticmethod
    def assess_risk_level(message):
        risk_score = 0
        reasons = []
        
        if RiskDetector.detect_spam(message.text or ''):
            risk_score += 3
            reasons.append("Spam links/content detected")
        
        if RiskDetector.detect_inappropriate_content(message.text or ''):
            risk_score += 4
            reasons.append("Inappropriate content")
        
        if RiskDetector.detect_caps_spam(message.text or ''):
            risk_score += 2
            reasons.append("Excessive caps usage")
        
        # Check for new user (account age < 7 days)
        if message.from_user:
            user_age = datetime.now().timestamp() - message.from_user.id
            if user_age < 604800:  # 7 days in seconds
                risk_score += 1
                reasons.append("New user account")
        
        if risk_score >= 5:
            return "HIGH", reasons
        elif risk_score >= 3:
            return "MEDIUM", reasons
        elif risk_score >= 1:
            return "LOW", reasons
        else:
            return "NONE", []

# Alert system
class AlertSystem:
    @staticmethod
    async def send_alert(context: ContextTypes.DEFAULT_TYPE, message, risk_level, reasons):
        alert_message = f"""
🚨 **SECURITY ALERT** 🚨

**Risk Level:** {risk_level}
**Message:** {message.text[:200] if message.text else 'No text content'}
**User:** @{message.from_user.username if message.from_user.username else 'N/A'} (ID: {message.from_user.id})
**Chat:** {message.chat.title if message.chat.title else 'N/A'}

**Reasons:**
{chr(10).join(f'• {reason}' for reason in reasons)}

**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=alert_message,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Alert sent to admin for risk level: {risk_level}")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
    
    @staticmethod
    async def take_action(context: ContextTypes.DEFAULT_TYPE, message, risk_level):
        try:
            if risk_level == "HIGH":
                # Delete message and ban user
                await message.delete()
                await context.bot.ban_chat_member(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id
                )
                await context.bot.send_message(
                    chat_id=message.chat.id,
                    text=f"User @{message.from_user.username} has been banned for violating group rules."
                )
            
            elif risk_level == "MEDIUM":
                # Delete message and restrict user
                await message.delete()
                await context.bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False
                    ),
                    until_date=datetime.now() + timedelta(hours=24)
                )
                await context.bot.send_message(
                    chat_id=message.chat.id,
                    text=f"User @{message.from_user.username} has been restricted for 24 hours."
                )
            
        except Exception as e:
            logger.error(f"Failed to take action: {e}")

# Database operations
class DatabaseManager:
    @staticmethod
    def log_message(message, risk_level):
        conn = get_db_connection()
        if not conn:
            return
        
        try:
            conn.run(
                """INSERT INTO monitored_messages 
                (message_id, chat_id, user_id, username, text, message_type, risk_level) 
                VALUES (:1, :2, :3, :4, :5, :6, :7)""",
                [
                    message.message_id,
                    message.chat.id,
                    message.from_user.id if message.from_user else None,
                    message.from_user.username if message.from_user else None,
                    message.text or '',
                    message.content_type,
                    risk_level
                ]
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to log message: {e}")
        finally:
            conn.close()
    
    @staticmethod
    def add_user_warning(user_id, username):
        conn = get_db_connection()
        if not conn:
            return
        
        try:
            # Check if user exists
            result = conn.run(
                "SELECT warning_count FROM user_warnings WHERE user_id = :1",
                [user_id]
            )
            
            if result:
                # Update existing user
                new_count = result[0][0] + 1
                conn.run(
                    "UPDATE user_warnings SET warning_count = :1, last_warning = CURRENT_TIMESTAMP WHERE user_id = :2",
                    [new_count, user_id]
                )
            else:
                # Insert new user
                conn.run(
                    "INSERT INTO user_warnings (user_id, username, warning_count) VALUES (:1, :2, :3)",
                    [user_id, username, 1]
                )
            
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to add user warning: {e}")
        finally:
            conn.close()

# Bot handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Group Protection Bot Active**\n\n"
        "I'm monitoring this group for potential ban risks and will alert admins of suspicious activities.",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    
    # Skip if message is from bot
    if message.from_user and message.from_user.is_bot:
        return
    
    # Analyze message for risks
    risk_level, reasons = RiskDetector.assess_risk_level(message)
    
    # Log message to database
    DatabaseManager.log_message(message, risk_level)
    
    # Take action based on risk level
    if risk_level in ["MEDIUM", "HIGH"]:
        # Send alert to admin
        await AlertSystem.send_alert(context, message, risk_level, reasons)
        
        # Take automatic action
        await AlertSystem.take_action(context, message, risk_level)
        
        # Log user warning
        if message.from_user:
            DatabaseManager.add_user_warning(message.from_user.id, message.from_user.username)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}")
    
    # Send error alert to admin
    try:
        error_message = f"""
❌ **BOT ERROR** ❌

**Error:** {context.error}
**Update:** {update}

**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=error_message,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Failed to send error alert: {e}")

# Admin commands
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("❌ Database connection failed.")
        return
    
    try:
        # Get total monitored messages
        total_msgs = conn.run("SELECT COUNT(*) FROM monitored_messages")[0][0]
        
        # Get high risk messages count
        high_risk = conn.run("SELECT COUNT(*) FROM monitored_messages WHERE risk_level = 'HIGH'")[0][0]
        
        # Get warned users count
        warned_users = conn.run("SELECT COUNT(*) FROM user_warnings WHERE warning_count > 0")[0][0]
        
        stats_message = f"""
📊 **Bot Statistics**

**Total Monitored Messages:** {total_msgs}
**High Risk Detections:** {high_risk}
**Users Warned/Restricted:** {warned_users}
**Last Check:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        await update.message.reply_text(stats_message, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        await update.message.reply_text("❌ Failed to retrieve statistics.")
    finally:
        conn.close()

def main():
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
