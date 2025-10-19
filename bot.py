import os
import logging
import asyncio
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

# Try different PostgreSQL drivers
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_DRIVER = "psycopg2"
except ImportError as e:
    try:
        import pg8000
        from pg8000 import Connection
        POSTGRES_DRIVER = "pg8000"
        logging.info("Using pg8000 as PostgreSQL driver")
    except ImportError:
        logging.error("No PostgreSQL driver available. Install psycopg2 or pg8000")
        sys.exit(1)

from dotenv import load_dotenv
from telegram import (
    Update, 
    Chat, 
    User, 
    ChatMember, 
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
from telegram.error import TelegramError, BadRequest

# Try to load .env file (for local development)
try:
    load_dotenv()
except Exception:
    pass  # Ignore if no .env file (normal on Render)

class Config:
    """Configuration management with Render environment support"""
    
    @staticmethod
    def get_required_env(var_name: str) -> str:
        """Get required environment variable or raise informative error"""
        value = os.getenv(var_name)
        if not value:
            raise ValueError(
                f"❌ Required environment variable '{var_name}' is not set.\n"
                f"Please set it in your Render environment variables."
            )
        return value

    @staticmethod
    def get_optional_env(var_name: str, default: str = "") -> str:
        """Get optional environment variable"""
        return os.getenv(var_name, default)

    @classmethod
    def load_config(cls):
        """Load and validate all configuration"""
        config = {
            'BOT_TOKEN': cls.get_required_env('BOT_TOKEN'),
            'DATABASE_URL': cls.get_required_env('DATABASE_URL'),
            'OWNER_ID': cls.get_optional_env('OWNER_ID'),
            'OWNER_USERNAME': cls.get_optional_env('OWNER_USERNAME', ''),
            'LOG_LEVEL': cls.get_optional_env('LOG_LEVEL', 'INFO'),
        }
        
        # Validate OWNER_ID
        if not config['OWNER_ID']:
            raise ValueError("OWNER_ID environment variable is required")
        
        try:
            config['OWNER_ID'] = int(config['OWNER_ID'])
        except ValueError:
            raise ValueError("OWNER_ID must be a valid integer")
        
        return config

class DatabaseManager:
    """Manage database connections and operations with multiple driver support"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.driver = POSTGRES_DRIVER
        logging.info(f"Using database driver: {self.driver}")

    def get_connection(self):
        """Get database connection based on available driver"""
        try:
            if self.driver == "psycopg2":
                return psycopg2.connect(
                    self.database_url,
                    cursor_factory=RealDictCursor,
                    connect_timeout=10
                )
            elif self.driver == "pg8000":
                # Parse database URL for pg8000
                from urllib.parse import urlparse
                url = urlparse(self.database_url)
                
                # Extract connection parameters
                dbname = url.path[1:]  # Remove leading slash
                user = url.username
                password = url.password
                host = url.hostname
                port = url.port or 5432
                
                conn = pg8000.connect(
                    database=dbname,
                    user=user,
                    password=password,
                    host=host,
                    port=port,
                    timeout=10
                )
                return conn
        except Exception as e:
            logging.error(f"Database connection error with {self.driver}: {e}")
            raise

    async def execute_query(self, query: str, params: tuple = None) -> Any:
        """Execute a query with proper error handling"""
        conn = None
        try:
            conn = self.get_connection()
            
            if self.driver == "psycopg2":
                with conn.cursor() as cursor:
                    cursor.execute(query, params or ())
                    if query.strip().upper().startswith('SELECT'):
                        result = cursor.fetchall()
                    else:
                        conn.commit()
                        result = None
            
            elif self.driver == "pg8000":
                cursor = conn.cursor()
                cursor.execute(query, params or ())
                if query.strip().upper().startswith('SELECT'):
                    result = []
                    columns = [desc[0] for desc in cursor.description]
                    for row in cursor.fetchall():
                        result.append(dict(zip(columns, row)))
                else:
                    conn.commit()
                    result = None
                cursor.close()
            
            return result
            
        except Exception as e:
            logging.error(f"Query execution error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

class TelegramGroupProtectionBot:
    """Telegram bot for group protection optimized for Render"""
    
    def __init__(self):
        # Load configuration with proper error handling
        try:
            self.config = Config.load_config()
        except ValueError as e:
            logging.critical(f"Configuration error: {e}")
            sys.exit(1)
        
        # Initialize core attributes
        self.bot_token = self.config['BOT_TOKEN']
        self.database_url = self.config['DATABASE_URL']
        self.owner_id = self.config['OWNER_ID']
        self.owner_username = self.config['OWNER_USERNAME']
        
        # Setup logging
        self._setup_logging()
        
        # Initialize database manager
        self.db = DatabaseManager(self.database_url)
        
        # Risk patterns for detection
        self.suspicious_keywords = [
            'http://', 'https://', 't.me/', 'buy now', 'limited offer', 'click here',
            'earn money', 'make money', 'investment', 'bitcoin', 'crypto', 'free money'
        ]
        self.violent_words = [
            'kill', 'attack', 'bomb', 'violence', 'hurt', 'destroy', 'harm'
        ]
        
        # Track application instance
        self.application = None

    def _setup_logging(self):
        """Setup logging for Render environment"""
        log_level = getattr(logging, self.config['LOG_LEVEL'].upper(), logging.INFO)
        
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - [Render] - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        logging.info("🚀 Telegram Group Protection Bot starting...")

    async def initialize_database(self):
        """Initialize database tables and settings"""
        try:
            logging.info("🔄 Initializing database...")
            
            # Create tables if they don't exist
            tables_sql = [
                """
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
                """,
                """
                CREATE TABLE IF NOT EXISTS activities (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    user_id BIGINT,
                    activity_type VARCHAR(50) NOT NULL,
                    content TEXT,
                    risk_level VARCHAR(20) DEFAULT 'normal',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    alert_type VARCHAR(50) NOT NULL,
                    alert_message TEXT NOT NULL,
                    risk_level VARCHAR(20) NOT NULL,
                    resolved BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS bot_settings (
                    id SERIAL PRIMARY KEY,
                    owner_id BIGINT NOT NULL UNIQUE,
                    owner_username TEXT,
                    alert_enabled BOOLEAN DEFAULT TRUE
                )
                """
            ]
            
            for sql in tables_sql:
                await self.db.execute_query(sql)
            
            # Check if settings exist
            settings = await self.db.execute_query(
                "SELECT COUNT(*) as count FROM bot_settings"
            )
            
            if not settings or settings[0]['count'] == 0:
                await self.db.execute_query(
                    "INSERT INTO bot_settings (owner_id, owner_username) VALUES (%s, %s)",
                    (self.owner_id, self.owner_username)
                )
                logging.info("✅ Bot settings initialized in database")
            else:
                logging.info("✅ Bot settings already exist in database")
                
        except Exception as e:
            logging.error(f"❌ Database initialization error: {e}")
            raise

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            user = update.effective_user
            
            if update.message.chat.type == ChatType.PRIVATE:
                welcome_text = (
                    "🤖 **Group Protection Bot**\n\n"
                    "I'm here to protect your Telegram groups and channels from risks and violations.\n\n"
                    "**Commands:**\n"
                    "/start - Show this message\n"
                    "/scan - Perform live scan of the group\n"
                    "/status - Check group status\n"
                    "/groups - List all monitored groups\n"
                    "/alerts - Show recent alerts\n\n"
                    "Add me to your group/channel and make me admin to start protection!"
                )
                await update.message.reply_text(welcome_text, parse_mode='Markdown')
                
                # Notify owner about new user (if not owner)
                if user.id != self.owner_id:
                    await self.send_alert_to_owner(
                        f"🆕 New user started the bot:\n"
                        f"User: {user.first_name} (@{user.username or 'No username'})\n"
                        f"ID: {user.id}"
                    )
                else:
                    logging.info("Owner started the bot")
                    
        except Exception as e:
            logging.error(f"Error in start command: {e}")

    async def track_new_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Track when bot is added to a new group/channel"""
        try:
            if not update.my_chat_member:
                return
                
            chat_member_update: ChatMemberUpdated = update.my_chat_member
            chat = chat_member_update.chat
            old_status = chat_member_update.old_chat_member.status
            new_status = chat_member_update.new_chat_member.status
            
            # Bot was added to group/channel
            if (old_status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED] and 
                new_status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]):
                
                logging.info(f"Bot added to {chat.type}: {chat.title}")
                await self.add_group_to_database(chat)
                await self.send_group_added_alert(chat)
                
                # Send welcome message to group
                welcome_text = (
                    "🛡️ **Group Protection Activated!**\n\n"
                    "I will monitor this group for potential risks and violations.\n"
                    "Use /scan to perform a security scan.\n"
                    "Group owner will receive alerts about suspicious activities."
                )
                await context.bot.send_message(chat.id, welcome_text, parse_mode='Markdown')
                
        except Exception as e:
            logging.error(f"Error tracking new chat: {e}")

    async def add_group_to_database(self, chat: Chat):
        """Add group to database"""
        try:
            member_count = await self.get_chat_member_count(chat)
            
            await self.db.execute_query("""
                INSERT INTO groups (group_id, group_name, group_type, member_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (group_id) DO UPDATE SET
                group_name = EXCLUDED.group_name,
                member_count = EXCLUDED.member_count,
                is_active = TRUE
            """, (chat.id, chat.title, chat.type, member_count))
            
            logging.info(f"✅ Added/updated group in database: {chat.title}")
            
        except Exception as e:
            logging.error(f"Error adding group to database: {e}")

    async def get_chat_member_count(self, chat: Chat) -> int:
        """Safely get chat member count"""
        try:
            return await chat.get_member_count()
        except (TelegramError, BadRequest) as e:
            logging.warning(f"Could not get member count for {chat.id}: {e}")
            return 0

    async def send_group_added_alert(self, chat: Chat):
        """Send alert to owner when bot is added to a new group"""
        try:
            member_count = await self.get_chat_member_count(chat)
            alert_message = (
                f"✅ **Bot Added to New {chat.type.capitalize()}**\n\n"
                f"**Name:** {chat.title}\n"
                f"**ID:** `{chat.id}`\n"
                f"**Type:** {chat.type}\n"
                f"**Members:** {member_count}\n\n"
                f"Protection monitoring has been activated!"
            )
            await self.send_alert_to_owner(alert_message)
        except Exception as e:
            logging.error(f"Error sending group added alert: {e}")

    async def scan_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Perform live scan of the group"""
        try:
            chat = update.effective_chat
            
            if chat.type == ChatType.PRIVATE:
                await update.message.reply_text("This command can only be used in groups/channels.")
                return

            # Send scanning message
            scan_message = await update.message.reply_text("🔍 **Scanning group for risks...**")
            
            # Perform security checks
            risk_factors = await self.perform_security_scan(chat, context)
            
            # Update group status in database
            await self.update_group_status(chat, risk_factors)
            
            # Generate scan report
            report = await self.generate_scan_report(chat, risk_factors)
            
            # Update the scanning message with results
            await scan_message.edit_text(report, parse_mode='Markdown')
            
            # Send detailed report to owner
            await self.send_detailed_report_to_owner(chat, risk_factors)
            
            logging.info(f"✅ Security scan completed for {chat.title}")
            
        except Exception as e:
            logging.error(f"Scan error: {e}")
            error_msg = "❌ Error during scan. Please make sure I'm an admin with necessary permissions."
            if update.message:
                await update.message.reply_text(error_msg)

    async def perform_security_scan(self, chat: Chat, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
        """Perform comprehensive security scan"""
        risk_factors = {
            'suspicious_members': [],
            'recent_joins': 0,
            'bot_count': 0,
            'admin_issues': 0,
            'recent_alerts': 0,
            'member_count': 0,
            'risk_score': 0
        }
        
        try:
            # Get basic chat information
            risk_factors['member_count'] = await self.get_chat_member_count(chat)
            
            # Get recent members (limited for performance)
            try:
                async for member in chat.get_members(limit=30):
                    user = member.user
                    
                    # Check for suspicious members
                    if await self.is_suspicious_member(member):
                        risk_factors['suspicious_members'].append({
                            'id': user.id,
                            'username': user.username,
                            'first_name': user.first_name
                        })
                    
                    # Count bots
                    if user.is_bot:
                        risk_factors['bot_count'] += 1
                    
            except (TelegramError, BadRequest) as e:
                logging.warning(f"Could not scan members for {chat.id}: {e}")
                risk_factors['admin_issues'] += 1
            
            # Check admin permissions
            risk_factors['admin_issues'] = await self.check_admin_permissions(chat, context)
            
            # Get recent alerts from database
            risk_factors['recent_alerts'] = await self.get_recent_alerts_count(chat.id)
            
            # Calculate risk score
            risk_factors['risk_score'] = self.calculate_risk_score(risk_factors)
            
        except Exception as e:
            logging.error(f"Security scan error for chat {chat.id}: {e}")
        
        return risk_factors

    async def is_suspicious_member(self, member: ChatMember) -> bool:
        """Check if a member is suspicious"""
        try:
            user = member.user
            
            # No username
            if not user.username:
                return True
            
            # Suspicious username patterns
            suspicious_patterns = ['spam', 'bot', 'fake', 'clone']
            username = user.username.lower()
            if any(pattern in username for pattern in suspicious_patterns):
                return True
            
            return False
        except Exception as e:
            logging.error(f"Error checking suspicious member: {e}")
            return False

    async def check_admin_permissions(self, chat: Chat, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Check for admin permission issues"""
        issues = 0
        try:
            bot_member = await chat.get_member(context.bot.id)
            
            # Check if bot has necessary admin permissions
            if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
                issues += 1
                
        except (TelegramError, BadRequest) as e:
            logging.warning(f"Could not check admin permissions for {chat.id}: {e}")
            issues += 1
        
        return issues

    async def get_recent_alerts_count(self, group_id: int) -> int:
        """Get count of recent alerts for the group"""
        try:
            result = await self.db.execute_query(
                "SELECT COUNT(*) as count FROM alerts WHERE group_id = %s AND created_at > NOW() - INTERVAL '24 hours'",
                (group_id,)
            )
            return result[0]['count'] if result else 0
        except Exception as e:
            logging.error(f"Error getting recent alerts count: {e}")
            return 0

    def calculate_risk_score(self, risk_factors: Dict) -> int:
        """Calculate overall risk score (0-100)"""
        score = 0
        
        try:
            # Suspicious members weight
            score += len(risk_factors['suspicious_members']) * 10
            
            # Bot count weight
            if risk_factors['bot_count'] > 5:
                score += 15
            
            # Admin issues weight
            score += risk_factors['admin_issues'] * 10
            
            # Recent alerts weight
            score += risk_factors['recent_alerts'] * 3
            
            return min(score, 100)
        except Exception as e:
            logging.error(f"Error calculating risk score: {e}")
            return 50

    async def update_group_status(self, chat: Chat, risk_factors: Dict):
        """Update group status in database"""
        try:
            status = 'safe'
            if risk_factors['risk_score'] > 70:
                status = 'risk'
            elif risk_factors['risk_score'] > 30:
                status = 'warning'
            
            await self.db.execute_query("""
                UPDATE groups 
                SET status = %s, last_scan = NOW(), member_count = %s
                WHERE group_id = %s
            """, (status, risk_factors['member_count'], chat.id))
            
        except Exception as e:
            logging.error(f"Error updating group status: {e}")

    async def generate_scan_report(self, chat: Chat, risk_factors: Dict) -> str:
        """Generate scan report for the group"""
        try:
            status = '🟢 SAFE'
            if risk_factors['risk_score'] > 70:
                status = '🔴 HIGH RISK'
            elif risk_factors['risk_score'] > 30:
                status = '🟡 WARNING'
            
            report = (
                f"🛡️ **Security Scan Report**\n\n"
                f"**Group:** {chat.title}\n"
                f"**Status:** {status}\n"
                f"**Risk Score:** {risk_factors['risk_score']}/100\n\n"
                f"**Findings:**\n"
                f"• Members: {risk_factors['member_count']}\n"
                f"• Suspicious members: {len(risk_factors['suspicious_members'])}\n"
                f"• Bots detected: {risk_factors['bot_count']}\n"
                f"• Permission issues: {risk_factors['admin_issues']}\n"
                f"• Recent alerts: {risk_factors['recent_alerts']}\n\n"
            )
            
            if risk_factors['risk_score'] > 30:
                report += "⚠️ **Recommendations:**\n"
                if len(risk_factors['suspicious_members']) > 0:
                    report += "• Review suspicious members\n"
                if risk_factors['bot_count'] > 5:
                    report += "• Limit bot access\n"
                if risk_factors['admin_issues'] > 0:
                    report += "• Check bot admin permissions\n"
            
            return report
        except Exception as e:
            logging.error(f"Error generating scan report: {e}")
            return "❌ Error generating scan report. Please try again."

    async def send_detailed_report_to_owner(self, chat: Chat, risk_factors: Dict):
        """Send detailed report to owner"""
        try:
            detailed_report = (
                f"📊 **Detailed Scan Report**\n\n"
                f"**Group:** {chat.title}\n"
                f"**ID:** `{chat.id}`\n"
                f"**Risk Score:** {risk_factors['risk_score']}/100\n\n"
                f"**Analysis:**\n"
                f"• Total members: {risk_factors['member_count']}\n"
                f"• Suspicious members: {len(risk_factors['suspicious_members'])}\n"
                f"• Active bots: {risk_factors['bot_count']}\n"
                f"• Permission issues: {risk_factors['admin_issues']}\n"
                f"• Alerts in 24h: {risk_factors['recent_alerts']}\n"
            )
            
            await self.send_alert_to_owner(detailed_report)
        except Exception as e:
            logging.error(f"Error sending detailed report: {e}")

    async def list_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all monitored groups"""
        try:
            if update.effective_user.id != self.owner_id:
                await update.message.reply_text("❌ This command is only available for the bot owner.")
                return
            
            groups = await self.db.execute_query("""
                SELECT group_id, group_name, group_type, member_count, status, last_scan
                FROM groups WHERE is_active = TRUE ORDER BY created_at DESC
            """)
            
            if not groups:
                await update.message.reply_text("No groups are being monitored yet.")
                return
            
            response = "📋 **Monitored Groups**\n\n"
            total_members = 0
            
            for group in groups:
                status_icon = "🟢" if group['status'] == 'safe' else "🟡" if group['status'] == 'warning' else "🔴"
                last_scan = group['last_scan'].strftime("%Y-%m-%d %H:%M") if group['last_scan'] else "Never"
                
                response += (
                    f"{status_icon} **{group['group_name']}**\n"
                    f"Type: {group['group_type']} | Members: {group['member_count']}\n"
                    f"Status: {group['status'].upper()} | Last Scan: {last_scan}\n\n"
                )
                total_members += group['member_count']
            
            response += f"**Total:** {len(groups)} groups, {total_members} members"
            
            await update.message.reply_text(response, parse_mode='Markdown')
            
        except Exception as e:
            logging.error(f"Error listing groups: {e}")
            await update.message.reply_text("❌ Error retrieving group list.")

    async def show_alerts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show recent alerts"""
        try:
            if update.effective_user.id != self.owner_id:
                await update.message.reply_text("❌ This command is only available for the bot owner.")
                return
            
            alerts = await self.db.execute_query("""
                SELECT a.*, g.group_name 
                FROM alerts a 
                JOIN groups g ON a.group_id = g.group_id 
                WHERE a.resolved = FALSE
                ORDER BY a.created_at DESC 
                LIMIT 5
            """)
            
            if not alerts:
                await update.message.reply_text("No recent alerts.")
                return
            
            response = "🚨 **Recent Alerts**\n\n"
            
            for alert in alerts:
                risk_icon = "🔴" if alert['risk_level'] == 'high' else "🟡"
                response += (
                    f"{risk_icon} **{alert['group_name']}**\n"
                    f"Type: {alert['alert_type']}\n"
                    f"Message: {alert['alert_message'][:100]}...\n\n"
                )
            
            await update.message.reply_text(response, parse_mode='Markdown')
            
        except Exception as e:
            logging.error(f"Error showing alerts: {e}")
            await update.message.reply_text("❌ Error retrieving alerts.")

    async def monitor_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Monitor messages for suspicious content"""
        try:
            if not update.message or update.message.chat.type == ChatType.PRIVATE:
                return
            
            message = update.message
            chat = message.chat
            user = message.from_user
            
            # Skip if user is bot itself
            if user and user.id == context.bot.id:
                return
            
            # Check for suspicious content
            if message.text:
                suspicious_patterns = []
                text = message.text.lower()
                
                # Spam patterns
                if any(keyword in text for keyword in self.suspicious_keywords):
                    suspicious_patterns.append('spam_links')
                
                # Violent content
                if any(word in text for word in self.violent_words):
                    suspicious_patterns.append('violent_content')
                
                if suspicious_patterns:
                    await self.log_suspicious_activity(chat, user, message, suspicious_patterns)
                    
                    # Send alert to owner
                    alert_msg = (
                        f"🚨 **Suspicious Activity**\n\n"
                        f"**Group:** {chat.title}\n"
                        f"**User:** @{user.username or 'No username'}\n"
                        f"**Patterns:** {', '.join(suspicious_patterns)}\n"
                        f"**Time:** {datetime.now().strftime('%H:%M')}"
                    )
                    await self.send_alert_to_owner(alert_msg)
                
        except Exception as e:
            logging.error(f"Error monitoring message: {e}")

    async def log_suspicious_activity(self, chat: Chat, user: User, message, patterns: List[str]):
        """Log suspicious activity to database"""
        try:
            content = message.text[:500] if message.text else 'Media message'
            
            # Log activity
            await self.db.execute_query("""
                INSERT INTO activities (group_id, user_id, activity_type, content, risk_level)
                VALUES (%s, %s, %s, %s, %s)
            """, (chat.id, user.id, 'suspicious_message', content, 'suspicious'))
            
            # Create alert
            await self.db.execute_query("""
                INSERT INTO alerts (group_id, alert_type, alert_message, risk_level)
                VALUES (%s, %s, %s, %s)
            """, (chat.id, 'suspicious_message', 
                  f"Suspicious message from @{user.username or 'No username'}", 
                  'medium'))
            
        except Exception as e:
            logging.error(f"Error logging activity: {e}")

    async def send_alert_to_owner(self, message: str):
        """Send alert message to owner"""
        try:
            if self.application:
                await self.application.bot.send_message(
                    chat_id=self.owner_id,
                    text=message,
                    parse_mode='Markdown'
                )
        except Exception as e:
            logging.error(f"Error sending alert to owner: {e}")

    async def get_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check current group status"""
        try:
            chat = update.effective_chat
            
            if chat.type == ChatType.PRIVATE:
                await update.message.reply_text("This command can only be used in groups/channels.")
                return
            
            group_data = await self.db.execute_query(
                "SELECT status, last_scan, member_count FROM groups WHERE group_id = %s",
                (chat.id,)
            )
            
            if not group_data:
                await update.message.reply_text("Group not monitored. Use /scan to start monitoring.")
                return
            
            group = group_data[0]
            status_icon = "🟢" if group['status'] == 'safe' else "🟡" if group['status'] == 'warning' else "🔴"
            last_scan = group['last_scan'].strftime("%Y-%m-%d %H:%M") if group['last_scan'] else "Never"
            
            status_msg = (
                f"{status_icon} **Group Status**\n\n"
                f"**Name:** {chat.title}\n"
                f"**Status:** {group['status'].upper()}\n"
                f"**Members:** {group['member_count']}\n"
                f"**Last Scan:** {last_scan}\n\n"
                f"Use /scan for detailed security check."
            )
            
            await update.message.reply_text(status_msg, parse_mode='Markdown')
            
        except Exception as e:
            logging.error(f"Error getting status: {e}")
            await update.message.reply_text("❌ Error retrieving status.")

    def setup_handlers(self, application: Application):
        """Setup bot handlers"""
        # Command handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("scan", self.scan_group))
        application.add_handler(CommandHandler("status", self.get_status))
        application.add_handler(CommandHandler("groups", self.list_groups))
        application.add_handler(CommandHandler("alerts", self.show_alerts))
        
        # Track when bot is added to groups
        application.add_handler(ChatMemberHandler(self.track_new_chat, ChatMemberHandler.MY_CHAT_MEMBER))
        
        # Monitor messages
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, 
            self.monitor_messages
        ))

    async def setup_bot_commands(self, application: Application):
        """Setup bot commands menu"""
        try:
            commands = [
                BotCommand("start", "Start the bot"),
                BotCommand("scan", "Scan group for risks"),
                BotCommand("status", "Check group status"),
                BotCommand("groups", "List monitored groups"),
                BotCommand("alerts", "Show recent alerts"),
            ]
            await application.bot.set_my_commands(commands)
        except Exception as e:
            logging.error(f"Error setting up bot commands: {e}")

    async def error_handler(self, update: Update, context: CallbackContext):
        """Handle errors in telegram bot"""
        try:
            logging.error(f"Exception while handling an update: {context.error}")
        except Exception as e:
            logging.error(f"Error in error handler: {e}")

    async def run(self):
        """Run the bot"""
        try:
            logging.info("🚀 Starting Telegram Bot...")
            
            # Create application
            self.application = Application.builder().token(self.bot_token).build()
            
            # Initialize database
            await self.initialize_database()
            
            # Setup handlers
            self.setup_handlers(self.application)
            
            # Setup bot commands
            await self.setup_bot_commands(self.application)
            
            # Add error handler
            self.application.add_error_handler(self.error_handler)
            
            # Send startup notification
            await self.send_alert_to_owner("🤖 **Bot Started Successfully**\n\nThe group protection bot is now running and ready!")
            
            logging.info("✅ Bot started successfully - now polling for updates...")
            
            # Start polling
            await self.application.run_polling(
                allowed_updates=["message", "edited_message", "my_chat_member"],
                drop_pending_updates=True
            )
            
        except Exception as e:
            logging.critical(f"❌ Fatal error starting bot: {e}")
            raise

# Main execution
if __name__ == '__main__':
    # Add startup delay for Render
    time.sleep(2)
    
    try:
        bot = TelegramGroupProtectionBot()
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.critical(f"Fatal error: {e}")
        sys.exit(1)
