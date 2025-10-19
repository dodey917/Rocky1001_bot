import os
import logging
import asyncio
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from telegram import (
    Update, 
    Chat, 
    User, 
    ChatMember, 
    BotCommand,
    ChatMemberUpdated,
    ChatPermissions,
    Message
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
from telegram.constants import ChatType, ChatMemberStatus, ParseMode
from telegram.error import TelegramError, BadRequest, Forbidden

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    """Database management with connection pooling"""
    
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")

    def get_connection(self):
        """Get database connection"""
        try:
            conn = psycopg2.connect(
                self.database_url,
                cursor_factory=RealDictCursor,
                connect_timeout=10
            )
            return conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise

    def execute_query(self, query: str, params: tuple = None, fetch: bool = False):
        """Execute database query"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params or ())
                if fetch:
                    if query.strip().upper().startswith('SELECT'):
                        result = cursor.fetchall()
                    else:
                        result = None
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
    """Complete Group Protection Bot with all requested features"""
    
    def __init__(self):
        # Load configuration
        self.bot_token = os.getenv('BOT_TOKEN')
        if not self.bot_token:
            raise ValueError("BOT_TOKEN environment variable is required")
        
        self.owner_id = int(os.getenv('OWNER_ID', 0))
        if not self.owner_id:
            raise ValueError("OWNER_ID environment variable is required")
        
        self.owner_username = os.getenv('OWNER_USERNAME', '')
        
        # Initialize database
        self.db = DatabaseManager()
        
        # Risk detection patterns
        self.spam_keywords = [
            'http://', 'https://', 't.me/', 'buy now', 'limited offer', 'click here',
            'earn money', 'make money', 'investment', 'bitcoin', 'crypto', 'free money',
            'discount', 'offer', 'promotion', 'make $', 'earn $', 'work from home'
        ]
        
        self.violent_keywords = [
            'kill', 'attack', 'bomb', 'violence', 'hurt', 'destroy', 'harm',
            'fight', 'war', 'weapon', 'gun', 'shoot', 'murder'
        ]
        
        self.suspicious_patterns = [
            'spam', 'bot', 'fake', 'clone', 'user', 'account', 'official'
        ]
        
        logger.info("🤖 Group Protection Bot initialized successfully")

    def initialize_database(self):
        """Initialize database tables"""
        try:
            # Create tables if they don't exist
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS groups (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT UNIQUE NOT NULL,
                    group_name TEXT NOT NULL,
                    group_type VARCHAR(20) NOT NULL,
                    member_count INTEGER DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'safe',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_scan TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS group_members (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_bot BOOLEAN DEFAULT FALSE,
                    status VARCHAR(20) DEFAULT 'active',
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(group_id, user_id)
                )
            """)
            
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS activities (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    user_id BIGINT,
                    activity_type VARCHAR(50) NOT NULL,
                    content TEXT,
                    risk_level VARCHAR(20) DEFAULT 'normal',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    alert_type VARCHAR(50) NOT NULL,
                    alert_message TEXT NOT NULL,
                    risk_level VARCHAR(20) NOT NULL,
                    resolved BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    id SERIAL PRIMARY KEY,
                    owner_id BIGINT NOT NULL UNIQUE,
                    owner_username TEXT,
                    alert_enabled BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Initialize bot settings
            self.db.execute_query("""
                INSERT INTO bot_settings (owner_id, owner_username) 
                VALUES (%s, %s)
                ON CONFLICT (owner_id) DO UPDATE SET
                owner_username = EXCLUDED.owner_username
            """, (self.owner_id, self.owner_username))
            
            logger.info("✅ Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            raise

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            user = update.effective_user
            
            if update.message.chat.type == ChatType.PRIVATE:
                welcome_message = (
                    "🤖 **Group Protection Bot**\n\n"
                    "I protect your Telegram groups and channels from risks and policy violations.\n\n"
                    "**Features:**\n"
                    "• Live security scanning\n"
                    "• Real-time risk alerts\n"
                    "• Suspicious activity detection\n"
                    "• Group status monitoring\n"
                    "• Owner notifications\n\n"
                    "**Commands:**\n"
                    "/start - Show this message\n"
                    "/scan - Perform live security scan\n"
                    "/status - Check group status\n"
                    "/groups - List all monitored groups\n"
                    "/alerts - Show recent alerts\n\n"
                    "Add me to your group/channel and make me admin to start protection!"
                )
                
                await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)
                
                # Notify owner if it's a new user
                if user.id != self.owner_id:
                    await self.send_owner_alert(
                        f"🆕 New User Started Bot\n"
                        f"Name: {user.first_name}\n"
                        f"Username: @{user.username or 'No username'}\n"
                        f"ID: {user.id}"
                    )
            else:
                await update.message.reply_text(
                    "🤖 Group Protection Bot is active!\n"
                    "Use /scan to check group security or /status for current status.",
                    parse_mode=ParseMode.MARKDOWN
                )
                
        except Exception as e:
            logger.error(f"Start command error: {e}")

    async def handle_bot_added(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bot being added to groups/channels"""
        try:
            if not update.my_chat_member:
                return
                
            chat_member_update = update.my_chat_member
            chat = chat_member_update.chat
            old_status = chat_member_update.old_chat_member.status
            new_status = chat_member_update.new_chat_member.status
            
            # Bot was added to a group/channel
            if (old_status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED] and 
                new_status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]):
                
                logger.info(f"Bot added to {chat.type}: {chat.title}")
                
                # Add group to database
                await self.add_group_to_monitoring(chat)
                
                # Send welcome message
                welcome_text = (
                    "🛡️ **Group Protection Activated!**\n\n"
                    "I will now monitor this group for:\n"
                    "• Security risks\n"
                    "• Policy violations\n"
                    "• Suspicious activities\n"
                    "• Spam and malicious content\n\n"
                    "Use /scan for security analysis\n"
                    "Use /status for current status\n\n"
                    "Owner will receive real-time alerts!"
                )
                
                try:
                    await context.bot.send_message(
                        chat.id,
                        welcome_text,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.warning(f"Could not send welcome message: {e}")
                    
        except Exception as e:
            logger.error(f"Bot added handler error: {e}")

    async def add_group_to_monitoring(self, chat: Chat):
        """Add group to monitoring system"""
        try:
            member_count = await self.get_chat_member_count(chat)
            
            self.db.execute_query("""
                INSERT INTO groups (group_id, group_name, group_type, member_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (group_id) DO UPDATE SET
                group_name = EXCLUDED.group_name,
                member_count = EXCLUDED.member_count,
                is_active = TRUE,
                last_scan = NULL
            """, (chat.id, chat.title, chat.type, member_count))
            
            # Send alert to owner
            await self.send_owner_alert(
                f"✅ **Bot Added to New {chat.type.capitalize()}**\n\n"
                f"**Name:** {chat.title}\n"
                f"**ID:** `{chat.id}`\n"
                f"**Type:** {chat.type}\n"
                f"**Members:** {member_count}\n\n"
                f"Protection monitoring has been activated!"
            )
            
            logger.info(f"Added group to monitoring: {chat.title}")
            
        except Exception as e:
            logger.error(f"Add group to monitoring error: {e}")

    async def get_chat_member_count(self, chat: Chat) -> int:
        """Get chat member count safely"""
        try:
            return await chat.get_member_count()
        except (TelegramError, BadRequest, Forbidden) as e:
            logger.warning(f"Could not get member count for {chat.id}: {e}")
            return 0

    async def scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Perform live security scan of the group"""
        try:
            chat = update.effective_chat
            
            if chat.type == ChatType.PRIVATE:
                await update.message.reply_text(
                    "This command can only be used in groups or channels.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            # Send scanning message
            scan_message = await update.message.reply_text(
                "🔍 **Starting Comprehensive Security Scan...**\n"
                "Scanning members, messages, and activities...",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Perform comprehensive scan
            scan_results = await self.perform_comprehensive_scan(chat, context)
            
            # Update group status
            await self.update_group_status(chat, scan_results)
            
            # Generate and send report
            report = self.generate_scan_report(chat, scan_results)
            await scan_message.edit_text(report, parse_mode=ParseMode.MARKDOWN)
            
            # Send detailed report to owner
            await self.send_detailed_scan_report_to_owner(chat, scan_results)
            
            logger.info(f"Security scan completed for {chat.title}")
            
        except Exception as e:
            logger.error(f"Scan command error: {e}")
            error_msg = (
                "❌ **Scan Failed**\n\n"
                "Please ensure I have:\n"
                "• Admin permissions\n"
                "• Can view messages\n"
                "• Can manage users\n"
                "Then try again."
            )
            await update.message.reply_text(error_msg, parse_mode=ParseMode.MARKDOWN)

    async def perform_comprehensive_scan(self, chat: Chat, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
        """Perform comprehensive security scan"""
        scan_data = {
            'total_members': 0,
            'suspicious_members': [],
            'bot_count': 0,
            'recent_activities': 0,
            'admin_permissions_ok': False,
            'risk_factors': [],
            'risk_score': 0,
            'scan_timestamp': datetime.now()
        }
        
        try:
            # Check admin permissions
            scan_data['admin_permissions_ok'] = await self.check_bot_permissions(chat, context)
            if not scan_data['admin_permissions_ok']:
                scan_data['risk_factors'].append('insufficient_permissions')
                scan_data['risk_score'] += 30
            
            # Scan members (limited for performance)
            member_scan = await self.scan_group_members(chat, limit=50)
            scan_data.update(member_scan)
            
            # Check recent activities
            recent_activities = self.db.execute_query(
                "SELECT COUNT(*) as count FROM activities WHERE group_id = %s AND timestamp > NOW() - INTERVAL '24 hours'",
                (chat.id,),
                fetch=True
            )
            scan_data['recent_activities'] = recent_activities[0]['count'] if recent_activities else 0
            
            # Check recent alerts
            recent_alerts = self.db.execute_query(
                "SELECT COUNT(*) as count FROM alerts WHERE group_id = %s AND created_at > NOW() - INTERVAL '24 hours' AND risk_level = 'high'",
                (chat.id,),
                fetch=True
            )
            alert_count = recent_alerts[0]['count'] if recent_alerts else 0
            if alert_count > 0:
                scan_data['risk_factors'].append(f'recent_high_risk_alerts_{alert_count}')
                scan_data['risk_score'] += alert_count * 10
            
            # Calculate final risk score
            scan_data['risk_score'] = min(scan_data['risk_score'], 100)
            
        except Exception as e:
            logger.error(f"Comprehensive scan error: {e}")
            scan_data['risk_factors'].append('scan_error')
            scan_data['risk_score'] += 20
            
        return scan_data

    async def check_bot_permissions(self, chat: Chat, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Check if bot has necessary admin permissions"""
        try:
            bot_member = await chat.get_member(context.bot.id)
            if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
                return False
            
            # Check essential permissions
            if (not bot_member.can_delete_messages or 
                not bot_member.can_restrict_members or 
                not bot_member.can_invite_users):
                return False
                
            return True
        except Exception as e:
            logger.warning(f"Permission check error: {e}")
            return False

    async def scan_group_members(self, chat: Chat, limit: int = 50) -> Dict[str, Any]:
        """Scan group members for risks"""
        member_data = {
            'total_members': 0,
            'suspicious_members': [],
            'bot_count': 0
        }
        
        try:
            member_count = 0
            suspicious_count = 0
            bot_count = 0
            
            async for member in chat.get_members(limit=limit):
                member_count += 1
                user = member.user
                
                # Update member in database
                self.db.execute_query("""
                    INSERT INTO group_members (group_id, user_id, username, first_name, last_name, is_bot)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (group_id, user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    last_seen = CURRENT_TIMESTAMP
                """, (chat.id, user.id, user.username, user.first_name, user.last_name, user.is_bot))
                
                # Check for suspicious members
                if await self.is_suspicious_member(user):
                    suspicious_count += 1
                    member_data['suspicious_members'].append({
                        'id': user.id,
                        'username': user.username,
                        'first_name': user.first_name
                    })
                
                # Count bots
                if user.is_bot:
                    bot_count += 1
            
            member_data['total_members'] = member_count
            member_data['bot_count'] = bot_count
            
            # Add risk factors based on member analysis
            if suspicious_count > 5:
                member_data['risk_factors'] = ['many_suspicious_members']
            elif suspicious_count > 0:
                member_data['risk_factors'] = ['some_suspicious_members']
                
            if bot_count > 3:
                member_data['risk_factors'] = member_data.get('risk_factors', []) + ['many_bots']
                
        except Exception as e:
            logger.error(f"Member scan error: {e}")
            
        return member_data

    async def is_suspicious_member(self, user: User) -> bool:
        """Check if a member is suspicious"""
        try:
            # No username
            if not user.username:
                return True
            
            username = user.username.lower()
            
            # Suspicious username patterns
            if any(pattern in username for pattern in self.suspicious_patterns):
                return True
            
            # Very new accounts (rough check)
            if user.id > 7000000000:  # Rough indicator of newer accounts
                return True
            
            return False
        except Exception as e:
            logger.error(f"Suspicious member check error: {e}")
            return False

    async def update_group_status(self, chat: Chat, scan_results: Dict[str, Any]):
        """Update group status based on scan results"""
        try:
            status = 'safe'
            if scan_results['risk_score'] > 70:
                status = 'high_risk'
            elif scan_results['risk_score'] > 30:
                status = 'medium_risk'
            
            self.db.execute_query("""
                UPDATE groups 
                SET status = %s, last_scan = %s, member_count = %s
                WHERE group_id = %s
            """, (status, scan_results['scan_timestamp'], scan_results.get('total_members', 0), chat.id))
            
        except Exception as e:
            logger.error(f"Update group status error: {e}")

    def generate_scan_report(self, chat: Chat, scan_results: Dict[str, Any]) -> str:
        """Generate scan report for the group"""
        risk_score = scan_results['risk_score']
        
        if risk_score > 70:
            status_emoji = "🔴"
            status_text = "HIGH RISK"
            action = "Immediate attention required!"
        elif risk_score > 30:
            status_emoji = "🟡"
            status_text = "MEDIUM RISK"
            action = "Monitor closely"
        else:
            status_emoji = "🟢"
            status_text = "SAFE"
            action = "No immediate action needed"
        
        report = (
            f"🛡️ **Security Scan Report**\n\n"
            f"**Group:** {chat.title}\n"
            f"**Status:** {status_emoji} {status_text}\n"
            f"**Risk Score:** {risk_score}/100\n\n"
            f"**Scan Results:**\n"
            f"• Members scanned: {scan_results.get('total_members', 0)}\n"
            f"• Suspicious members: {len(scan_results.get('suspicious_members', []))}\n"
            f"• Bots detected: {scan_results.get('bot_count', 0)}\n"
            f"• Recent activities: {scan_results.get('recent_activities', 0)}\n"
            f"• Admin permissions: {'✅ OK' if scan_results.get('admin_permissions_ok') else '❌ Issues'}\n\n"
        )
        
        if scan_results.get('risk_factors'):
            report += f"**Risk Factors:**\n"
            for factor in scan_results['risk_factors']:
                report += f"• {factor.replace('_', ' ').title()}\n"
            report += f"\n"
        
        report += f"**Action:** {action}"
        
        return report

    async def send_detailed_scan_report_to_owner(self, chat: Chat, scan_results: Dict[str, Any]):
        """Send detailed scan report to owner"""
        try:
            detailed_report = (
                f"📊 **Detailed Scan Report**\n\n"
                f"**Group:** {chat.title}\n"
                f"**ID:** `{chat.id}`\n"
                f"**Type:** {chat.type}\n"
                f"**Risk Score:** {scan_results['risk_score']}/100\n\n"
                f"**Comprehensive Analysis:**\n"
                f"• Total members scanned: {scan_results.get('total_members', 0)}\n"
                f"• Suspicious members found: {len(scan_results.get('suspicious_members', []))}\n"
                f"• Active bots: {scan_results.get('bot_count', 0)}\n"
                f"• Activities (24h): {scan_results.get('recent_activities', 0)}\n"
                f"• Admin permissions: {'✅ Optimal' if scan_results.get('admin_permissions_ok') else '❌ Limited'}\n\n"
            )
            
            if scan_results.get('suspicious_members'):
                detailed_report += "**Suspicious Members Sample:**\n"
                for member in scan_results['suspicious_members'][:5]:
                    detailed_report += f"• @{member['username'] or 'No username'} ({member['first_name']})\n"
                detailed_report += "\n"
            
            if scan_results.get('risk_factors'):
                detailed_report += "**Identified Risks:**\n"
                for risk in scan_results['risk_factors']:
                    detailed_report += f"• {risk.replace('_', ' ').title()}\n"
            
            await self.send_owner_alert(detailed_report)
            
        except Exception as e:
            logger.error(f"Detailed report error: {e}")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check current group status"""
        try:
            chat = update.effective_chat
            
            if chat.type == ChatType.PRIVATE:
                await update.message.reply_text(
                    "This command can only be used in groups or channels.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Get group status from database
            group_data = self.db.execute_query(
                "SELECT status, member_count, last_scan FROM groups WHERE group_id = %s",
                (chat.id,),
                fetch=True
            )
            
            if not group_data:
                await update.message.reply_text(
                    "This group is not being monitored yet. Use /scan to start protection.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            group = group_data[0]
            status_emoji = "🔴" if group['status'] == 'high_risk' else "🟡" if group['status'] == 'medium_risk' else "🟢"
            last_scan = group['last_scan'].strftime("%Y-%m-%d at %H:%M") if group['last_scan'] else "Never"
            
            status_message = (
                f"{status_emoji} **Group Status Report**\n\n"
                f"**Group:** {chat.title}\n"
                f"**Current Status:** {group['status'].upper().replace('_', ' ')}\n"
                f"**Members:** {group['member_count']}\n"
                f"**Last Security Scan:** {last_scan}\n\n"
                f"Use /scan for detailed security analysis\n"
                f"Use /groups to see all monitored groups"
            )
            
            await update.message.reply_text(status_message, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Status command error: {e}")

    async def groups_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all monitored groups with statistics"""
        try:
            if update.effective_user.id != self.owner_id:
                await update.message.reply_text(
                    "❌ This command is only available for the bot owner.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Get all monitored groups
            groups_data = self.db.execute_query(
                "SELECT group_name, group_type, member_count, status, last_scan FROM groups WHERE is_active = TRUE ORDER BY created_at DESC",
                fetch=True
            )
            
            if not groups_data:
                await update.message.reply_text(
                    "No groups are currently being monitored.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            total_groups = len(groups_data)
            total_members = sum(group['member_count'] for group in groups_data)
            high_risk_count = sum(1 for group in groups_data if group['status'] == 'high_risk')
            medium_risk_count = sum(1 for group in groups_data if group['status'] == 'medium_risk')
            safe_count = sum(1 for group in groups_data if group['status'] == 'safe')
            
            response = (
                f"📋 **Monitored Groups Overview**\n\n"
                f"**Summary:**\n"
                f"• Total Groups: {total_groups}\n"
                f"• Total Members: {total_members}\n"
                f"• 🔴 High Risk: {high_risk_count}\n"
                f"• 🟡 Medium Risk: {medium_risk_count}\n"
                f"• 🟢 Safe: {safe_count}\n\n"
                f"**Group Details:**\n"
            )
            
            for group in groups_data:
                status_emoji = "🔴" if group['status'] == 'high_risk' else "🟡" if group['status'] == 'medium_risk' else "🟢"
                last_scan = group['last_scan'].strftime("%m/%d %H:%M") if group['last_scan'] else "Never"
                
                response += (
                    f"{status_emoji} **{group['group_name']}**\n"
                    f"Type: {group['group_type']} | Members: {group['member_count']}\n"
                    f"Status: {group['status'].replace('_', ' ').title()} | Last Scan: {last_scan}\n\n"
                )
            
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Groups command error: {e}")

    async def alerts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show recent alerts"""
        try:
            if update.effective_user.id != self.owner_id:
                await update.message.reply_text(
                    "❌ This command is only available for the bot owner.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Get recent alerts
            alerts_data = self.db.execute_query("""
                SELECT a.alert_type, a.alert_message, a.risk_level, a.created_at, g.group_name 
                FROM alerts a 
                JOIN groups g ON a.group_id = g.group_id 
                WHERE a.resolved = FALSE
                ORDER BY a.created_at DESC 
                LIMIT 10
            """, fetch=True)
            
            if not alerts_data:
                await update.message.reply_text(
                    "No recent alerts. Everything looks good! 🎉",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            response = "🚨 **Recent Security Alerts**\n\n"
            
            for alert in alerts_data:
                risk_emoji = "🔴" if alert['risk_level'] == 'high' else "🟡" if alert['risk_level'] == 'medium' else "🔵"
                time_str = alert['created_at'].strftime("%m/%d %H:%M")
                
                response += (
                    f"{risk_emoji} **{alert['group_name']}**\n"
                    f"Type: {alert['alert_type'].replace('_', ' ').title()}\n"
                    f"Message: {alert['alert_message']}\n"
                    f"Time: {time_str}\n\n"
                )
            
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Alerts command error: {e}")

    async def monitor_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Monitor all messages for suspicious content"""
        try:
            if not update.message or update.message.chat.type == ChatType.PRIVATE:
                return
            
            message = update.message
            chat = message.chat
            user = message.from_user
            
            # Skip if message is from bot itself
            if user.id == context.bot.id:
                return
            
            # Log activity
            self.db.execute_query("""
                INSERT INTO activities (group_id, user_id, activity_type, content)
                VALUES (%s, %s, %s, %s)
            """, (chat.id, user.id, 'message', message.text or 'Media content'))
            
            # Check for suspicious content
            if message.text:
                detected_risks = await self.analyze_message_content(message.text, user)
                
                if detected_risks:
                    await self.handle_suspicious_activity(chat, user, message, detected_risks)
                    
        except Exception as e:
            logger.error(f"Message monitoring error: {e}")

    async def analyze_message_content(self, text: str, user: User) -> List[str]:
        """Analyze message content for risks"""
        risks = []
        text_lower = text.lower()
        
        # Check for spam links
        if any(keyword in text_lower for keyword in self.spam_keywords):
            risks.append('spam_content')
        
        # Check for violent content
        if any(keyword in text_lower for keyword in self.violent_keywords):
            risks.append('violent_content')
        
        # Check for excessive caps
        if len(text_lower) > 10:
            upper_count = sum(1 for char in text_lower if char.isupper())
            if upper_count / len(text_lower) > 0.7:
                risks.append('excessive_caps')
        
        # Check for repetitive content
        words = text_lower.split()
        if len(words) > 20 and len(set(words)) < 10:
            risks.append('repetitive_content')
        
        return risks

    async def handle_suspicious_activity(self, chat: Chat, user: User, message: Message, risks: List[str]):
        """Handle detected suspicious activity"""
        try:
            risk_level = 'high' if 'violent_content' in risks else 'medium'
            
            # Create alert
            self.db.execute_query("""
                INSERT INTO alerts (group_id, alert_type, alert_message, risk_level)
                VALUES (%s, %s, %s, %s)
            """, (
                chat.id,
                'suspicious_activity',
                f"Suspicious activity from @{user.username or 'No username'} - Detected: {', '.join(risks)}",
                risk_level
            ))
            
            # Log high-risk activity
            self.db.execute_query("""
                INSERT INTO activities (group_id, user_id, activity_type, content, risk_level)
                VALUES (%s, %s, %s, %s, %s)
            """, (chat.id, user.id, 'suspicious_activity', f"Risks: {', '.join(risks)}", risk_level))
            
            # Send immediate alert to owner
            alert_message = (
                f"🚨 **Suspicious Activity Detected**\n\n"
                f"**Group:** {chat.title}\n"
                f"**User:** @{user.username or 'No username'} (ID: {user.id})\n"
                f"**Detected Risks:** {', '.join(risks)}\n"
                f"**Content:** {message.text[:200] if message.text else 'Media message'}\n"
                f"**Risk Level:** {risk_level.upper()}\n"
                f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            await self.send_owner_alert(alert_message)
            
            logger.info(f"Alert sent for suspicious activity in {chat.title}")
            
        except Exception as e:
            logger.error(f"Suspicious activity handling error: {e}")

    async def send_owner_alert(self, message: str):
        """Send alert message to bot owner"""
        try:
            app = Application.builder().token(self.bot_token).build()
            await app.bot.send_message(
                chat_id=self.owner_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            await app.shutdown()
        except Exception as e:
            logger.error(f"Send owner alert error: {e}")

    def setup_handlers(self, application: Application):
        """Setup all bot handlers"""
        # Command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("scan", self.scan_command))
        application.add_handler(CommandHandler("status", self.status_command))
        application.add_handler(CommandHandler("groups", self.groups_command))
        application.add_handler(CommandHandler("alerts", self.alerts_command))
        
        # Chat member handler (bot added/removed from groups)
        application.add_handler(ChatMemberHandler(
            self.handle_bot_added, 
            ChatMemberHandler.MY_CHAT_MEMBER
        ))
        
        # Message handler (monitor all messages)
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUPS | filters.ChatType.CHANNELS),
            self.monitor_messages
        ))

    async def setup_bot_commands(self, application: Application):
        """Setup bot command menu"""
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("scan", "Perform security scan"),
            BotCommand("status", "Check group status"),
            BotCommand("groups", "List monitored groups (owner)"),
            BotCommand("alerts", "Show recent alerts (owner)"),
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
            # Initialize database
            self.initialize_database()
            
            # Create application
            application = Application.builder().token(self.bot_token).build()
            
            # Setup handlers
            self.setup_handlers(application)
            
            # Setup commands
            await self.setup_bot_commands(application)
            
            # Add error handler
            application.add_error_handler(self.error_handler)
            
            # Send startup notification
            await self.send_owner_alert(
                "🤖 **Group Protection Bot Started Successfully!**\n\n"
                "The bot is now running and ready to protect your groups and channels.\n\n"
                "Features activated:\n"
                "• Real-time monitoring\n"
                "• Security scanning\n"
                "• Risk detection\n"
                "• Alert system\n\n"
                "Add the bot to your groups and make it admin to start protection!"
            )
            
            logger.info("✅ Bot started successfully - Now polling for updates...")
            
            # Start polling
            await application.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "my_chat_member", "chat_member", "edited_message"]
            )
            
        except Exception as e:
            logger.critical(f"❌ Bot failed to start: {e}")
            raise

def main():
    """Main function"""
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
