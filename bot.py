import os
import logging
import asyncio
import json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from groq import Groq
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

BOT_TOKEN   = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID    = int(os.getenv("ADMIN_ID", "0"))

# ✅ DefaultBotProperties disables link preview globally
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode="HTML",
        link_preview_is_disabled=True
    )
)
dp        = Dispatcher(storage=MemoryStorage())
groq_client = Groq(api_key=GROQ_API_KEY)
scheduler = AsyncIOScheduler()

CHANNELS_FILE        = "channels.json"
SYSTEM_SETTINGS_FILE = "settings.json"

# ──────────────────────────────────────────
# 📂 File Helpers
# ──────────────────────────────────────────

def load_channels():
    if os.path.exists(CHANNELS_FILE):
        try:
            with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_channels(data):
    with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_settings():
    default = {
        "ad_sign": {
            "content_type": "text",
            "text": "ማስታወቂያ ብቻ ❗️",
            "file_id": None,
            "caption": None
        }
    }
    if os.path.exists(SYSTEM_SETTINGS_FILE):
        try:
            with open(SYSTEM_SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_settings(settings):
    with open(SYSTEM_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

# ──────────────────────────────────────────
# 🤖 AI Prompt
# ──────────────────────────────────────────

REFERRAL_PROMPT = (
    "You are an expert Amharic digital marketer. "
    "Write a highly compelling, professional, and clear "
    "Telegram channel post based on the raw text provided. "
    "Use emojis naturally. Keep it concise and persuasive."
)

# ──────────────────────────────────────────
# 🗂 States
# ──────────────────────────────────────────

class BotFlow(StatesGroup):
    waiting_for_referral_info      = State()
    waiting_for_regular_post       = State()
    waiting_for_ad_post            = State()
    waiting_for_ad_sign_input      = State()
    waiting_for_manual_post_link   = State()
    waiting_for_btn_text           = State()
    waiting_for_btn_url            = State()
    waiting_for_channel_link       = State()
    waiting_for_channel_name       = State()
    # ✅ New: manual time input states
    waiting_for_custom_sched_mins  = State()
    waiting_for_custom_delete_mins = State()

# ──────────────────────────────────────────
# 🎛 Keyboards
# ──────────────────────────────────────────

def get_main_menu():
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="💸 የሪፈራል ፖስት በ AI ፍጠር",      callback_data="main_referral_ai"))
    b.add(types.InlineKeyboardButton(text="📝 መደበኛ ፖስት (ፅሁፍ/ሚዲያ)",       callback_data="main_regular_post"))
    b.add(types.InlineKeyboardButton(text="📢 ማስታወቂያ ፖስት (ፅሁፍ/ሚዲያ)",     callback_data="main_ad_post"))
    b.add(types.InlineKeyboardButton(text="📡 ቻናሎችን ማስተዳደር",             callback_data="main_manage_channels"))
    b.add(types.InlineKeyboardButton(text="🗑 በማንዋል የፖሰቱትን ማጥፊያ",        callback_data="main_link_delete"))
    b.add(types.InlineKeyboardButton(text="⚙️ የማስታወቂያ ምልክት (Sign) ቀይር", callback_data="main_change_sign"))
    b.adjust(1)
    return b.as_markup()

def get_post_options_menu(has_button=False):
    b = InlineKeyboardBuilder()
    if not has_button:
        b.add(types.InlineKeyboardButton(text="🔗 Inline ሊንክ ቁልፍ ጨምር", callback_data="flow_add_button"))
    b.add(types.InlineKeyboardButton(text="🚀 ቀጣይ (ቻናል ምረጥ)",          callback_data="flow_choose_channel"))
    b.add(types.InlineKeyboardButton(text="↩️ ወደ ዋናው ማውጫ ተመለስ",       callback_data="go_to_main"))
    b.adjust(1)
    return b.as_markup()

def get_ai_result_menu():
    """✅ AI result menu with retry button"""
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="🔄 እንደገና ፍጠር (Retry)",       callback_data="ai_retry"))
    b.add(types.InlineKeyboardButton(text="✅ ይህን ተጠቀም",                 callback_data="ai_use_this"))
    b.add(types.InlineKeyboardButton(text="🔗 Inline ሊንክ ቁልፍ ጨምር",     callback_data="flow_add_button"))
    b.add(types.InlineKeyboardButton(text="🚀 ቀጣይ (ቻናል ምረጥ)",          callback_data="flow_choose_channel"))
    b.add(types.InlineKeyboardButton(text="↩️ ወደ ዋናው ማውጫ ተመለስ",       callback_data="go_to_main"))
    b.adjust(1)
    return b.as_markup()

def get_schedule_menu():
    """✅ Schedule menu with custom time option"""
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="⚡️ አሁኑኑ ቀጥታ",           callback_data="sched_0"))
    b.add(types.InlineKeyboardButton(text="⏱ ከ 30 ደቂቃ በኋላ",        callback_data="sched_30"))
    b.add(types.InlineKeyboardButton(text="⏱ ከ 1 ሰዓት በኋላ",         callback_data="sched_60"))
    b.add(types.InlineKeyboardButton(text="⏱ ከ 3 ሰዓት በኋላ",         callback_data="sched_180"))
    b.add(types.InlineKeyboardButton(text="⏱ ከ 6 ሰዓት በኋላ",         callback_data="sched_360"))
    b.add(types.InlineKeyboardButton(text="✏️ ሌላ ሰዓት ጻፍ (Manual)", callback_data="sched_custom"))
    b.adjust(1)
    return b.as_markup()

def get_delete_menu():
    """✅ Delete menu with custom time option"""
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="♾ ለዘላለም ይኑር",                   callback_data="deltime_never"))
    b.add(types.InlineKeyboardButton(text="🗑 ከ 30 ደቂቃ በኋላ",               callback_data="deltime_30"))
    b.add(types.InlineKeyboardButton(text="🗑 ከ 1 ሰዓት በኋላ (+6 ደቂቃ)",      callback_data="deltime_60"))
    b.add(types.InlineKeyboardButton(text="🗑 ከ 3 ሰዓት በኋላ (+6 ደቂቃ)",      callback_data="deltime_180"))
    b.add(types.InlineKeyboardButton(text="🗑 ከ 6 ሰዓት በኋላ (+6 ደቂቃ)",      callback_data="deltime_360"))
    b.add(types.InlineKeyboardButton(text="🗑 ከ 24 ሰዓት በኋላ (+6 ደቂቃ)",     callback_data="deltime_1440"))
    b.add(types.InlineKeyboardButton(text="✏️ ሌላ ሰዓት ጻፍ (Manual)",        callback_data="deltime_custom"))
    b.adjust(1)
    return b.as_markup()

def back_button(cb="go_to_main"):
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data=cb))
    return b.as_markup()

# ──────────────────────────────────────────
# 🛠 Scheduler — Send & Delete
# ──────────────────────────────────────────

async def send_scheduled_post(
    channel_id, content_type, file_id,
    text_content, reply_markup, post_type,
    delete_after_mins=None
):
    msg_ids = []
    try:
        main_msg = None

        # ✅ link_preview_is_disabled set globally via DefaultBotProperties
        if content_type == "text":
            main_msg = await bot.send_message(
                chat_id=channel_id,
                text=text_content or " ",
                reply_markup=reply_markup
            )
        elif content_type == "photo":
            main_msg = await bot.send_photo(
                chat_id=channel_id,
                photo=file_id,
                caption=text_content,
                reply_markup=reply_markup
            )
        elif content_type == "video":
            main_msg = await bot.send_video(
                chat_id=channel_id,
                video=file_id,
                caption=text_content,
                reply_markup=reply_markup
            )
        elif content_type == "animation":
            main_msg = await bot.send_animation(
                chat_id=channel_id,
                animation=file_id,
                caption=text_content,
                reply_markup=reply_markup
            )
        elif content_type == "document":
            main_msg = await bot.send_document(
                chat_id=channel_id,
                document=file_id,
                caption=text_content,
                reply_markup=reply_markup
            )
        elif content_type == "audio":
            main_msg = await bot.send_audio(
                chat_id=channel_id,
                audio=file_id,
                caption=text_content,
                reply_markup=reply_markup
            )
        elif content_type == "voice":
            main_msg = await bot.send_voice(
                chat_id=channel_id,
                voice=file_id,
                caption=text_content,
                reply_markup=reply_markup
            )

        if main_msg:
            msg_ids.append(main_msg.message_id)

        # ── Send ad sign below ──
        if post_type == "ad":
            settings = load_settings()
            sign = settings.get("ad_sign", {
                "content_type": "text",
                "text": "ማስታወቂያ ብቻ ❗️",
                "file_id": None,
                "caption": None
            })
            sign_msg = None
            ct = sign.get("content_type", "text")

            if ct == "text":
                sign_msg = await bot.send_message(
                    chat_id=channel_id,
                    text=sign.get("text") or "ማስታወቂያ ብቻ ❗️"
                )
            elif ct == "sticker":
                sign_msg = await bot.send_sticker(
                    chat_id=channel_id,
                    sticker=sign["file_id"]
                )
            elif ct == "photo":
                sign_msg = await bot.send_photo(
                    chat_id=channel_id,
                    photo=sign["file_id"],
                    caption=sign.get("caption") or None
                )
            elif ct == "video":
                sign_msg = await bot.send_video(
                    chat_id=channel_id,
                    video=sign["file_id"],
                    caption=sign.get("caption") or None
                )
            elif ct == "animation":
                sign_msg = await bot.send_animation(
                    chat_id=channel_id,
                    animation=sign["file_id"],
                    caption=sign.get("caption") or None
                )
            elif ct == "document":
                sign_msg = await bot.send_document(
                    chat_id=channel_id,
                    document=sign["file_id"],
                    caption=sign.get("caption") or None
                )

            if sign_msg:
                msg_ids.append(sign_msg.message_id)

        # ── Schedule deletion of ALL messages together ──
        if msg_ids and delete_after_mins and delete_after_mins > 0:
            run_time = datetime.now() + timedelta(minutes=delete_after_mins + 6)
            scheduler.add_job(
                delete_expired_posts, "date",
                run_date=run_time,
                args=[channel_id, msg_ids]
            )

    except Exception as e:
        logging.error(f"ፖስት መላክ አልተቻለም፦ {e}")


async def delete_expired_posts(channel_id, message_ids: list):
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id=channel_id, message_id=msg_id)
            logging.info(f"ጠፍቷል፦ {msg_id}")
        except Exception as e:
            logging.error(f"ማጥፋት አልተቻለም፦ {e}")

# ──────────────────────────────────────────
# 🚦 /start
# ──────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.reply(
        "👑 <b>የማስተዳደሪያ ማዕከል</b>\nየሚፈልጉትን ተግባር ይምረጡ፦",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "go_to_main")
async def handle_go_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🎛 <b>ዋናው ማውጫ</b>",
        reply_markup=get_main_menu()
    )
    await callback.answer()

# ──────────────────────────────────────────
# ⚙️ Ad Sign — Save ALL media types
# ──────────────────────────────────────────

@dp.callback_query(F.data == "main_change_sign")
async def change_sign_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_ad_sign_input)
    await callback.message.edit_text(
        "⚙️ <b>የማስታወቂያ ምልክት (Ad Sign) መቀየሪያ</b>\n\n"
        "ማስታወቂያ ከተለቀቀ ወዲያውኑ ከስር የሚከተለውን ይላኩልኝ፦\n\n"
        "📝 ፅሁፍ\n"
        "🎭 ስቲከር\n"
        "🖼 ፎቶ (ካፕሽን ጨምረው ወይም ሳይጨምሩ)\n"
        "🎬 ቪዲዮ\n"
        "🎞 GIF / Animation\n"
        "📄 ዶኩሜንት\n\n"
        "ወይም ከሌላ ቦታ <b>Forward</b> አድርገው ይላኩልኝ፦",
        reply_markup=back_button()
    )
    await callback.answer()

@dp.message(BotFlow.waiting_for_ad_sign_input)
async def change_sign_save(message: types.Message, state: FSMContext):
    """✅ Fixed: accepts ALL media types for ad sign"""
    settings = load_settings()
    sign = {}
    preview = ""

    if message.sticker:
        sign = {
            "content_type": "sticker",
            "text": None,
            "file_id": message.sticker.file_id,
            "caption": None
        }
        preview = "🎭 <b>ስቲከር</b> ተመዝግቧል"

    elif message.photo:
        caption = message.caption_html if message.caption else None
        sign = {
            "content_type": "photo",
            "text": None,
            "file_id": message.photo[-1].file_id,
            "caption": caption
        }
        preview = "🖼 <b>ፎቶ</b> ተመዝግቧል" + (f"\n📝 {caption[:80]}" if caption else "")

    elif message.video:
        caption = message.caption_html if message.caption else None
        sign = {
            "content_type": "video",
            "text": None,
            "file_id": message.video.file_id,
            "caption": caption
        }
        preview = "🎬 <b>ቪዲዮ</b> ተመዝግቧል" + (f"\n📝 {caption[:80]}" if caption else "")

    elif message.animation:
        caption = message.caption_html if message.caption else None
        sign = {
            "content_type": "animation",
            "text": None,
            "file_id": message.animation.file_id,
            "caption": caption
        }
        preview = "🎞 <b>GIF</b> ተመዝግቧል" + (f"\n📝 {caption[:80]}" if caption else "")

    elif message.document:
        caption = message.caption_html if message.caption else None
        sign = {
            "content_type": "document",
            "text": None,
            "file_id": message.document.file_id,
            "caption": caption
        }
        preview = "📄 <b>ዶኩሜንት</b> ተመዝግቧል" + (f"\n📝 {caption[:80]}" if caption else "")

    elif message.text or message.html_text:
        sign = {
            "content_type": "text",
            "text": message.html_text,
            "file_id": None,
            "caption": None
        }
        preview = f"📝 <b>ፅሁፍ</b> ተመዝግቧል:\n{message.html_text[:100]}"

    else:
        await message.reply(
            "❌ ይህ አይነት ይዘት አልተደገፈም። ፅሁፍ፣ ፎቶ፣ ቪዲዮ፣ GIF፣ ስቲከር፣ ወይም ዶኩሜንት ይላኩ።",
            reply_markup=back_button("main_change_sign")
        )
        return

    settings["ad_sign"] = sign
    save_settings(settings)

    await message.reply(
        f"✅ <b>Ad Sign በተሳካ ሁኔታ ሴቭ ተደርጓል!</b>\n\n{preview}",
        reply_markup=get_main_menu()
    )
    await state.clear()

# ──────────────────────────────────────────
# 📡 Channel Management
# ──────────────────────────────────────────

@dp.callback_query(F.data == "main_manage_channels")
async def manage_channels_menu(callback: types.CallbackQuery):
    channels = load_channels()
    text = "📡 <b>የቻናሎች ማስተዳደሪያ</b>\n\n📋 <b>የተመዘገቡ ቻናሎች፦</b>\n"
    for name, cid in channels.items():
        text += f"• {name} (<code>{cid}</code>)\n"
    if not channels:
        text += "⚠️ ምንም የተመዘገበ ቻናል የለም።"

    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="➕ አዲስ ቻናል ጨምር", callback_data="chan_add_start"))
    if channels:
        b.add(types.InlineKeyboardButton(text="❌ ቻናል ሰርዝ", callback_data="chan_delete_start"))
    b.add(types.InlineKeyboardButton(text="↩️ ወደ ዋናው ማውጫ", callback_data="go_to_main"))
    b.adjust(1)
    await callback.message.edit_text(text, reply_markup=b.as_markup())

@dp.callback_query(F.data == "chan_add_start")
async def channel_add_step1(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_channel_link)
    await callback.message.edit_text(
        "🔗 <b>አዲስ ቻናል መጨመሪያ</b>\n\n"
        "1. ቦቱን በቻናልዎ ላይ <b>Admin</b> ያድርጉት።\n"
        "2. የቻናሉን <b>@username</b> ወይም ID ይላኩሉኝ፦",
        reply_markup=back_button("main_manage_channels")
    )

@dp.message(BotFlow.waiting_for_channel_link)
async def channel_add_step2(message: types.Message, state: FSMContext):
    chat_id = message.text.strip()
    if "t.me/" in chat_id:
        parts = chat_id.split('/')
        chat_id = f"-100{parts[parts.index('c')+1]}" if 'c' in parts else f"@{parts[-1]}"
    elif not chat_id.startswith("@") and not chat_id.startswith("-"):
        chat_id = f"@{chat_id}"
    try:
        chat   = await bot.get_chat(chat_id)
        member = await bot.get_chat_member(chat_id=chat.id, user_id=bot.id)
        if member.status in ["administrator", "creator"]:
            await state.update_data(verified_chat_id=str(chat.id))
            await state.set_state(BotFlow.waiting_for_channel_name)
            await message.reply(
                f"✅ አድሚንነቱ ተረጋግጧል! (<b>{chat.title}</b>)\n\n"
                "✍️ በምርጫ ማውጫ ላይ እንዲታይ የሚፈልጉትን <b>የቻናሉን መለያ ስም</b> ይጻፉልኝ፦"
            )
        else:
            await message.reply("❌ ቦቱ አድሚን አልተደረገም። እባክዎ መጀመሪያ አድሚን ያድርጉት።")
    except Exception:
        await message.reply("❌ ቻናሉ አልተገኘም! ቦቱ መታከሉን ያረጋግጡ።")

@dp.message(BotFlow.waiting_for_channel_name)
async def channel_add_step3(message: types.Message, state: FSMContext):
    name     = message.text.strip()
    data     = await state.get_data()
    channels = load_channels()
    channels[name] = data.get("verified_chat_id")
    save_channels(channels)
    await message.reply(
        f"✅ '<b>{name}</b>' በተሳካ ሁኔታ ተመዝግቧል!",
        reply_markup=get_main_menu()
    )
    await state.clear()

@dp.callback_query(F.data == "chan_delete_start")
async def channel_delete_menu(callback: types.CallbackQuery):
    channels = load_channels()
    b = InlineKeyboardBuilder()
    for name in channels.keys():
        b.add(types.InlineKeyboardButton(text=f"🗑 {name}", callback_data=f"delc_{name}"))
    b.add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="main_manage_channels"))
    b.adjust(1)
    await callback.message.edit_text("❌ መሰረዝ የሚፈልጉትን ቻናል ይምረጡ፦", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("delc_"))
async def channel_delete_execute(callback: types.CallbackQuery):
    name     = callback.data.split("delc_")[1]
    channels = load_channels()
    if name in channels:
        del channels[name]
        save_channels(channels)
    await manage_channels_menu(callback)

# ──────────────────────────────────────────
# 💸 Referral Post — Groq AI + Retry
# ──────────────────────────────────────────

async def _run_groq(user_text: str) -> str:
    completion = groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": REFERRAL_PROMPT},
            {"role": "user",   "content": user_text}
        ],
        model="llama-3.3-70b-versatile",
    )
    return completion.choices[0].message.content

@dp.callback_query(F.data == "main_referral_ai")
async def handle_referral_ai(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_referral_info)
    await callback.message.edit_text(
        "💰 ስለ ስራው/ፕሮዳክቱ መረጃ ይጻፉ፤ AI ፖስቱን ይጽፍልዎታል፦",
        reply_markup=back_button()
    )

@dp.message(BotFlow.waiting_for_referral_info)
async def process_referral_ai(message: types.Message, state: FSMContext):
    wait = await message.reply("⏳ AI እያዘጋጀ ነው...")
    try:
        ai_text = await _run_groq(message.text)
        # Save original prompt for retry
        await state.update_data(
            referral_raw_text=message.text,
            final_text=ai_text,
            content_type="text",
            file_id=None,
            post_type="regular",
            btn_text=None,
            btn_url=None
        )
        await bot.delete_message(chat_id=message.chat.id, message_id=wait.message_id)
        await message.reply(
            f"✨ <b>AI የጻፈው ፖስት፦</b>\n\n{ai_text}",
            reply_markup=get_ai_result_menu()
        )
    except Exception as e:
        await bot.delete_message(chat_id=message.chat.id, message_id=wait.message_id)
        await message.reply(f"❌ ስህተት: {e}", reply_markup=get_main_menu())

@dp.callback_query(F.data == "ai_retry")
async def ai_retry(callback: types.CallbackQuery, state: FSMContext):
    """✅ Retry — regenerate with same prompt"""
    data = await state.get_data()
    raw  = data.get("referral_raw_text", "")
    if not raw:
        await callback.answer("❌ የመጀመሪያው ጥያቄ አልተገኘም።", show_alert=True)
        return
    await callback.message.edit_text("⏳ AI እንደገና እያዘጋጀ ነው...")
    try:
        ai_text = await _run_groq(raw)
        await state.update_data(final_text=ai_text)
        await callback.message.edit_text(
            f"✨ <b>AI የጻፈው ፖስት (ድጋሚ)፦</b>\n\n{ai_text}",
            reply_markup=get_ai_result_menu()
        )
    except Exception as e:
        await callback.message.edit_text(f"❌ ስህተት: {e}", reply_markup=get_main_menu())

@dp.callback_query(F.data == "ai_use_this")
async def ai_use_this(callback: types.CallbackQuery, state: FSMContext):
    """Confirm using current AI text and proceed"""
    await callback.message.edit_text(
        "✅ <b>ፖስቱ ተይዟል!</b>\n\nቀጥሎ ምን ማድረግ ይፈልጋሉ?",
        reply_markup=get_post_options_menu()
    )
    await callback.answer()

# ──────────────────────────────────────────
# 📝 Regular & Ad Post — Receive ALL media
# ──────────────────────────────────────────

@dp.callback_query(F.data.in_({"main_regular_post", "main_ad_post"}))
async def handle_post_input_start(callback: types.CallbackQuery, state: FSMContext):
    ptype = "regular" if callback.data == "main_regular_post" else "ad"
    await state.set_state(
        BotFlow.waiting_for_regular_post if ptype == "regular"
        else BotFlow.waiting_for_ad_post
    )
    await state.update_data(post_type=ptype)
    label = "📝 መደበኛ ፖስት" if ptype == "regular" else "📢 የማስታወቂያ ፖስት"
    await callback.message.edit_text(
        f"<b>{label} ማዘጋጃ</b>\n\n"
        "ፖስቱን እዚህ ይላኩ ወይም ከሌላ ቦታ <b>Forward</b> ያድርጉልኝ፦\n\n"
        "ይደገፋሉ: ፅሁፍ, ፎቶ, ቪዲዮ, GIF, ዶኩሜንት, ኦዲዮ, ቮይስ",
        reply_markup=back_button()
    )

@dp.message(BotFlow.waiting_for_regular_post)
@dp.message(BotFlow.waiting_for_ad_post)
async def process_incoming_post(message: types.Message, state: FSMContext):
    """✅ Fixed: accepts ALL media types"""
    content_type = "text"
    file_id      = None

    if message.photo:
        content_type, file_id = "photo",     message.photo[-1].file_id
    elif message.video:
        content_type, file_id = "video",     message.video.file_id
    elif message.animation:
        content_type, file_id = "animation", message.animation.file_id
    elif message.document:
        content_type, file_id = "document",  message.document.file_id
    elif message.audio:
        content_type, file_id = "audio",     message.audio.file_id
    elif message.voice:
        content_type, file_id = "voice",     message.voice.file_id

    raw_text = (
        message.caption_html if content_type != "text"
        else (message.html_text or "")
    )

    await state.update_data(
        final_text=raw_text,
        content_type=content_type,
        file_id=file_id,
        btn_text=None,
        btn_url=None
    )
    await message.reply(
        "✅ <b>ይዘቱ በተሳካ ሁኔታ ተይዟል!</b>",
        reply_markup=get_post_options_menu()
    )

# ──────────────────────────────────────────
# 🔗 Inline Button
# ──────────────────────────────────────────

@dp.callback_query(F.data == "flow_add_button")
async def handle_flow_add_button(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.reply("✏️ በቁልፉ ላይ የሚጻፈውን ስም ያስገቡ፦")
    await state.set_state(BotFlow.waiting_for_btn_text)
    await callback.answer()

@dp.message(BotFlow.waiting_for_btn_text)
async def get_btn_text(message: types.Message, state: FSMContext):
    await state.update_data(btn_text=message.text)
    await message.reply("🔗 ሊንኩን (URL) ያስገቡ፦")
    await state.set_state(BotFlow.waiting_for_btn_url)

@dp.message(BotFlow.waiting_for_btn_url)
async def get_btn_url(message: types.Message, state: FSMContext):
    if not message.text.startswith(("http://", "https://", "t.me/")):
        return await message.reply("❌ ትክክለኛ ሊንክ አይደለም!")
    await state.update_data(btn_url=message.text)
    await message.reply("✅ ሊንኩ ተይዟል።", reply_markup=get_post_options_menu(has_button=True))

# ──────────────────────────────────────────
# 📊 Channel → Schedule → Delete → Confirm → Execute
# ──────────────────────────────────────────

@dp.callback_query(F.data == "flow_choose_channel")
async def handle_flow_choose_channel(callback: types.CallbackQuery):
    channels = load_channels()
    if not channels:
        return await callback.message.edit_text(
            "⚠️ መጀመሪያ ቻናል ይመዝግቡ!", reply_markup=get_main_menu()
        )
    b = InlineKeyboardBuilder()
    for name, cid in channels.items():
        b.add(types.InlineKeyboardButton(text=name, callback_data=f"selchan_{cid}"))
    b.add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main"))
    b.adjust(2)
    await callback.message.edit_text("🚀 <b>ቻናል ይምረጡ፦</b>", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("selchan_"))
async def process_channel_selection(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(target_channel=callback.data.split("selchan_")[1])
    await callback.message.edit_text(
        "⏰ <b>የመልቀቂያ ሰዓት፦</b>",
        reply_markup=get_schedule_menu()
    )

# ── Schedule handlers ──

@dp.callback_query(F.data.startswith("sched_"))
async def process_schedule_selection(callback: types.CallbackQuery, state: FSMContext):
    val = callback.data.split("sched_")[1]

    if val == "custom":
        # ✅ Ask for manual input
        await state.set_state(BotFlow.waiting_for_custom_sched_mins)
        await callback.message.edit_text(
            "✏️ <b>የሚፈልጉትን ደቂቃ ብዛት ይጻፉ</b>\n\n"
            "ምሳሌ: <code>45</code> (45 ደቂቃ)\n"
            "ወይም: <code>120</code> (2 ሰዓት)",
            reply_markup=back_button()
        )
        return

    await state.update_data(schedule_after_mins=int(val))
    await callback.message.edit_text(
        "🗑 <b>የማጥፊያ ሰዓት (Auto-Delete)፦</b>",
        reply_markup=get_delete_menu()
    )

@dp.message(BotFlow.waiting_for_custom_sched_mins)
async def handle_custom_sched(message: types.Message, state: FSMContext):
    try:
        mins = int(message.text.strip())
        if mins < 0:
            raise ValueError
        await state.update_data(schedule_after_mins=mins)
        await message.reply(
            f"✅ ከ <b>{mins}</b> ደቂቃ በኋላ ይለቃል።\n\n"
            "🗑 <b>የማጥፊያ ሰዓት (Auto-Delete)፦</b>",
            reply_markup=get_delete_menu()
        )
        await state.set_state(None)
    except ValueError:
        await message.reply("❌ ትክክለኛ ቁጥር ያስገቡ። ምሳሌ: <code>45</code>")

# ── Delete time handlers ──

@dp.callback_query(F.data.startswith("deltime_"))
async def process_delete_selection(callback: types.CallbackQuery, state: FSMContext):
    val = callback.data.split("deltime_")[1]

    if val == "custom":
        # ✅ Ask for manual delete time
        await state.set_state(BotFlow.waiting_for_custom_delete_mins)
        await callback.message.edit_text(
            "✏️ <b>ፖስቱ ከስንት ደቂቃ በኋላ ይጥፋ?</b>\n\n"
            "ምሳሌ: <code>90</code> (1.5 ሰዓት)\n"
            "ወይም: <code>720</code> (12 ሰዓት)",
            reply_markup=back_button()
        )
        return

    delete_mins = 0 if val == "never" else int(val)
    await state.update_data(delete_after_mins=delete_mins)
    await _show_confirmation(callback, state)

@dp.message(BotFlow.waiting_for_custom_delete_mins)
async def handle_custom_delete(message: types.Message, state: FSMContext):
    try:
        mins = int(message.text.strip())
        if mins < 0:
            raise ValueError
        await state.update_data(delete_after_mins=mins)
        await state.set_state(None)
        # Show confirmation as a new message
        class FakeCallback:
            def __init__(self, msg):
                self.message = msg
            async def answer(self): pass
        await _show_confirmation(FakeCallback(message), state, as_reply=True)
    except ValueError:
        await message.reply("❌ ትክክለኛ ቁጥር ያስገቡ። ምሳሌ: <code>90</code>")

async def _show_confirmation(callback_or_fake, state: FSMContext, as_reply=False):
    data        = await state.get_data()
    delete_mins = data.get("delete_after_mins", 0)
    sched_mins  = data.get("schedule_after_mins", 0)
    ptype_label = "📢 ማስታወቂያ (Sign ይከተለዋል)" if data.get("post_type") == "ad" else "📝 መደበኛ ፖስት"
    preview     = (data.get("final_text") or "")[:200]
    del_label   = "ለዘለዓለም" if delete_mins == 0 else f"ከ {delete_mins + 6} ደቂቃ በኋላ"

    text = (
        "⚠️ <b>የመጨረሻ ማረጋገጫ</b>\n\n"
        f"🔹 <b>አይነት፦</b> {ptype_label}\n"
        f"📢 <b>መድረሻ፦</b> <code>{data.get('target_channel')}</code>\n"
        f"⏰ <b>መልቀቂያ፦</b> ከ {sched_mins} ደቂቃ በኋላ\n"
        f"🗑 <b>ማጥፊያ፦</b> {del_label}\n\n"
        f"📄 <b>ቅድመ-ዕይታ፦</b>\n"
        f"{'─'*28}\n"
        f"{preview}{'...' if len(data.get('final_text') or '') > 200 else ''}\n"
        f"{'─'*28}"
    )
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="✅ አረጋግጣለሁ — ፈጽም! 🚀", callback_data="execute_final_post"))
    b.add(types.InlineKeyboardButton(text="❌ ሰርዝና ተመለስ",          callback_data="go_to_main"))
    b.adjust(1)

    if as_reply:
        await callback_or_fake.message.reply(text, reply_markup=b.as_markup())
    else:
        await callback_or_fake.message.edit_text(text, reply_markup=b.as_markup())

@dp.callback_query(F.data == "execute_final_post")
async def execute_final_post(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()

    reply_markup = None
    if data.get("btn_text") and data.get("btn_url"):
        kb = InlineKeyboardBuilder()
        kb.add(types.InlineKeyboardButton(text=data["btn_text"], url=data["btn_url"]))
        reply_markup = kb.as_markup()

    sched_mins  = data.get("schedule_after_mins", 0)
    delete_mins = data.get("delete_after_mins", 0)
    args = [
        data.get("target_channel"),
        data.get("content_type"),
        data.get("file_id"),
        data.get("final_text"),
        reply_markup,
        data.get("post_type", "regular"),
        delete_mins
    ]

    if sched_mins > 0:
        run_time = datetime.now() + timedelta(minutes=sched_mins)
        scheduler.add_job(send_scheduled_post, "date", run_date=run_time, args=args)
        msg_out = f"📅 ፖስቱ ከ <b>{sched_mins}</b> ደቂቃ በኋላ ይለቃል!"
    else:
        await send_scheduled_post(*args)
        msg_out = "🚀 ፖስቱ አሁኑኑ ቀጥታ ተለቋል!"

    await callback.message.edit_text(msg_out, reply_markup=get_main_menu())
    await state.clear()

# ──────────────────────────────────────────
# 🗑 Manual Delete by Link
# ──────────────────────────────────────────

@dp.callback_query(F.data == "main_link_delete")
async def manual_link_delete_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_manual_post_link)
    await callback.message.edit_text(
        "🗑 <b>በሊንክ ማጥፊያ</b>\n\nየፖስቱን ሊንክ እዚህ ይላኩልኝ፦",
        reply_markup=back_button()
    )

@dp.message(BotFlow.waiting_for_manual_post_link)
async def process_manual_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    try:
        parts      = link.split('/')
        msg_id     = int(parts[-1])
        chan_part  = parts[-2]
        channel_id = f"-100{parts[-3]}" if chan_part == "c" else f"@{chan_part}"
        await state.update_data(target_channel=channel_id, manual_msg_id=msg_id)

        b = InlineKeyboardBuilder()
        b.add(types.InlineKeyboardButton(text="🗑 ከ 30 ደቂቃ በኋላ",          callback_data="man_del_30"))
        b.add(types.InlineKeyboardButton(text="🗑 ከ 1 ሰዓት በኋላ (+6 ደቂቃ)", callback_data="man_del_60"))
        b.add(types.InlineKeyboardButton(text="🗑 ከ 6 ሰዓት በኋላ (+6 ደቂቃ)", callback_data="man_del_360"))
        b.add(types.InlineKeyboardButton(text="🗑 ከ 24 ሰዓት (+6 ደቂቃ)",     callback_data="man_del_1440"))
        b.add(types.InlineKeyboardButton(text="✏️ ሌላ ሰዓት ጻፍ (Manual)",   callback_data="man_del_custom"))
        b.adjust(1)
        await message.reply("📍 ፖስቱ ተለይቷል! ከስንት ሰዓት በኋላ ይጥፋ?", reply_markup=b.as_markup())
    except Exception:
        await message.reply("❌ ሊንኩ ትክክል አይደለም።", reply_markup=get_main_menu())

@dp.callback_query(F.data.startswith("man_del_"))
async def execute_manual_link_delete(callback: types.CallbackQuery, state: FSMContext):
    val = callback.data.split("man_del_")[1]

    if val == "custom":
        await callback.message.edit_text(
            "✏️ <b>ከስንት ደቂቃ በኋላ ይጥፋ?</b>\n\nምሳሌ: <code>90</code>",
            reply_markup=back_button("main_link_delete")
        )
        await state.set_state(BotFlow.waiting_for_custom_delete_mins)
        # Store that we're in manual-link mode
        await state.update_data(manual_link_mode=True)
        await callback.answer()
        return

    del_mins = int(val)
    actual   = del_mins + 6 if del_mins > 0 else del_mins
    data     = await state.get_data()
    run_time = datetime.now() + timedelta(minutes=actual)
    scheduler.add_job(
        delete_expired_posts, "date", run_date=run_time,
        args=[data.get("target_channel"), [data.get("manual_msg_id")]]
    )
    await callback.message.edit_text(
        f"✅ ከ <b>{actual}</b> ደቂቃ በኋላ እንዲጠፋ ተቀጥሯል!",
        reply_markup=get_main_menu()
    )
    await state.clear()

# ──────────────────────────────────────────
# 🚀 Entry Point
# ──────────────────────────────────────────

async def main():
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
