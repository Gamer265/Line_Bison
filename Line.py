import logging
import asyncio
import re
import unicodedata
import string
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from cachetools import TTLCache

# --- Configuration ---
API_ID = '1747534'
API_HASH = '5a2684512006853f2e48aca9652d83ea'
SESSION_STRING = '1BVtsOGgBu2LspEEeVvgzMKpcl4eA1X-F5mPytbGAAzGj2MeduTtSM5QUhx3eSKfRjhxqVXr47NsUj1EYYRH5zZyxQ2yvUqTdHtFzNM1lniJGPhIhmRUn21C3hPjYXdEXJz5oOXC9wvwvUGNj3Moo-atcP0HuMiwydv0PVZ59RWdkHrXQeqHSXKnzbcw_9LrmhdjFf-6KwT3Hfd2LAxcIZ2hmOoRb9oqpNniGU6wQ1KRyMaCfM2bT5XWfUDGq9MG-iC2NXGaC6kev_riTQwvoveioRelU7HP4QV3wC0aPayWpaargbhPtEdl8Y2Vnhln88lBbZj1gJj7UjxqxyzJXfwii6PYHFsg='
SOURCE_CHAT_ID = -1001262096355  # source channel
TARGET_CHAT_ID = -1001075055733  # Destination channel

# --- Initialize Bot & Logging ---
user_bot = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- In-memory Message Mapping (auto-cleanup after 24 hours) ---
message_map = TTLCache(maxsize=10000, ttl=86400)

# --- Forbidden Words Setup (using a simple list) ---
FORBIDDEN_WORDS_LIST = {'id', 'bet', 'fairplay'}

def normalize_text(text: str) -> str:
    """Normalize text to NFC form."""
    return unicodedata.normalize('NFC', text)

def forbidden_words_check(text: str) -> bool:
    """Tokenize and check for any forbidden words (case-insensitive)."""
    # Lowercase and split text on whitespace
    tokens = text.lower().split()
    for token in tokens:
        # Strip punctuation from each token
        clean = token.strip(string.punctuation)
        if clean in FORBIDDEN_WORDS_LIST:
            return True
    return False

# --- Precompiled Regex Patterns ---
URL_REGEX = re.compile(r'\b(?:https?://|www\.|t\.me/|telegram\.me/)\S+\b', re.IGNORECASE)
USERNAME_REGEX = re.compile(r'@\w+', re.IGNORECASE)
EMOJI_REGEX = re.compile(r'['
                         u"\U0001F600-\U0001F64F"  # Emoticons
                         u"\U0001F446"             # 👆 
                         ']', flags=re.UNICODE)

def contains_forbidden(text: str) -> bool:
    """
    Returns True if the normalized text contains any forbidden content:
    URLs, Telegram usernames, specified emoji range, or any forbidden words.
    """
    norm_text = normalize_text(text)
    if URL_REGEX.search(norm_text):
        return True
    if USERNAME_REGEX.search(norm_text):
        return True
    if EMOJI_REGEX.search(norm_text):
        return True
    if forbidden_words_check(norm_text):
        return True
    return False

# --- Forwarding Function ---
async def forward_text_message(text, source_id):
    """
    Forward the text message to the target channel and update message_map.
    Retries if FloodWaitError occurs.
    """
    try:
        dest_message = await user_bot.send_message(TARGET_CHAT_ID, text)
        message_map[source_id] = dest_message.id
        logger.info(f"Forwarded message {source_id} as {dest_message.id}.")
        return dest_message.id
    except FloodWaitError as e:
        logger.warning(f"Rate limited. Retrying in {e.seconds} seconds.")
        await asyncio.sleep(e.seconds)
        return await forward_text_message(text, source_id)
    except Exception as e:
        logger.error(f"Error forwarding message {source_id}: {e}", exc_info=True)
        return None

# --- Event Handlers ---
@user_bot.on(events.NewMessage(chats=SOURCE_CHAT_ID))
async def new_message_handler(event):
    if event.message.text:
        if contains_forbidden(event.message.text):
            logger.info(f"Message (ID: {event.message.id}) contains forbidden content; ignoring.")
            return
        logger.info(f"Received new message (ID: {event.message.id}) with acceptable content.")
        asyncio.create_task(forward_text_message(event.message.text, event.message.id))
    else:
        logger.info("Message has no text; ignoring.")

@user_bot.on(events.MessageEdited(chats=SOURCE_CHAT_ID))
async def message_edited_handler(event):
    if event.message.text:
        source_id = event.message.id
        logger.info(f"Edited message received (Source ID: {source_id}).")
        # If the edited text now contains forbidden content, ignore the edit.
        if contains_forbidden(event.message.text):
            logger.info(f"Edited message {source_id} now contains forbidden content; ignoring edit.")
            return
        if source_id not in message_map:
            logger.info(f"No mapping for source message {source_id}; ignoring edit event.")
            return
        try:
            await user_bot.edit_message(TARGET_CHAT_ID, message_map[source_id], event.message.text)
            logger.info(f"Edited destination message {message_map[source_id]} for source {source_id}.")
        except Exception as e:
            logger.error(f"Error editing message {source_id}: {e}", exc_info=True)
    else:
        logger.info("Edited message has no text; ignoring.")

@user_bot.on(events.MessageDeleted(chats=SOURCE_CHAT_ID))
async def message_deleted_handler(event):
    logger.info(f"Message(s) deleted in source channel: {event.deleted_ids}")
    for source_id in event.deleted_ids:
        if source_id in message_map:
            try:
                await user_bot.delete_messages(TARGET_CHAT_ID, message_map.pop(source_id))
                logger.info(f"Deleted forwarded message for source {source_id}.")
            except Exception as e:
                logger.error(f"Error deleting message {source_id}: {e}", exc_info=True)
        else:
            logger.info(f"No mapping for deleted source message {source_id}.")

# --- Startup ---
async def start_userbot():
    try:
        await user_bot.start()
        logger.info("Bot is Online")
        await user_bot.run_until_disconnected()
    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(start_userbot())
