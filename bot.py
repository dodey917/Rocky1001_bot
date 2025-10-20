import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import psycopg2

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
DATABASE_URL = os.getenv('DATABASE_URL')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                group_id BIGINT PRIMARY KEY,
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
        
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database ready")
    except Exception as e:
        print(f"❌ Database error: {e}")

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
        print(f"Save group error: {e}")

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
        print(f"Save message error: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if chat.type in ["group", "supergroup"]:
        save_group(chat.id, chat.title)
        await update.message.reply_text(
            "🛡️ Protection Bot Active!\n"
            "I'm monitoring this group and sending alerts to owner."
        )
    else:
        await update.message.reply_text("Add me to a group to start monitoring!")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"✅ Bot is running\n🕒 {datetime.now().strftime('%H:%M:%S')}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM groups")
        group_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM messages")
        message_count = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        await update.message.reply_text(
            f"📊 Stats:\nGroups: {group_count}\nMessages: {message_count}"
        )
    except Exception as e:
        await update.message.reply_text("❌ Could not get stats")

async def handle_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    
    if not message or not message.from_user or message.from_user.is_bot:
        return
    
    chat = update.effective_chat
    
    if chat.type in ["group", "supergroup"]:
        # Save group and message
        save_group(chat.id, chat.title)
        
        if message.text:
            save_message(chat.id, message.from_user.id, message.from_user.username, message.text)
            
            # Send alert to owner
            try:
                alert_msg = f"📝 New message in {chat.title}\n👤 @{message.from_user.username or 'No username'}\n💬 {message.text[:100]}"
                await context.bot.send_message(chat_id=CHAT_ID, text=alert_msg)
            except Exception as e:
                print(f"Alert error: {e}")

async def handle_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.new_chat_members:
        for user in update.message.new_chat_members:
            if user.id == context.bot.id:
                chat = update.effective_chat
                save_group(chat.id, chat.title)
                await update.message.reply_text("🛡️ Bot added! Monitoring this group.")
                
                # Alert owner
                try:
                    await context.bot.send_message(
                        chat_id=CHAT_ID, 
                        text=f"🤖 Bot added to: {chat.title}"
                    )
                except:
                    pass

def main():
    print("🛡️ Starting Protection Bot...")
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_messages))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_bot_added))
    
    print("✅ Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
