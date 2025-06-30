import os
import json
import subprocess
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LinkBot:
    def __init__(self):
        self.data_file = "bot_data.json"
        self.load_data()
        
    def load_data(self):
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.links = data.get('links', [])
                self.proxy = data.get('proxy', '')
                self.check_interval = data.get('check_interval', 60)
        except FileNotFoundError:
            self.links = []
            self.proxy = ''
            self.check_interval = 60
            self.save_data()
    
    def save_data(self):
        data = {
            'links': self.links,
            'proxy': self.proxy,
            'check_interval': self.check_interval
        }
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def get_main_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("➕ Добавить ссылку", callback_data="add_link")],
            [InlineKeyboardButton("📋 Список ссылок", callback_data="list_links")],
            [InlineKeyboardButton("🗑 Удалить ссылку", callback_data="delete_link")],
            [InlineKeyboardButton("⏱ Задержка между проверками", callback_data="set_interval")],
            [InlineKeyboardButton("🌐 Прокси", callback_data="set_proxy")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def check_link_with_curl(self, url, max_retries=3):
        display_url = url[:50] + "..." if len(url) > 50 else url
        
        for attempt in range(max_retries):
            try:
                cmd = ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}']
                
                if self.proxy:
                    # Parse proxy format: residential.birdproxies.com:7777:pool-p1-cc-il:lnal286wfd376e9j
                    parts = self.proxy.split(':')
                    if len(parts) >= 4:
                        host = parts[0]
                        port = parts[1]
                        user = parts[2]
                        password = parts[3]
                        proxy_url = f"{user}:{password}@{host}:{port}"
                        cmd.extend(['-x', proxy_url])
                
                cmd.append(url)
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                status_code = result.stdout.strip()
                
                if status_code == '200':
                    return True, f"✅ {display_url} - OK (200)"
                elif status_code == '404':
                    return False, f"❌ {display_url} - Not Found (404)"
                elif status_code == '502':
                    return False, f"❌ {display_url} - Bad Gateway (502)"
                elif status_code == '000':
                    # Connection failed - retry if not last attempt
                    if attempt < max_retries - 1:
                        logger.warning(f"Connection failed for {display_url}, retrying... ({attempt + 1}/{max_retries})")
                        continue
                    else:
                        return False, f"❌ {display_url} - Connection failed (after {max_retries} retries)"
                else:
                    return False, f"⚠️ {display_url} - Status: {status_code}"
                    
            except subprocess.TimeoutExpired:
                # Timeout - retry if not last attempt
                if attempt < max_retries - 1:
                    logger.warning(f"Timeout for {display_url}, retrying... ({attempt + 1}/{max_retries})")
                    continue
                else:
                    return False, f"❌ {display_url} - Timeout (after {max_retries} retries)"
            except Exception as e:
                # Other error - retry if not last attempt
                if attempt < max_retries - 1:
                    logger.warning(f"Error for {display_url}: {str(e)}, retrying... ({attempt + 1}/{max_retries})")
                    continue
                else:
                    return False, f"❌ {display_url} - Error: {str(e)} (after {max_retries} retries)"
        
        # Should never reach here, but just in case
        return False, f"❌ {display_url} - Unknown error"

bot_instance = LinkBot()

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🔗 Link Monitor Bot\n\nВыберите действие:",
        reply_markup=bot_instance.get_main_keyboard()
    )

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data == "add_link":
        query.edit_message_text("📝 Отправьте ссылку для добавления:")
        context.user_data['waiting_for'] = 'link'
        
    elif query.data == "list_links":
        if not bot_instance.links:
            query.edit_message_text(
                "📋 Список ссылок пуст",
                reply_markup=bot_instance.get_main_keyboard()
            )
        else:
            links_text = "📋 Список ссылок:\n\n"
            for i, link in enumerate(bot_instance.links, 1):
                # Truncate long URLs for display
                display_link = link[:80] + "..." if len(link) > 80 else link
                links_text += f"{i}. {display_link}\n"
            
            query.edit_message_text(
                links_text,
                reply_markup=bot_instance.get_main_keyboard()
            )
    
    elif query.data == "delete_link":
        if not bot_instance.links:
            query.edit_message_text(
                "📋 Список ссылок пуст",
                reply_markup=bot_instance.get_main_keyboard()
            )
        else:
            keyboard = []
            for i, link in enumerate(bot_instance.links):
                # Show domain name or first part of URL for better readability
                display_text = link[:45] + "..." if len(link) > 45 else link
                keyboard.append([InlineKeyboardButton(f"🗑 {display_text}", callback_data=f"del_{i}")])
            keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")])
            
            query.edit_message_text(
                "Выберите ссылку для удаления:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    elif query.data == "set_interval":
        query.edit_message_text("⏱ Отправьте интервал проверки в секундах:")
        context.user_data['waiting_for'] = 'interval'
        
    elif query.data == "set_proxy":
        current_proxy = bot_instance.proxy or "Не установлен"
        query.edit_message_text(
            f"🌐 Текущий прокси: {current_proxy}\n\n"
            "Отправьте прокси в формате:\n"
            "residential.birdproxies.com:7777:pool-p1-cc-il:lnal286wfd376e9j"
        )
        context.user_data['waiting_for'] = 'proxy'
        
    elif query.data.startswith("del_"):
        index = int(query.data.split("_")[1])
        deleted_link = bot_instance.links.pop(index)
        bot_instance.save_data()
        
        # Show truncated URL in deletion confirmation
        display_url = deleted_link[:60] + "..." if len(deleted_link) > 60 else deleted_link
        query.edit_message_text(
            f"🗑 Ссылка удалена:\n{display_url}",
            reply_markup=bot_instance.get_main_keyboard()
        )
        
    elif query.data == "back_to_main":
        query.edit_message_text(
            "🔗 Link Monitor Bot\n\nВыберите действие:",
            reply_markup=bot_instance.get_main_keyboard()
        )

def message_handler(update: Update, context: CallbackContext):
    logger.info(f"Message received: {update.message.text[:50]}...")
    logger.info(f"User data: {context.user_data}")
    
    waiting_for = context.user_data.get('waiting_for')
    logger.info(f"Waiting for: {waiting_for}")
    
    if waiting_for == 'link':
        url = update.message.text.strip()
        logger.info(f"Received URL: {url[:100]}... (length: {len(url)})")
        
        # Check if URL is valid
        if url.startswith(('http://', 'https://')) and len(url) > 10:
            # Check if link already exists
            if url in bot_instance.links:
                update.message.reply_text(
                    "⚠️ Эта ссылка уже добавлена",
                    reply_markup=bot_instance.get_main_keyboard()
                )
            else:
                bot_instance.links.append(url)
                bot_instance.save_data()
                
                # Show truncated URL in confirmation
                display_url = url[:60] + "..." if len(url) > 60 else url
                update.message.reply_text(
                    f"✅ Ссылка добавлена:\n{display_url}",
                    reply_markup=bot_instance.get_main_keyboard()
                )
                logger.info(f"Added link: {url}")
        else:
            update.message.reply_text(
                "❌ Неверный формат ссылки. Используйте http:// или https://",
                reply_markup=bot_instance.get_main_keyboard()
            )
            logger.warning(f"Invalid URL format: {url[:100]}")
        context.user_data.pop('waiting_for', None)
        
    elif waiting_for == 'interval':
        try:
            interval = int(update.message.text.strip())
            if interval < 10:
                update.message.reply_text(
                    "❌ Минимальный интервал - 10 секунд",
                    reply_markup=bot_instance.get_main_keyboard()
                )
            else:
                bot_instance.check_interval = interval
                bot_instance.save_data()
                
                # Restart the job with new interval
                try:
                    current_jobs = context.job_queue.get_jobs_by_name("link_checker")
                    for job in current_jobs:
                        job.schedule_removal()
                    
                    context.job_queue.run_repeating(
                        check_links_task,
                        interval=interval,
                        first=5,
                        name="link_checker"
                    )
                except Exception as e:
                    logger.error(f"Error restarting job: {e}")
                
                update.message.reply_text(
                    f"✅ Интервал установлен: {interval} секунд",
                    reply_markup=bot_instance.get_main_keyboard()
                )
        except ValueError:
            update.message.reply_text(
                "❌ Введите число",
                reply_markup=bot_instance.get_main_keyboard()
            )
        context.user_data.pop('waiting_for', None)
        
    elif waiting_for == 'proxy':
        proxy = update.message.text.strip()
        bot_instance.proxy = proxy
        bot_instance.save_data()
        update.message.reply_text(
            f"✅ Прокси установлен: {proxy}",
            reply_markup=bot_instance.get_main_keyboard()
        )
        context.user_data.pop('waiting_for', None)
    
    else:
        # Handle case when not waiting for any input
        logger.info("Not waiting for any input")
        update.message.reply_text(
            "🤔 Используйте /start для открытия меню",
            reply_markup=bot_instance.get_main_keyboard()
        )

def check_links_task(context: CallbackContext):
    if not bot_instance.links:
        return
    
    chat_id = os.getenv('CHAT_ID')
    if not chat_id:
        return
        
    results = []
    for link in bot_instance.links:
        is_ok, message = bot_instance.check_link_with_curl(link)
        results.append(message)
    
    if results:
        report = f"🔍 Проверка ссылок ({datetime.now().strftime('%H:%M:%S')}):\n\n"
        report += "\n".join(results)
        
        try:
            context.bot.send_message(chat_id=chat_id, text=report)
        except Exception as e:
            logger.error(f"Error sending message: {e}")

def main():
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        print("❌ BOT_TOKEN not found in environment variables")
        return
    
    updater = Updater(token=bot_token, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text, message_handler))
    
    # Schedule link checking
    job_queue = updater.job_queue
    job_queue.run_repeating(
        check_links_task, 
        interval=60,  # Will be updated dynamically based on bot_instance.check_interval
        first=10,
        name="link_checker"
    )
    
    print("🚀 Bot starting...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main() 