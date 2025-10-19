import os
import logging
import asyncio
import sys
from datetime import datetime
from typing import Dict, List, Any

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from telegram import (
    Update, 
    Chat, 
    User, 
    BotCommand,
    ChatMemberUpdated
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    ChatMemberHandler,
    filters,
    CallbackContext
)
from telegram.constants import ChatType, ChatMemberStatus
from telegram.error import TelegramError

# Load environment variables
load_dotenv()

# Configure logging for Render
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class Database:
    """Simplified database handler inspired by HAMSAS_BOT"""
    
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            logger.error("DATABASE_URL not found in environment variables")
            raise ValueError("DATABASE_URL is required")

    def get_connection(self):
        """Get database connection with retry logic"""
        try:
            conn = psycopg2.connect(
                self.database_url,
                cursor_factory=RealDictCursor
            )
            return conn
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def execute_query(self, query: str, params: tuple = None):
        """Execute query and return results"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params or ())
                if query.strip().upper().startswith('SELECT'):
                    result = cursor.fetchall()
                else:
                    conn.commit()
                    result = None
            return result
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

class GroupProtectionBot:
    """Simplified and optimized bot for Render"""
    
    def __init__(self):
        self.token = os.getenv('BOT_TOKEN')
        if not self.token:
            raise ValueError("BOT_TOKEN is required")
        
        self.owner_id = int(os.getenv('OWNER_ID', 0))
        if not self.owner_id:
            raise ValueError("OWNER_ID is required")
        
        self.owner_username = os.getenv('OWNER_USERNAME', '')
        
        self.db = Database()
        self.setup_database()
        
        logger.info("🤖 Group Protection Bot initialized")

    def setup_database(self):
        """Initialize database tables"""
        try:
            # Groups table
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS groups (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT UNIQUE NOT NULL,
                    group_name TEXT,
                    group_type VARCHAR(20),
                    member_count INTEGER DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'safe',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_scan TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            
            # Alerts table
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    alert_type VARCHAR(50) NOT NULL,
                    alert_message TEXT NOT NULL,
                    risk_level VARCHAR(20) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Activities table
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS activities (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    user_id BIGINT,
                    activity_type VARCHAR(50) NOT NULL,
                    content TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            logger.info("✅ Database tables initialized")
            
        except Exception as e:
            logger.error(f"Database setup error: {e}")
            raise

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            user = update.effective_user
            
            if update.message.chat.type == ChatType.PRIVATE:
                await update.message.reply_text(
                    "🤖 **Group Protection Bot**\n\n"
                    "I help protect your Telegram groups from risks and violations.\n\n"
                    "**Commands:**\n"
                    "/start - Show this message\n"
                    "/scan - Scan group for risks\n"
                    "/status - Check group status\n"
                    "/groups - List monitored groups\n\n"
                    "Add me to your group and make me admin!",
                    parse_mode='Markdown'
                )
                
                if user.id != self.owner_id:
                    await self.send_to_owner(
                        f"🆕 New user: {user.first_name} (@{user.username or 'No username'})"
                    )
                    
        except Exception as e:
            logger.error(f"Start command error: {e}")

    async def handle_chat_member_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bot being added to groups"""
        try:
            if not update.my_chat_member:
                return
                
            chat_member = update.my_chat_member
            chat = chat_member.chat
            new_status = chat_member.new_chat_member.status
            
            # Bot added to group
            if new_status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
                await self.add_group(chat)
                await self.send_to_owner(f"✅ Added to: {chat.title}")
                
                # Welcome message
                await context.bot.send_message(
                    chat.id,
                    "🛡️ **Group Protection Activated!**\nUse /scan to check security.",
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Chat member update error: {e}")

    async def add_group(self, chat: Chat):
        """Add group to database"""
        try:
            member_count = await self.get_member_count(chat)
            
            self.db.execute_query("""
                INSERT INTO groups (group_id, group_name, group_type, member_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (group_id) DO UPDATE SET
                group_name = EXCLUDED.group_name,
                member_count = EXCLUDED.member_count,
                is_active = TRUE
            """, (chat.id, chat.title, chat.type, member_count))
            
            logger.info(f"Group added: {chat.title}")
            
        except Exception as e:
            logger.error(f"Add group error: {e}")

    async def get_member_count(self, chat: Chat) -> int:
        """Safely get member count"""
        try:
            return await chat.get_member_count()
        except TelegramError:
            return 0

    async def scan_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Scan group for security risks"""
        try:
            chat = update.effective_chat
            
            if chat.type == ChatType.PRIVATE:
                await update.message.reply_text("Use this in a group!")
                return

            scan_msg = await update.message.reply_text("🔍 Scanning...")
            
            # Basic security check
            risk_score = await self.perform_scan(chat, context)
            status = await self.determine_status(risk_score)
            
            # Update database
            self.db.execute_query("""
                UPDATE groups 
                SET status = %s, last_scan = NOW() 
                WHERE group_id = %s
            """, (status, chat.id))
            
            # Send report
            report = self.generate_report(chat, risk_score, status)
            await scan_msg.edit_text(report, parse_mode='Markdown')
            
            # Notify owner
            await self.send_to_owner(
                f"📊 Scan completed for {chat.title}\n"
                f"Status: {status.upper()}\n"
                f"Score: {risk_score}/100"
            )
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
            await update.message.reply_text("❌ Scan failed!")

    async def perform_scan(self, chat: Chat, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Perform security scan"""
        risk_score = 0
        
        try:
            # Check bot permissions
            try:
                bot_member = await chat.get_member(context.bot.id)
                if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
                    risk_score += 30
            except TelegramError:
                risk_score += 50
            
            # Check member count (basic risk assessment)
            member_count = await self.get_member_count(chat)
            if member_count > 1000:
                risk_score += 20
            elif member_count > 100:
                risk_score += 10
                
            # Check recent alerts
            recent_alerts = self.db.execute_query(
                "SELECT COUNT(*) as count FROM alerts WHERE group_id = %s AND created_at > NOW() - INTERVAL '1 day'",
                (chat.id,)
            )
            if recent_alerts and recent_alerts[0]['count'] > 5:
                risk_score += 25
                
        except Exception as e:
            logger.error(f"Scan performance error: {e}")
            
        return min(risk_score, 100)

    async def determine_status(self, risk_score: int) -> str:
        """Determine group status based on risk score"""
        if risk_score > 70:
            return "high_risk"
        elif risk_score > 30:
            return "warning"
        else:
            return "safe"

    def generate_report(self, chat: Chat, risk_score: int, status: str) -> str:
        """Generate scan report"""
        status_emoji = "🔴" if status == "high_risk" else "🟡" if status == "warning" else "🟢"
        
        return (
            f"🛡️ **Security Report**\n\n"
            f"**Group:** {chat.title}\n"
            f"**Status:** {status_emoji} {status.upper()}\n"
            f"**Risk Score:** {risk_score}/100\n\n"
            f"*Use /status for updates*"
        )

    async def list_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all monitored groups"""
        try:
            if update.effective_user.id != self.owner_id:
                await update.message.reply_text("❌ Owner only!")
                return
            
            groups = self.db.execute_query("""
                SELECT group_name, member_count, status, last_scan 
                FROM groups WHERE is_active = TRUE
            """)
            
            if not groups:
                await update.message.reply_text("No groups monitored.")
                return
            
            response = "📋 **Monitored Groups**\n\n"
            for group in groups:
                status_emoji = "🔴" if group['status'] == 'high_risk' else "🟡" if group['status'] == 'warning' else "🟢"
                last_scan = group['last_scan'].strftime("%m/%d %H:%M") if group['last_scan'] else "Never"
                
                response += (
                    f"{status_emoji} **{group['group_name']}**\n"
                    f"Members: {group['member_count']} | Status: {group['status']}\n"
                    f"Last Scan: {last_scan}\n\n"
                )
            
            await update.message.reply_text(response, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"List groups error: {e}")

    async def group_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check group status"""
        try:
            chat = update.effective_chat
            
            if chat.type == ChatType.PRIVATE:
                await update.message.reply_text("Use in a group!")
                return
            
            group_data = self.db.execute_query(
                "SELECT status, member_count, last_scan FROM groups WHERE group_id = %s",
                (chat.id,)
            )
            
            if not group_data:
                await update.message.reply_text("Group not monitored. Use /scan first.")
                return
            
            group = group_data[0]
            status_emoji = "🔴" if group['status'] == 'high_risk' else "🟡" if group['status'] == 'warning' else "🟢"
            last_scan = group['last_scan'].strftime("%Y-%m-%d %H:%M") if group['last_scan'] else "Never"
            
            await update.message.reply_text(
                f"{status_emoji} **Status for {chat.title}**\n\n"
                f"**Status:** {group['status'].upper()}\n"
                f"**Members:** {group['member_count']}\n"
                f"**Last Scan:** {last_scan}\n\n"
                f"Use /scan for detailed analysis",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Status error: {e}")

    async def monitor_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Monitor messages for suspicious content"""
        try:
            if not update.message or update.message.chat.type == ChatType.PRIVATE:
                return
            
            message = update.message
            chat = message.chat
            user = message.from_user
            
            if user.id == context.bot.id:
                return
            
            # Basic spam detection
            if message.text:
                text = message.text.lower()
                spam_keywords = ['http://', 'https://', 't.me/', 'buy now', 'click here']
                
                if any(keyword in text for keyword in spam_keywords):
                    await self.log_alert(chat, user, "spam_detected")
                    await self.send_to_owner(
                        f"🚨 Spam detected in {chat.title}\n"
                        f"From: @{user.username or 'No username'}\n"
                        f"Message: {text[:100]}..."
                    )
                    
        except Exception as e:
            logger.error(f"Message monitoring error: {e}")

    async def log_alert(self, chat: Chat, user: User, alert_type: str):
        """Log alert to database"""
        try:
            self.db.execute_query("""
                INSERT INTO alerts (group_id, alert_type, alert_message, risk_level)
                VALUES (%s, %s, %s, %s)
            """, (chat.id, alert_type, f"Alert from @{user.username}", "medium"))
            
            # Also log activity
            self.db.execute_query("""
                INSERT INTO activities (group_id, user_id, activity_type, content)
                VALUES (%s, %s, %s, %s)
            """, (chat.id, user.id, alert_type, "Suspicious activity detected"))
            
        except Exception as e:
            logger.error(f"Alert logging error: {e}")

    async def send_to_owner(self, message: str):
        """Send message to bot owner"""
        try:
            app = Application.builder().token(self.token).build()
            await app.bot.send_message(
                chat_id=self.owner_id,
                text=message,
                parse_mode='Markdown'
            )
            await app.shutdown()
        except Exception as e:
            logger.error(f"Send to owner error: {e}")

    def setup_handlers(self, application: Application):
        """Setup bot handlers"""
        # Command handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("scan", self.scan_group))
        application.add_handler(CommandHandler("status", self.group_status))
        application.add_handler(CommandHandler("groups", self.list_groups))
        
        # Chat member updates
        application.add_handler(ChatMemberHandler(
            self.handle_chat_member_update, 
            ChatMemberHandler.MY_CHAT_MEMBER
        ))
        
        # Message monitoring
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
            self.monitor_messages
        ))

    async def setup_commands(self, application: Application):
        """Setup bot commands"""
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("scan", "Scan group for risks"),
            BotCommand("status", "Check group status"),
            BotCommand("groups", "List monitored groups"),
        ]
        await application.bot.set_my_commands(commands)

    async def error_handler(self, update: Update, context: CallbackContext):
        """Handle errors"""
        try:
            logger.error(f"Update {update} caused error {context.error}")
        except Exception as e:
            logger.error(f"Error handler error: {e}")

    async def run(self):
        """Run the bot"""
        try:
            # Create application
            application = Application.builder().token(self.token).build()
            
            # Setup handlers
            self.setup_handlers(application)
            
            # Setup commands
            await self.setup_commands(application)
            
            # Add error handler
            application.add_error_handler(self.error_handler)
            
            # Notify owner
            await self.send_to_owner("🤖 **Bot Started Successfully**\n\nGroup protection bot is now running!")
            
            logger.info("✅ Bot started - polling for updates...")
            
            # Start polling
            await application.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "my_chat_member", "chat_member"]
            )
            
        except Exception as e:
            logger.critical(f"❌ Bot failed to start: {e}")
            raise

def main():
    """Main function with proper error handling"""
    try:
        logger.info("🚀 Starting Group Protection Bot...")
        
        # Create and run bot
        bot = GroupProtectionBot()
        
        # Run the bot
        asyncio.run(bot.run())
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
