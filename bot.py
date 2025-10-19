import os
import logging
import sqlite3
import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from telegram import (
    Update, 
    Chat, 
    ChatMember, 
    BotCommand,
    ChatMemberUpdated
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    ChatMemberHandler
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class GroupProtectionBot:
    def __init__(self):
        # Get environment variables directly from Render
        self.bot_token = os.environ.get('BOT_TOKEN')
        self.owner_id = os.environ.get('OWNER_ID')
        
        # Validate required environment variables
        if not self.bot_token:
            raise ValueError("❌ BOT_TOKEN environment variable is required but not set")
        
        if self.owner_id:
            try:
                self.owner_id = int(self.owner_id)
                logger.info(f"✅ Owner ID set to: {self.owner_id}")
            except ValueError:
                logger.warning("⚠️ OWNER_ID is not a valid integer - owner notifications disabled")
                self.owner_id = None
        else:
            logger.warning("⚠️ OWNER_ID not set - owner notifications will be disabled")
        
        logger.info("✅ Environment variables loaded successfully")
        
        # Initialize bot application
        self.application = ApplicationBuilder().token(self.bot_token).build()
        
        # Setup database and handlers
        self.setup_database()
        self.setup_handlers()
        
        logger.info("✅ Bot initialized successfully")
    
    def setup_database(self):
        """Initialize SQLite database"""
        try:
            conn = sqlite3.connect('groups.db', check_same_thread=False)
            cursor = conn.cursor()
            
            # Create groups table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER UNIQUE NOT NULL,
                    chat_title TEXT,
                    chat_type TEXT,
                    member_count INTEGER DEFAULT 0,
                    bot_role TEXT DEFAULT 'member',
                    risk_level TEXT DEFAULT 'unknown',
                    purpose_description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create index for better performance
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_chat_id ON groups(chat_id)
            ''')
            
            conn.commit()
            conn.close()
            logger.info("✅ Database initialized successfully")
        except Exception as e:
            logger.error(f"❌ Error initializing database: {e}")
            raise
    
    def get_db_connection(self):
        """Get SQLite database connection with error handling"""
        try:
            conn = sqlite3.connect('groups.db', check_same_thread=False)
            conn.row_factory = sqlite3.Row  # This enables column access by name
            return conn
        except Exception as e:
            logger.error(f"❌ Database connection error: {e}")
            raise
    
    async def get_bot_role(self, chat, context):
        """Safely get bot's role in the chat"""
        try:
            bot_member = await chat.get_member(context.bot.id)
            if bot_member.status in ['administrator', 'creator']:
                return "admin"
            else:
                return "member"
        except Exception as e:
            logger.warning(f"⚠️ Could not get bot role: {e}")
            return "member"
    
    async def get_member_count_safe(self, chat):
        """Safely get member count"""
        try:
            return chat.get_member_count() or 0
        except Exception as e:
            logger.warning(f"⚠️ Could not get member count: {e}")
            return 0
    
    async def save_group_info(self, chat: Chat, bot_role: str = "member"):
        """Save or update group information in database"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            member_count = await self.get_member_count_safe(chat)
            
            cursor.execute('''
                INSERT OR REPLACE INTO groups 
                (chat_id, chat_title, chat_type, member_count, bot_role, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            ''', (
                chat.id, 
                chat.title if hasattr(chat, 'title') else 'Unknown',
                chat.type,
                member_count, 
                bot_role
            ))
            
            conn.commit()
            conn.close()
            logger.info(f"✅ Saved group info: {getattr(chat, 'title', 'Unknown')} (ID: {chat.id})")
            return True
        except Exception as e:
            logger.error(f"❌ Error saving group info: {e}")
            return False
    
    async def analyze_group_risk(self, chat: Chat) -> Dict:
        """Analyze group risk level and provide insights"""
        risk_factors = []
        risk_score = 0
        
        # Get member count safely
        member_count = await self.get_member_count_safe(chat)
        
        # Member count analysis
        if member_count < 5:
            risk_factors.append("Very small group (potential spam)")
            risk_score += 3
        elif member_count < 20:
            risk_factors.append("Small group")
            risk_score += 1
        elif member_count > 50000:
            risk_factors.append("Very large group (high visibility)")
            risk_score += 2
        elif member_count > 10000:
            risk_factors.append("Large group (increased monitoring)")
            risk_score += 1
        
        # Group type analysis
        if chat.type == Chat.CHANNEL:
            risk_factors.append("Channel - different moderation rules")
            risk_score += 1
        elif chat.type == Chat.GROUP:
            risk_factors.append("Basic group - limited features")
            risk_score += 1
        
        # Check if group has username (public groups have different risks)
        if hasattr(chat, 'username') and chat.username:
            risk_factors.append("Public group/channel - higher visibility")
            risk_score += 2
        
        # Determine risk level
        if risk_score >= 5:
            risk_level = "danger"
        elif risk_score >= 3:
            risk_level = "risk"
        else:
            risk_level = "safe"
        
        # Generate purpose description
        purpose_description = f"This {chat.type} has {member_count} members. "
        if risk_factors:
            purpose_description += f"Key factors: {', '.join(risk_factors[:3])}."
        else:
            purpose_description += "No major risk factors detected."
        
        return {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "risk_factors": risk_factors,
            "purpose_description": purpose_description,
            "member_count": member_count
        }
    
    async def send_owner_notification(self, context: ContextTypes.DEFAULT_TYPE, 
                                    chat: Chat, analysis: Dict, event_type: str):
        """Send notification to bot owner"""
        try:
            if not self.owner_id:
                logger.info("ℹ️ Owner notification skipped - OWNER_ID not set")
                return
                
            chat_title = getattr(chat, 'title', 'Unknown Chat')
            
            message = f"🤖 <b>Bot {event_type}</b>\n\n"
            message += f"📋 <b>Group:</b> {chat_title}\n"
            message += f"🆔 <b>ID:</b> {chat.id}\n"
            message += f"👥 <b>Type:</b> {chat.type}\n"
            message += f"🔢 <b>Members:</b> {analysis['member_count']}\n"
            message += f"⚠️ <b>Risk Level:</b> {analysis['risk_level'].upper()}\n"
            message += f"📊 <b>Risk Score:</b> {analysis['risk_score']}/7\n"
            
            if analysis['risk_factors']:
                message += f"🔍 <b>Risk Factors:</b>\n"
                for factor in analysis['risk_factors'][:5]:
                    message += f"   • {factor}\n"
            
            message += f"\n📝 <b>Analysis:</b>\n{analysis['purpose_description']}"
            
            await context.bot.send_message(
                chat_id=self.owner_id,
                text=message,
                parse_mode='HTML'
            )
            logger.info(f"✅ Sent owner notification: {event_type}")
        except Exception as e:
            logger.error(f"❌ Error sending owner notification: {e}")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - scan group and notify owner"""
        try:
            chat = update.effective_chat
            
            if chat.type in [Chat.GROUP, Chat.SUPERGROUP, Chat.CHANNEL]:
                # Get bot's role
                bot_role = await self.get_bot_role(chat, context)
                
                # Save group info
                await self.save_group_info(chat, bot_role)
                
                # Analyze group risk
                analysis = await self.analyze_group_risk(chat)
                
                # Update risk level in database
                await self.update_group_risk(chat.id, analysis['risk_level'], analysis['purpose_description'])
                
                # Send notification to owner
                await self.send_owner_notification(context, chat, analysis, "SCAN COMPLETED")
                
                # Respond in group
                response_text = (
                    f"✅ <b>Group Protection Scan Completed</b>\n\n"
                    f"⚠️ <b>Risk Level:</b> {analysis['risk_level'].upper()}\n"
                    f"👥 <b>Members:</b> {analysis['member_count']}\n"
                    f"📊 <b>Risk Score:</b> {analysis['risk_score']}/7\n"
                    f"🤖 <b>Bot Role:</b> {bot_role}\n\n"
                    f"Use /status for detailed analysis."
                )
                
                await update.message.reply_text(response_text, parse_mode='HTML')
                
            else:
                # Private chat
                help_text = (
                    "👋 <b>Group Protection Bot</b>\n\n"
                    "Add me to your group or channel and use /start to begin protection monitoring.\n\n"
                    "<b>Commands in Groups:</b>\n"
                    "/start - Scan group and start protection\n"
                    "/status - Check group status\n\n"
                    "<b>Private Commands:</b>\n"
                    "/list - Show all monitored groups\n"
                    "/help - Show this message"
                )
                await update.message.reply_text(help_text, parse_mode='HTML')
                
        except Exception as e:
            logger.error(f"❌ Error in start command: {e}")
            error_msg = "❌ Error processing command. Please try again or check bot permissions."
            await update.message.reply_text(error_msg)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - check group status"""
        try:
            chat = update.effective_chat
            
            if chat.type in [Chat.GROUP, Chat.SUPERGROUP, Chat.CHANNEL]:
                # Get current analysis
                analysis = await self.analyze_group_risk(chat)
                
                # Get bot role
                bot_role = await self.get_bot_role(chat, context)
                
                # Get risk emoji
                risk_emoji = "✅" if analysis['risk_level'] == 'safe' else "⚠️" if analysis['risk_level'] == 'risk' else "🚨"
                
                chat_title = getattr(chat, 'title', 'Unknown Chat')
                
                status_message = f"📊 <b>Group Status Report</b> {risk_emoji}\n\n"
                status_message += f"🏷️ <b>Name:</b> {chat_title}\n"
                status_message += f"🆔 <b>ID:</b> {chat.id}\n"
                status_message += f"👥 <b>Type:</b> {chat.type}\n"
                status_message += f"🔢 <b>Members:</b> {analysis['member_count']}\n"
                status_message += f"🤖 <b>Bot Role:</b> {bot_role}\n"
                status_message += f"⚠️ <b>Risk Level:</b> {analysis['risk_level'].upper()}\n"
                status_message += f"📊 <b>Risk Score:</b> {analysis['risk_score']}/7\n\n"
                status_message += f"📝 <b>Analysis:</b>\n{analysis['purpose_description']}\n\n"
                
                # Status summary
                if analysis['risk_level'] == 'safe':
                    status_message += "✅ <b>Status: SAFE</b> - No immediate threats detected"
                elif analysis['risk_level'] == 'risk':
                    status_message += "⚠️ <b>Status: RISK</b> - Monitor group activity regularly"
                else:
                    status_message += "🚨 <b>Status: DANGER</b> - Immediate attention recommended"
                
                await update.message.reply_text(status_message, parse_mode='HTML')
            else:
                await update.message.reply_text("❌ This command can only be used in groups or channels.")
                
        except Exception as e:
            logger.error(f"❌ Error in status command: {e}")
            await update.message.reply_text("❌ Error checking group status. Please ensure I have necessary permissions.")
    
    async def list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list command - show all groups/channels bot is in"""
        try:
            # This command should only work in private chats
            if update.effective_chat.type != Chat.PRIVATE:
                await update.message.reply_text("❌ This command can only be used in private chat with the bot.")
                return
            
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT chat_id, chat_title, chat_type, member_count, bot_role, risk_level, updated_at
                FROM groups 
                ORDER BY updated_at DESC
            ''')
            
            groups = cursor.fetchall()
            conn.close()
            
            if not groups:
                await update.message.reply_text("🤖 Bot is not monitoring any groups or channels yet.")
                return
            
            list_message = "📋 <b>Monitored Groups & Channels</b>\n\n"
            
            for i, group in enumerate(groups, 1):
                chat_id, title, chat_type, members, bot_role, risk_level, updated = group
                
                # Risk emoji
                risk_emoji = "✅" if risk_level == 'safe' else "⚠️" if risk_level == 'risk' else "🚨"
                
                # Format update time
                if updated:
                    updated_str = str(updated)[:10]
                else:
                    updated_str = "Unknown"
                
                display_title = title if title else f"Chat {chat_id}"
                
                list_message += f"{i}. {risk_emoji} <b>{display_title}</b>\n"
                list_message += f"   🆔: {chat_id} | 👥: {chat_type}\n"
                list_message += f"   🔢: {members} members | 🤖: {bot_role}\n"
                list_message += f"   ⚠️: {risk_level.upper() if risk_level else 'UNKNOWN'} | 📅: {updated_str}\n\n"
            
            list_message += f"<i>Total: {len(groups)} groups/channels monitored</i>"
            
            await update.message.reply_text(list_message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"❌ Error in list command: {e}")
            await update.message.reply_text("❌ Error retrieving group list. Please try again later.")
    
    async def update_group_risk(self, chat_id: int, risk_level: str, purpose: str):
        """Update group risk level in database"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE groups 
                SET risk_level = ?, purpose_description = ?, updated_at = datetime('now')
                WHERE chat_id = ?
            ''', (risk_level, purpose, chat_id))
            
            conn.commit()
            conn.close()
            logger.info(f"✅ Updated risk level for chat {chat_id}: {risk_level}")
            return True
        except Exception as e:
            logger.error(f"❌ Error updating group risk: {e}")
            return False
    
    async def chat_member_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bot being added to groups/channels"""
        try:
            my_chat_member = update.my_chat_member
            if my_chat_member:
                chat = my_chat_member.chat
                old_status = my_chat_member.old_chat_member.status
                new_status = my_chat_member.new_chat_member.status
                
                logger.info(f"🔄 Bot status changed: {old_status} -> {new_status} in {getattr(chat, 'title', 'Unknown')}")
                
                # Bot was added to a group/channel
                if old_status == 'left' and new_status in ['member', 'administrator']:
                    bot_role = "admin" if new_status == 'administrator' else "member"
                    
                    # Save group info
                    await self.save_group_info(chat, bot_role)
                    
                    # Analyze group risk
                    analysis = await self.analyze_group_risk(chat)
                    
                    # Update risk level
                    await self.update_group_risk(chat.id, analysis['risk_level'], analysis['purpose_description'])
                    
                    # Send notification to owner
                    await self.send_owner_notification(context, chat, analysis, "ADDED TO GROUP")
                    
                    # Send welcome message
                    welcome_text = (
                        f"🤖 <b>Group Protection Bot Activated</b>\n\n"
                        f"I will monitor this {chat.type} for potential risks and provide security analysis.\n\n"
                        f"<b>Initial Scan Results:</b>\n"
                        f"⚠️ Risk Level: {analysis['risk_level'].upper()}\n"
                        f"📊 Risk Score: {analysis['risk_score']}/7\n"
                        f"👥 Members: {analysis['member_count']}\n\n"
                        f"<b>Commands:</b>\n"
                        f"/status - Check current status\n"
                        f"/start - Rescan group"
                    )
                    
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=welcome_text,
                        parse_mode='HTML'
                    )
                    logger.info(f"✅ Bot successfully added to {getattr(chat, 'title', 'Unknown')}")
                
                # Bot was removed from group/channel
                elif new_status == 'left' and old_status in ['member', 'administrator']:
                    # Notify owner about removal
                    if self.owner_id:
                        try:
                            await context.bot.send_message(
                                chat_id=self.owner_id,
                                text=f"❌ Bot was removed from:\n"
                                     f"Group: {getattr(chat, 'title', 'Unknown')}\n"
                                     f"ID: {chat.id}\n"
                                     f"Type: {chat.type}"
                            )
                        except Exception as e:
                            logger.error(f"❌ Error sending removal notification: {e}")
                    
                    logger.info(f"❌ Bot removed from {getattr(chat, 'title', 'Unknown')} (ID: {chat.id})")
        
        except Exception as e:
            logger.error(f"❌ Error in chat member handler: {e}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = (
            "🤖 <b>Group Protection Bot Commands</b>\n\n"
            "<b>Group Commands:</b>\n"
            "/start - Scan group and start protection monitoring\n"
            "/status - Check current group status and risk analysis\n\n"
            "<b>Private Commands:</b>\n"
            "/list - List all monitored groups and channels\n"
            "/help - Show this help message\n\n"
            "<b>Features:</b>\n"
            "• Automatic risk assessment\n"
            "• Real-time monitoring\n"
            "• Owner notifications\n"
            "• Multi-group support"
        )
        
        await update.message.reply_text(help_text, parse_mode='HTML')
    
    def setup_handlers(self):
        """Setup bot command handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("list", self.list_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Chat member handler (for bot being added/removed from groups)
        self.application.add_handler(ChatMemberHandler(self.chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
        
        # Set bot commands for menu
        commands = [
            BotCommand("start", "Start bot and scan group"),
            BotCommand("status", "Check group status and risk level"),
            BotCommand("list", "List all monitored groups/channels"),
            BotCommand("help", "Show help information")
        ]
        
        async def set_commands(app):
            try:
                await app.bot.set_my_commands(commands)
                logger.info("✅ Bot commands set successfully")
            except Exception as e:
                logger.error(f"❌ Error setting bot commands: {e}")
        
        self.application.post_init = set_commands
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
        
        logger.info("✅ Bot handlers setup completed")
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors in the bot"""
        logger.error(f"🚨 Bot error: {context.error}", exc_info=context.error)
    
    def run(self):
        """Start the bot"""
        logger.info("🚀 Starting Group Protection Bot...")
        logger.info("📊 Bot configuration:")
        logger.info(f"   - Owner ID: {self.owner_id}")
        logger.info(f"   - Database: SQLite (groups.db)")
        logger.info("✅ Bot is ready and listening for updates...")
        
        # Start polling
        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

def main():
    """Main function to run the bot"""
    try:
        logger.info("🔧 Initializing Group Protection Bot...")
        bot = GroupProtectionBot()
        bot.run()
    except Exception as e:
        logger.error(f"💥 Failed to start bot: {e}")
        # Exit with error code for Render to restart
        raise

if __name__ == "__main__":
    main()
