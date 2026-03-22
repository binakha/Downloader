import os
import telebot
from telebot import types
import yt_dlp
import ffmpeg
import logging
import time
import threading

# ==========================
# CONFIGURATION
# ==========================

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Set your BOT_TOKEN in Railway Environment Variables
bot = telebot.TeleBot(BOT_TOKEN)

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# User state tracking: user_id -> mode ("mp3" or "mp4")
user_state = {}

# Anti-spam control
user_last_action = {}
SPAM_COOLDOWN = 15  # seconds

# ==========================
# HELPER FUNCTIONS
# ==========================

def cleanup_file(filepath):
    """Delete a temporary file after sending."""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        logging.warning(f"File cleanup error: {e}")

def is_spamming(user_id):
    """Prevent spamming by checking cooldowns."""
    now = time.time()
    last = user_last_action.get(user_id, 0)
    if now - last < SPAM_COOLDOWN:
        return True
    user_last_action[user_id] = now
    return False

def download_media(url, format_type, output_path):
    """Use yt-dlp to download video/audio files."""
    ydl_opts = {}

    if format_type == "mp3":
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'noplaylist': True,
        }
    elif format_type == "mp4":
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': output_path,
            'merge_output_format': 'mp4',
            'quiet': True,
            'noplaylist': True,
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


# ==========================
# BOT MENU HANDLERS
# ==========================

def main_menu():
    """Return main keyboard menu."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("1️⃣ Mp3 / Music 🎵", "2️⃣ Mp4 / Video 🎬")
    return markup

def back_menu():
    """Return back button keyboard."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🔙 Back")
    return markup


@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(
        message.chat.id,
        "👋 Hi Sir, Please Select Your Type For download your Video / Audio.",
        reply_markup=main_menu()
    )
    user_state.pop(message.chat.id, None)


@bot.message_handler(func=lambda m: m.text == "🔙 Back")
def go_back(message):
    bot.send_message(
        message.chat.id,
        "👋 Back to main menu.",
        reply_markup=main_menu()
    )
    user_state.pop(message.chat.id, None)


@bot.message_handler(func=lambda m: m.text == "1️⃣ Mp3 / Music 🎵")
def select_mp3(message):
    user_state[message.chat.id] = "mp3"
    bot.send_message(
        message.chat.id,
        "📥 Please Send Your Video Link.",
        reply_markup=back_menu()
    )


@bot.message_handler(func=lambda m: m.text == "2️⃣ Mp4 / Video 🎬")
def select_mp4(message):
    user_state[message.chat.id] = "mp4"
    bot.send_message(
        message.chat.id,
        "📥 Please Send Your Video Link.",
        reply_markup=back_menu()
    )


@bot.message_handler(func=lambda m: True)
def handle_link(message):
    user_id = message.chat.id
    text = message.text.strip()

    # Handle back button or empty message
    if text == "🔙 Back":
        go_back(message)
        return

    # Ensure user state is set
    if user_id not in user_state:
        bot.send_message(user_id, "❌ Please select an option first.", reply_markup=main_menu())
        return

    if is_spamming(user_id):
        bot.send_message(user_id, "⚠️ Please wait a few seconds before sending another request.")
        return

    format_type = user_state[user_id]
    bot_msg = bot.send_message(user_id, "⏳ Downloading... Please wait.")

    try:
        file_suffix = "mp3" if format_type == "mp3" else "mp4"
        output_path = f"{user_id}_{int(time.time())}.%(ext)s"
        clean_output_path = f"{user_id}_{int(time.time())}.{file_suffix}"

        # Run download in a separate thread to avoid blocking
        def process_download():
            try:
                download_media(text, format_type, output_path)
                final_file = None

                # Find the actual downloaded file
                for file in os.listdir("."):
                    if file.startswith(str(user_id)) and file.endswith(file_suffix):
                        final_file = file
                        break

                if not final_file:
                    raise Exception("Download failed")

                caption = "𝘾𝙧𝙚𝙖𝙩𝙚𝙙 𝘽𝙮 | 𝙎𝙖𝙖𝙁𝙚 😌🖤"

                with open(final_file, 'rb') as f:
                    if format_type == "mp3":
                        bot.send_audio(user_id, f, caption=caption)
                    else:
                        bot.send_video(user_id, f, caption=caption)

                bot.edit_message_text("✅ Done!", chat_id=user_id, message_id=bot_msg.message_id)
                cleanup_file(final_file)

            except yt_dlp.utils.DownloadError:
                bot.edit_message_text("❌ Unsupported or invalid link.", chat_id=user_id, message_id=bot_msg.message_id)
            except Exception as e:
                logging.error(f"Error: {e}")
                bot.edit_message_text("❌ Video download failed.", chat_id=user_id, message_id=bot_msg.message_id)

        threading.Thread(target=process_download).start()

    except Exception as e:
        logging.error(e)
        bot.edit_message_text("❌ Unexpected error occurred.", chat_id=user_id, message_id=bot_msg.message_id)


# ==========================
# RUN BOT
# ==========================

if __name__ == "__main__":
    logging.info("Bot started successfully!")
    bot.infinity_polling(skip_pending=True)
