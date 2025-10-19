import logging
import os
import datetime
import sys
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from sqlalchemy.orm import Session
from database import SessionLocal, init_db
from models import Group, GroupMember, Alert, GroupActivity

# Configure logging for Render
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout  # Ensure logs go to stdout for Render
)
logger = logging.getLogger(__name__)

def get_required_env(var_name):
    """Get required environment variable or raise informative error"""
    value = os.getenv(var_name)
    if not value:
        raise ValueError(f"{var_name} environment variable is required but not set")
    return value

# Get environment variables with proper error handling
try:
    TELEGRAM_BOT_TOKEN = get_required_env('TELEGRAM_BOT_TOKEN')
    OWNER_CHAT_ID = get_required_env('OWNER_CHAT_ID')
    logger.info("Environment variables loaded successfully")
except ValueError as e:
    logger.error(f"Configuration error: {e}")
    sys.exit(1)

class SecurityBot:
    def __init__(self):
        self.monitored_groups = {}
        self.init_database()
    
    def init_database(self):
        """Initialize database with error handling"""
        try:
            init_db()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            # Don't exit - the bot might still work without DB
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /start command"""
        try:
            user = update.effective_user
            logger.info(f"Start command received from user {user.id if user else 'unknown'}")
            
            await update.message.reply_text(
                "🛡️ Security Bot Activated!\n\n"
                "I will monitor your groups and channels for security risks.\n"
                "Add me to your groups and make me an admin with appropriate permissions.\n\n"
                "Available commands:\n"
                "/start - Show this message\n"
                "/report - Generate security report for this group\n"
                "/groups - List all monitored groups\n"
                "/scan - Perform live security scan of this group"
            )
        except Exception as e:
            logger.error(f"Error in start command: {e}")
    
    async def handle_new_chat_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when bot is added to a group"""
        try:
            chat = update.effective_chat
            logger.info(f"New chat members event in chat {chat.id}")
            
            for user in update.message.new_chat_members:
                if user.id == context.bot.id:
                    # Bot was added to a group
                    session = SessionLocal()
                    try:
                        # Check if group already exists
                        existing_group = session.query(Group).filter(Group.group_id == str(chat.id)).first()
                        if not existing_group:
                            # Get member count safely
                            try:
                                member_count = await chat.get_member_count()
                            except Exception:
                                member_count = 0  # Default if we can't get count
                            
                            # Add new group to database
                            new_group = Group(
                                group_id=str(chat.id),
                                group_name=chat.title or "Unknown Group",
                                member_count=member_count,
                                status="safe"
                            )
                            session.add(new_group)
                            session.commit()
                            
                            logger.info(f"Bot added to new group: {chat.title} (ID: {chat.id})")
                            
                            # Notify owner
                            await self.send_owner_message(
                                context,
                                f"✅ Bot added to new group:\n\n"
                                f"Group: {chat.title or 'Unknown Group'}\n"
                                f"ID: {chat.id}\n"
                                f"Members: {member_count}\n"
                                f"Status: Monitoring started"
                            )
                        else:
                            logger.info(f"Bot rejoined existing group: {chat.title}")
                            
                    except Exception as e:
                        logger.error(f"Error handling new group: {e}")
                        session.rollback()
                    finally:
                        session.close()
                    break  # Only need to handle bot once
                        
        except Exception as e:
            logger.error(f"Error in handle_new_chat_members: {e}")
    
    async def handle_group_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Monitor all group messages for suspicious content"""
        session = SessionLocal()
        try:
            chat = update.effective_chat
            user = update.effective_user
            
            if chat and chat.type in ['group', 'supergroup']:
                # Store activity in database
                message_text = update.message.text if update.message and update.message.text else "Non-text content"
                user_id = str(user.id) if user else "unknown"
                
                activity = GroupActivity(
                    group_id=str(chat.id),
                    activity_type="message",
                    user_id=user_id,
                    content=message_text[:500]  # Limit content length
                )
                session.add(activity)
                
                # Check for risks in message content
                if update.message and update.message.text:
                    risk_detected = await self.detect_message_risks(update.message.text, user, chat)
                    if risk_detected:
                        await self.send_alert_to_owner(context, chat, risk_detected, "message_risk")
                
                session.commit()
                
        except Exception as e:
            logger.error(f"Error handling group message: {e}")
            session.rollback()
        finally:
            session.close()
    
    async def detect_message_risks(self, message_text: str, user, chat):
        """Analyze messages for potential risks"""
        try:
            risks = []
            
            # Expanded banned keywords list
            banned_keywords = [
                'spam', 'phishing', 'http://malicious', 'hack', 'cheat', 'scam',
                'free money', 'bitcoin scam', 'password steal', 'account hack'
            ]
            
            if message_text:
                text_lower = message_text.lower()
                
                # Check for banned keywords
                for keyword in banned_keywords:
                    if keyword in text_lower:
                        risks.append(f"Banned keyword detected: '{keyword}'")
                
                # Check for spam patterns
                if len(message_text) > 500:
                    risks.append("Potential spam: Very long message")
                
                # Check for excessive links
                link_count = text_lower.count('http://') + text_lower.count('https://')
                if link_count > 3:
                    risks.append(f"Potential spam: {link_count} links in message")
                
                # Check for excessive capital letters
                if len(message_text) > 10:
                    uppercase_ratio = sum(1 for c in message_text if c.isupper()) / len(message_text)
                    if uppercase_ratio > 0.7:
                        risks.append("Potential spam: Excessive capital letters")
            
            return risks if risks else None
            
        except Exception as e:
            logger.error(f"Error in risk detection: {e}")
            return None
    
    async def send_alert_to_owner(self, context: ContextTypes.DEFAULT_TYPE, chat, risk_details, alert_type):
        """Send security alerts to bot owner"""
        session = SessionLocal()
        try:
            if isinstance(risk_details, list):
                risk_text = "\n".join([f"• {risk}" for risk in risk_details])
            else:
                risk_text = str(risk_details)
            
            group_name = getattr(chat, 'title', 'Unknown Group')
            group_id = getattr(chat, 'id', 'Unknown')
            
            alert_message = f"🚨 SECURITY ALERT\n\n"
            alert_message += f"Group: {group_name}\n"
            alert_message += f"Group ID: {group_id}\n"
            alert_message += f"Risk Type: {alert_type}\n"
            alert_message += f"Details:\n{risk_text}\n"
            alert_message += f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Send to owner
            await self.send_owner_message(context, alert_message)
            
            # Store alert in database
            alert = Alert(
                group_id=str(group_id),
                alert_type=alert_type,
                alert_message=alert_message,
                risk_level="high"
            )
            session.add(alert)
            session.commit()
            
            logger.info(f"Alert sent to owner for group {group_id}")
                
        except Exception as e:
            logger.error(f"Error sending alert to owner: {e}")
            session.rollback()
        finally:
            session.close()
    
    async def send_owner_message(self, context: ContextTypes.DEFAULT_TYPE, message: str):
        """Send message to owner with error handling"""
        try:
            await context.bot.send_message(
                chat_id=OWNER_CHAT_ID,
                text=message
            )
        except Exception as e:
            logger.error(f"Failed to send message to owner: {e}")
    
    async def generate_group_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate comprehensive security report for a group"""
        session = SessionLocal()
        try:
            chat = update.effective_chat
            
            # Get group data
            group = session.query(Group).filter(Group.group_id == str(chat.id)).first()
            if not group:
                await update.message.reply_text("❌ This group is not being monitored yet. Make sure I'm added as admin.")
                return
            
            recent_alerts = session.query(Alert).filter(
                Alert.group_id == str(chat.id),
                Alert.created_at >= datetime.datetime.utcnow() - datetime.timedelta(hours=24)
            ).order_by(Alert.created_at.desc()).all()
            
            activities_count = session.query(GroupActivity).filter(
                GroupActivity.group_id == str(chat.id),
                GroupActivity.timestamp >= datetime.datetime.utcnow() - datetime.timedelta(hours=24)
            ).count()
            
            # Calculate risk status
            high_risk_count = len([alert for alert in recent_alerts if alert.risk_level == "high"])
            if high_risk_count > 2:
                status = "🔴 HIGH RISK"
                status_db = "high_risk"
            elif high_risk_count > 0:
                status = "🟡 MEDIUM RISK" 
                status_db = "medium_risk"
            else:
                status = "🟢 SAFE"
                status_db = "safe"
            
            # Generate report
            report = f"📊 Security Report for: {chat.title}\n\n"
            report += f"Total Members: {group.member_count}\n"
            report += f"Activities (24h): {activities_count}\n"
            report += f"Current Status: {status}\n"
            report += f"Recent Alerts (24h): {len(recent_alerts)}\n"
            report += f"High Risk Alerts: {high_risk_count}\n\n"
            
            if recent_alerts:
                report += "Recent Security Issues:\n"
                for alert in recent_alerts[:3]:  # Last 3 alerts
                    alert_time = alert.created_at.strftime('%H:%M')
                    report += f"• [{alert_time}] {alert.alert_type}\n"
            else:
                report += "✅ No recent security issues detected.\n"
            
            # Update group status in database
            group.status = status_db
            session.commit()
            
            await update.message.reply_text(report)
            logger.info(f"Generated report for group {chat.id}")
            
        except Exception as e:
            logger.error(f"Error generating group report: {e}")
            await update.message.reply_text("❌ Error generating report. Please try again.")
        finally:
            session.close()
    
    async def list_all_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all monitored groups with their status"""
        session = SessionLocal()
        try:
            groups = session.query(Group).all()
            
            if not groups:
                await update.message.reply_text("📝 No groups are currently being monitored.")
                return
            
            groups_list = "🛡️ Monitored Groups:\n\n"
            total_members = 0
            at_risk_groups = 0
            
            for group in groups:
                status_icon = "🟢" if group.status == "safe" else "🟡" if group.status == "medium_risk" else "🔴"
                if group.status != "safe":
                    at_risk_groups += 1
                
                groups_list += f"{status_icon} {group.group_name or 'Unknown Group'}\n"
                groups_list += f"   Members: {group.member_count} | Status: {group.status}\n"
                groups_list += f"   ID: {group.group_id}\n\n"
                total_members += group.member_count
            
            # Add summary
            groups_list += f"📈 Summary:\n"
            groups_list += f"Total Groups: {len(groups)}\n"
            groups_list += f"Total Members: {total_members}\n"
            groups_list += f"Groups at Risk: {at_risk_groups}\n"
            
            await update.message.reply_text(groups_list)
            logger.info("Sent group list to user")
            
        except Exception as e:
            logger.error(f"Error listing groups: {e}")
            await update.message.reply_text("❌ Error retrieving group list.")
        finally:
            session.close()
    
    async def perform_live_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Perform live security scan of the group"""
        try:
            chat = update.effective_chat
            await update.message.reply_text("🔍 Starting live security scan...")
            
            # Simulate scanning process
            scan_results = []
            
            # Check recent activities
            session = SessionLocal()
            try:
                recent_alerts = session.query(Alert).filter(
                    Alert.group_id == str(chat.id),
                    Alert.created_at >= datetime.datetime.utcnow() - datetime.timedelta(hours=24)
                ).count()
                
                if recent_alerts > 0:
                    scan_results.append(f"⚠️ Found {recent_alerts} security alerts in last 24h")
                else:
                    scan_results.append("✅ No recent security alerts")
                
                # Get member count
                try:
                    member_count = await chat.get_member_count()
                    scan_results.append(f"👥 Group has {member_count} members")
                except:
                    scan_results.append("👥 Could not retrieve member count")
                    
            finally:
                session.close()
            
            # Compile scan report
            report = f"🔍 Live Scan Results for: {chat.title}\n\n"
            report += "\n".join(scan_results)
            report += f"\n\nScan completed at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await update.message.reply_text(report)
            
            # Also send to owner
            await self.send_owner_message(context, f"Live scan completed for {chat.title}")
            
        except Exception as e:
            logger.error(f"Error performing live scan: {e}")
            await update.message.reply_text("❌ Error performing live scan.")
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors in the bot"""
        logger.error(f"Exception while handling an update: {context.error}")

def main():
    """Start the security bot - Render optimized"""
    try:
        logger.info("Initializing Security Bot...")
        
        # Create application
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Create bot instance
        security_bot = SecurityBot()
        
        # Add handlers
        application.add_handler(CommandHandler("start", security_bot.start))
        application.add_handler(CommandHandler("report", security_bot.generate_group_report))
        application.add_handler(CommandHandler("groups", security_bot.list_all_groups))
        application.add_handler(CommandHandler("scan", security_bot.perform_live_scan))
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, security_bot.handle_new_chat_members))
        application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, security_bot.handle_group_message))
        
        # Add error handler
        application.add_error_handler(security_bot.error_handler)
        
        # Start polling
        logger.info("Security bot is starting...")
        application.run_polling(
            drop_pending_updates=True,  # Clean start on Render
            allowed_updates=Update.ALL_TYPES
        )
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        # Exit with error code for Render to restart
        sys.exit(1)

if __name__ == '__main__':
    main()
