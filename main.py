import os
import telebot
from telebot import types
import yt_dlp
import logging
import time
import threading
import glob

# ==========================
# CONFIGURATION
# ==========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# user_id -> "mp3" or "mp4"
user_state = {}

# Anti-spam
user_last_action = {}
SPAM_COOLDOWN = 15  # seconds

# ==========================
# HELPER FUNCTIONS
# ==========================

def cleanup_files(pattern):
    """Delete temp files matching a glob pattern."""
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except Exception as e:
            logging.warning(f"Cleanup error: {e}")

def is_spamming(user_id):
    now = time.time()
    if now - user_last_action.get(user_id, 0) < SPAM_COOLDOWN:
        return True
    user_last_action[user_id] = now
    return False

def is_valid_url(text):
    return text.startswith("http://") or text.startswith("https://")

def get_ydl_opts(format_type, output_template):
    """Build yt-dlp options. Works for most sites yt-dlp supports."""

    common = {
        'outtmpl': output_template,
        'quiet': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'socket_timeout': 30,
        # Retry on fragment errors (helps with Instagram, TikTok, etc.)
        'retries': 5,
        'fragment_retries': 5,
        # Use a browser-like User-Agent to avoid blocks
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            )
        },
        # Cookies from browser (optional but helps for age-gated / login-required content)
        # 'cookiesfrombrowser': ('chrome',),
    }

    if format_type == "mp3":
        common.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:  # mp4
        common.update({
            # Prefer mp4 container; fall back to best if not available
            'format': (
                'bestvideo[ext=mp4]+bestaudio[ext=m4a]'
                '/bestvideo+bestaudio'
                '/best'
            ),
            'merge_output_format': 'mp4',
            # Re-encode to h264 if the merged container isn't mp4
            # (needed for some sites like Twitter/X)
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        })

    return common

# ==========================
# KEYBOARD MENUS
# ==========================

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("1️⃣ Mp3 / Music 🎵", "2️⃣ Mp4 / Video 🎬")
    return markup

def back_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🔙 Back")
    return markup

# ==========================
# COMMAND HANDLERS
# ==========================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(
        message.chat.id,
        "👋 *Hi! Select a format to get started.*\n\n"
        "Supports: YouTube, Instagram, TikTok, Twitter/X, Facebook, "
        "Vimeo, SoundCloud, Dailymotion & 1000+ more sites.",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )
    user_state.pop(message.chat.id, None)


@bot.message_handler(func=lambda m: m.text == "🔙 Back")
def go_back(message):
    bot.send_message(message.chat.id, "🏠 Main menu.", reply_markup=main_menu())
    user_state.pop(message.chat.id, None)


@bot.message_handler(func=lambda m: m.text == "1️⃣ Mp3 / Music 🎵")
def select_mp3(message):
    user_state[message.chat.id] = "mp3"
    bot.send_message(
        message.chat.id,
        "🎵 *MP3 mode selected.*\nSend a video/audio link now.",
        parse_mode="Markdown",
        reply_markup=back_menu()
    )


@bot.message_handler(func=lambda m: m.text == "2️⃣ Mp4 / Video 🎬")
def select_mp4(message):
    user_state[message.chat.id] = "mp4"
    bot.send_message(
        message.chat.id,
        "🎬 *MP4 mode selected.*\nSend a video link now.",
        parse_mode="Markdown",
        reply_markup=back_menu()
    )


# ==========================
# LINK HANDLER
# ==========================

@bot.message_handler(func=lambda m: True)
def handle_link(message):
    user_id = message.chat.id
    text = message.text.strip()

    if text == "🔙 Back":
        go_back(message)
        return

    if user_id not in user_state:
        bot.send_message(user_id, "❌ Please select MP3 or MP4 first.", reply_markup=main_menu())
        return

    if not is_valid_url(text):
        bot.send_message(user_id, "⚠️ Please send a valid URL (starting with http/https).")
        return

    if is_spamming(user_id):
        bot.send_message(user_id, f"⏳ Please wait {SPAM_COOLDOWN}s before another request.")
        return

    format_type = user_state[user_id]
    status_msg = bot.send_message(user_id, "⏳ Processing your request...")

    def process():
        timestamp = int(time.time())
        base_name = f"{user_id}_{timestamp}"
        output_template = f"{base_name}.%(ext)s"

        try:
            ydl_opts = get_ydl_opts(format_type, output_template)

            bot.edit_message_text(
                "⬇️ Downloading...",
                chat_id=user_id,
                message_id=status_msg.message_id
            )

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                title = info.get('title', 'media')

            # Find the downloaded file
            ext = "mp3" if format_type == "mp3" else "mp4"
            matches = glob.glob(f"{base_name}*.{ext}")

            # Fallback: pick any file with the base name
            if not matches:
                matches = glob.glob(f"{base_name}*")

            if not matches:
                raise FileNotFoundError("Downloaded file not found.")

            final_file = matches[0]
            file_size = os.path.getsize(final_file)

            # Telegram bot API limit: 50 MB
            if file_size > 50 * 1024 * 1024:
                cleanup_files(f"{base_name}*")
                bot.edit_message_text(
                    "❌ File is larger than 50MB — Telegram doesn't allow sending files this big via bot.",
                    chat_id=user_id,
                    message_id=status_msg.message_id
                )
                return

            bot.edit_message_text(
                "📤 Uploading to Telegram...",
                chat_id=user_id,
                message_id=status_msg.message_id
            )

            caption = f"🎵 *{title}*\n\n_Created By | SaaFe_ 😌🖤"

            with open(final_file, 'rb') as f:
                if format_type == "mp3":
                    bot.send_audio(
                        user_id, f,
                        caption=caption,
                        parse_mode="Markdown",
                        title=title
                    )
                else:
                    bot.send_video(
                        user_id, f,
                        caption=caption,
                        parse_mode="Markdown",
                        supports_streaming=True
                    )

            bot.edit_message_text(
                "✅ Done!",
                chat_id=user_id,
                message_id=status_msg.message_id
            )

        except yt_dlp.utils.DownloadError as e:
            logging.error(f"DownloadError [{user_id}]: {e}")
            bot.edit_message_text(
                "❌ *Download failed.*\n\nPossible reasons:\n"
                "• Link is private or login-required\n"
                "• Site is not supported\n"
                "• Link is expired or invalid",
                chat_id=user_id,
                message_id=status_msg.message_id,
                parse_mode="Markdown"
            )
        except FileNotFoundError as e:
            logging.error(f"FileNotFoundError [{user_id}]: {e}")
            bot.edit_message_text(
                "❌ File not found after download. Try again.",
                chat_id=user_id,
                message_id=status_msg.message_id
            )
        except Exception as e:
            logging.error(f"Unexpected error [{user_id}]: {e}")
            bot.edit_message_text(
                "❌ Something went wrong. Please try again later.",
                chat_id=user_id,
                message_id=status_msg.message_id
            )
        finally:
            cleanup_files(f"{base_name}*")

    threading.Thread(target=process, daemon=True).start()


# ==========================
# RUN
# ==========================

if __name__ == "__main__":
    logging.info("Bot started.")
    bot.infinity_polling(skip_pending=True)
