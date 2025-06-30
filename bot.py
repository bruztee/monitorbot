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
                self.proxy_il = data.get('proxy_il', '')  # Israel proxy
                self.proxy_ua = data.get('proxy_ua', '')  # Ukraine proxy
                self.check_interval = data.get('check_interval', 60)
        except FileNotFoundError:
            self.links = []
            self.proxy_il = ''
            self.proxy_ua = ''
            self.check_interval = 60
            self.save_data()
    
    def save_data(self):
        data = {
            'links': self.links,
            'proxy_il': self.proxy_il,
            'proxy_ua': self.proxy_ua,
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
            [InlineKeyboardButton("🇮🇱 Прокси Израиль", callback_data="set_proxy_il")],
            [InlineKeyboardButton("🇺🇦 Прокси Украина", callback_data="set_proxy_ua")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def check_link_with_curl(self, url, proxy_config=None, proxy_name="", max_retries=3):
        display_url = url[:50] + "..." if len(url) > 50 else url
        
        for attempt in range(max_retries):
            try:
                # Get both status code and response body with browser headers
                cmd = [
                    'curl', '-s', '-L', '-w', '%{http_code}', '--max-time', '30', '--compressed',
                    '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
                    '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    '-H', 'Accept-Language: en-US,en;q=0.5',
                    '-H', 'Connection: keep-alive',
                    '-H', 'Upgrade-Insecure-Requests: 1'
                ]
                
                if proxy_config:
                    # Parse proxy format: residential.birdproxies.com:7777:pool-p1-cc-il:lnal286wfd376e9j
                    parts = proxy_config.split(':')
                    if len(parts) >= 4:
                        host = parts[0]
                        port = parts[1]
                        user = parts[2]
                        password = parts[3]
                        proxy_url = f"{user}:{password}@{host}:{port}"
                        cmd.extend(['-x', proxy_url])
                
                cmd.append(url)
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
                
                # Log stderr if there are errors
                if result.stderr:
                    logger.warning(f"Curl stderr: {result.stderr}")
                
                # Extract status code (last 3 characters) and response body
                response = result.stdout
                if len(response) >= 3:
                    status_code = response[-3:]
                    response_body = response[:-3] if len(response) > 3 else ""
                else:
                    status_code = "000"
                    response_body = ""
                
                # Check for Cloudflare challenge/block (more specific detection)
                cf_challenge_indicators = [
                    'sorry, you have been blocked' in response_body.lower(),
                    'attention required!' in response_body.lower() and 'cloudflare' in response_body.lower(),
                    'checking your browser before accessing' in response_body.lower(),
                    'enable cookies' in response_body.lower() and 'cloudflare' in response_body.lower(),
                    'cf-error-details' in response_body.lower(),
                    'cf-wrapper' in response_body.lower() and status_code in ['403', '503']
                ]
                
                if any(cf_challenge_indicators):
                    logger.warning(f"Cloudflare challenge/block detected for {display_url} ({proxy_name})")
                    return False, f"🛡️ {display_url} ({proxy_name}) - Cloudflare blocked"
                
                if status_code == '200':
                    # Double check it's not a masked Cloudflare page
                    if 'cloudflare' in response_body.lower() and 'ray id' in response_body.lower():
                        return False, f"🛡️ {display_url} ({proxy_name}) - Cloudflare challenge"
                    return True, f"✅ {display_url} ({proxy_name}) - OK (200)"
                elif status_code == '404':
                    return False, f"❌ {display_url} ({proxy_name}) - Not Found (404)"
                elif status_code == '502':
                    return False, f"❌ {display_url} ({proxy_name}) - Bad Gateway (502)"
                elif status_code == '403':
                    return False, f"🚫 {display_url} ({proxy_name}) - Forbidden (403)"
                elif status_code == '000':
                    # Connection failed - retry if not last attempt
                    if attempt < max_retries - 1:
                        logger.warning(f"Connection failed for {display_url} ({proxy_name}), retrying... ({attempt + 1}/{max_retries})")
                        continue
                    else:
                        return False, f"❌ {display_url} ({proxy_name}) - Connection failed (after {max_retries} retries)"
                else:
                    return False, f"⚠️ {display_url} ({proxy_name}) - Status: {status_code}"
                    
            except subprocess.TimeoutExpired:
                # Timeout - retry if not last attempt
                if attempt < max_retries - 1:
                    logger.warning(f"Timeout for {display_url} ({proxy_name}), retrying... ({attempt + 1}/{max_retries})")
                    continue
                else:
                    return False, f"❌ {display_url} ({proxy_name}) - Timeout (after {max_retries} retries)"
            except Exception as e:
                # Other error - retry if not last attempt
                if attempt < max_retries - 1:
                    logger.warning(f"Error for {display_url} ({proxy_name}): {str(e)}, retrying... ({attempt + 1}/{max_retries})")
                    continue
                else:
                    return False, f"❌ {display_url} ({proxy_name}) - Error: {str(e)} (after {max_retries} retries)"
        
        # Should never reach here, but just in case
        return False, f"❌ {display_url} ({proxy_name}) - Unknown error"

    def check_link_both_proxies(self, url):
        """Check link through both proxies and return both results"""
        results = []
        
        # Check with Israel proxy
        if self.proxy_il:
            is_ok_il, msg_il = self.check_link_with_curl(url, self.proxy_il, "🇮🇱")
            results.append(msg_il)
        
        # Check with Ukraine proxy  
        if self.proxy_ua:
            is_ok_ua, msg_ua = self.check_link_with_curl(url, self.proxy_ua, "🇺🇦")
            results.append(msg_ua)
        
        # If no proxies configured, check without proxy
        if not self.proxy_il and not self.proxy_ua:
            is_ok, msg = self.check_link_with_curl(url, None, "🌐")
            results.append(msg)
        
        return results

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
        
    elif query.data == "set_proxy_il":
        current_proxy = bot_instance.proxy_il or "Не установлен"
        query.edit_message_text(
            f"🇮🇱 Текущий прокси Израиль: {current_proxy}\n\n"
            "Отправьте прокси в формате:\n"
            "residential.birdproxies.com:7777:pool-p1-cc-il:lnal286wfd376e9j"
        )
        context.user_data['waiting_for'] = 'proxy_il'
        
    elif query.data == "set_proxy_ua":
        current_proxy = bot_instance.proxy_ua or "Не установлен"
        query.edit_message_text(
            f"🇺🇦 Текущий прокси Украина: {current_proxy}\n\n"
            "Отправьте прокси в формате:\n"
            "residential.birdproxies.com:7777:pool-p1-cc-ua:lnal286wfd376e9j"
        )
        context.user_data['waiting_for'] = 'proxy_ua'
        
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
    waiting_for = context.user_data.get('waiting_for')
    
    if waiting_for == 'link':
        url = update.message.text.strip()
        
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
        else:
            update.message.reply_text(
                "❌ Неверный формат ссылки. Используйте http:// или https://",
                reply_markup=bot_instance.get_main_keyboard()
            )
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
        
    elif waiting_for == 'proxy_il':
        proxy = update.message.text.strip()
        bot_instance.proxy_il = proxy
        bot_instance.save_data()
        update.message.reply_text(
            f"✅ 🇮🇱 Прокси Израиль установлен: {proxy}",
            reply_markup=bot_instance.get_main_keyboard()
        )
        context.user_data.pop('waiting_for', None)
        
    elif waiting_for == 'proxy_ua':
        proxy = update.message.text.strip()
        bot_instance.proxy_ua = proxy
        bot_instance.save_data()
        update.message.reply_text(
            f"✅ 🇺🇦 Прокси Украина установлен: {proxy}",
            reply_markup=bot_instance.get_main_keyboard()
        )
        context.user_data.pop('waiting_for', None)
    
    else:
        # Handle case when not waiting for any input
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
        
    all_results = []
    for link in bot_instance.links:
        # Check through both proxies
        link_results = bot_instance.check_link_both_proxies(link)
        all_results.extend(link_results)
        # Add empty line between different links if multiple proxies
        if len(link_results) > 1:
            all_results.append("")
    
    if all_results:
        report = f"🔍 Проверка ссылок ({datetime.now().strftime('%H:%M:%S')}):\n\n"
        report += "\n".join(all_results)
        
        try:
            context.bot.send_message(chat_id=chat_id, text=report)
        except Exception as e:
            logger.error(f"Error sending message: {e}")

def main():
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        print("❌ BOT_TOKEN not found in environment variables")
        return
    
    updater = Updater(bot_token, use_context=True)
    dispatcher = updater.dispatcher
    
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))
    
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