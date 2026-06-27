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
from groq import Groq
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 📝 ሎግ መቆጣጠሪያ
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
groq_client = Groq(api_key=GROQ_API_KEY)
scheduler = AsyncIOScheduler()

CHANNELS_FILE = "channels.json"
SYSTEM_SETTINGS_FILE = "settings.json"

# 📂 የፋይል አያያዝ ተግባራት
def load_channels():
    if os.path.exists(CHANNELS_FILE):
        try: with open(CHANNELS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return {}
    return {}

def save_channels(channels_data):
    with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump(channels_data, f, ensure_ascii=False, indent=4)

def load_settings():
    default_settings = {
        "ad_sign": {
            "content_type": "text",
            "text": "ማስታወቂያ ብቻ ❗️",
            "file_id": None
        }
    }
    if os.path.exists(SYSTEM_SETTINGS_FILE):
        try:
            with open(SYSTEM_SETTINGS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return default_settings
    return default_settings

def save_settings(settings):
    with open(SYSTEM_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

REFERRAL_PROMPT = "You are an expert Amharic digital marketer. Write a highly compelling, professional, and clear Telegram channel post based on the raw text provided."

class BotFlow(StatesGroup):
    waiting_for_referral_info = State()
    waiting_for_regular_post = State()
    waiting_for_ad_post = State()
    waiting_for_ad_sign_input = State() # 🆕 ምልክት መቀበያ
    waiting_for_manual_post_link = State()
    waiting_for_btn_text = State()
    waiting_for_btn_url = State()
    waiting_for_channel_link = State()
    waiting_for_channel_name = State()

# --- 🛠 የጀርባ ስራዎች (Scheduler Tasks) ---

async def send_scheduled_post(channel_id, content_type, file_id, text_content, reply_markup, post_type, delete_after_mins=None):
    msg_ids = []
    try:
        main_msg = None
        # 1. ኦሪጂናል ማስታወቂያውን ወይም መደበኛ ፖስቱን መለጠፍ (ያለ ምንም ጭማሪ ፅሁፍ)
        if content_type == "text":
            main_msg = await bot.send_message(chat_id=channel_id, text=text_content, reply_markup=reply_markup, parse_mode="HTML")
        elif content_type == "photo":
            main_msg = await bot.send_photo(chat_id=channel_id, photo=file_id, caption=text_content, reply_markup=reply_markup, parse_mode="HTML")
        elif content_type == "video":
            main_msg = await bot.send_video(chat_id=channel_id, video=file_id, caption=text_content, reply_markup=reply_markup, parse_mode="HTML")
        elif content_type == "animation":
            main_msg = await bot.send_animation(chat_id=channel_id, animation=file_id, caption=text_content, reply_markup=reply_markup, parse_mode="HTML")
            
        if main_msg:
            msg_ids.append(main_msg.message_id)
            
        # 2. ፖስቱ "ማስታወቂያ" ከሆነ ብቻ ሴቭ የተደረገውን ምልክት (Sign) ቀጥሎ መለጠፍ
        if post_type == "ad":
            settings = load_settings()
            sign = settings.get("ad_sign", {"content_type": "text", "text": "ማስታወቂያ ብቻ ❗️", "file_id": None})
            sign_msg = None
            
            if sign["content_type"] == "text":
                sign_msg = await bot.send_message(chat_id=channel_id, text=sign["text"], parse_mode="HTML")
            elif sign["content_type"] == "sticker":
                sign_msg = await bot.send_sticker(chat_id=channel_id, sticker=sign["file_id"])
            elif sign["content_type"] == "photo":
                sign_msg = await bot.send_photo(chat_id=channel_id, photo=sign["file_id"])
                
            if sign_msg:
                msg_ids.append(sign_msg.message_id)
                
        # ⏱ የማጥፊያ ሰዓት ከታዘዘ ሁለቱንም መልዕክቶች በአንድ ላይ እንዲጠፉ መቅጠር
        if msg_ids and delete_after_mins and delete_after_mins > 0:
            actual_delay = delete_after_mins + 6
            run_time = datetime.now() + timedelta(minutes=actual_delay)
            scheduler.add_job(delete_expired_posts, 'date', run_date=run_time, args=[channel_id, msg_ids])
            
    except Exception as e:
        logging.error(f"ፖስት መላክ አልተቻለም፦ {e}")

async def delete_expired_posts(channel_id, message_ids):
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id=channel_id, message_id=msg_id)
            logging.info(f"መልዕክት በራሱ ጊዜ ጠፍቷል፦ {msg_id}")
        except Exception as e:
            logging.error(f"ማጥፋት አልተቻለም፦ {e}")

# --- 🎛 የቁልፍ ሰሌዳዎች ---

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="💸 የሪፈራል ፖስት በ AI ፍጠር", callback_data="main_referral_ai"))
    builder.add(types.InlineKeyboardButton(text="📝 መደበኛ ፖስት (ፅሁፍ/ሚዲያ)", callback_data="main_regular_post"))
    builder.add(types.InlineKeyboardButton(text="📢 ማስታወቂያ ፖስት (ፅሁፍ/ሚዲያ)", callback_data="main_ad_post"))
    builder.add(types.InlineKeyboardButton(text="📡 ቻናሎችን ማስተዳደር", callback_data="main_manage_channels"))
    builder.add(types.InlineKeyboardButton(text="🗑 በማንዋል የፖሰቱትን ማጥፊያ", callback_data="main_link_delete"))
    builder.add(types.InlineKeyboardButton(text="⚙️ የማስታወቂያ ምልክት (Sign) ቀይር", callback_data="main_change_sign"))
    builder.adjust(1)
    return builder.as_markup()

def get_post_options_menu(has_button=False):
    builder = InlineKeyboardBuilder()
    if not has_button:
        builder.add(types.InlineKeyboardButton(text="🔗 Inline ሊንክ ቁልፍ ጨምር", callback_data="flow_add_button"))
    builder.add(types.InlineKeyboardButton(text="🚀 ቀጣይ (ቻናል ምረጥ)", callback_data="flow_choose_channel"))
    builder.add(types.InlineKeyboardButton(text="↩️ ወደ ዋናው ማውጫ ተመለስ", callback_data="go_to_main"))
    builder.adjust(1)
    return builder.as_markup()

# --- 🚦 የቦት መቆጣጠሪያዎች (Handlers) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.clear()
    await message.reply("👑 **የማስተዳደሪያ ማዕከል**\nየሚፈልጉትን ተግባር ይምረጡ፦", reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "go_to_main")
async def handle_go_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🎛 **ዋናው ማውጫ**", reply_markup=get_main_menu(), parse_mode="Markdown")
    await callback.answer()

# --- ⚙️ 🆕 የማስታወቂያ ምልክት በፎርዋርድ መቀበያ እና ሴቭ ማድረጊያ ክፍል ---

@dp.callback_query(F.data == "main_change_sign")
async def change_sign_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_ad_sign_input)
    await callback.message.edit_text(
        "⚙️ **የማስታወቂያ ምልክት (Ad Sign) መቀየሪያ**\n\n"
        "እባክዎን ማስታወቂያው እንደተለጠፈ ወዲያውኑ ከስር በሁለተኛ መልዕክትነት እንዲከተል የሚፈልጉትን ፅሁፍ (Custom Emoji ያለበትን) "
        "ወይም ስቲከር/ፎቶ ከሌላ ቦታ **Forward** አድርገው ይላኩሉኝ ወይም እዚህ ይጻፉት፦",
        reply_markup=InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main")).as_markup()
    )
    await callback.answer()

@dp.message(BotFlow.waiting_for_ad_sign_input)
async def change_sign_save(message: types.Message, state: FSMContext):
    settings = load_settings()
    
    if message.sticker:
        settings["ad_sign"] = {"content_type": "sticker", "text": None, "file_id": message.sticker.file_id}
    elif message.photo:
        settings["ad_sign"] = {"content_type": "photo", "text": message.html_text, "file_id": message.photo[-1].file_id}
    else:
        # የ Custom Emoji ቅርፅ እንዳይበላሽ በ HTML ፎርማት ሴቭ ይደረጋል
        settings["ad_sign"] = {"content_type": "text", "text": message.html_text, "file_id": None}
        
    save_settings(settings)
    await message.reply("✅ የማስታወቂያ ምልክቱ በተሳካ ሁኔታ ሴቭ ተደርጓል! ለወደፊት ማስታወቂያዎች በሙሉ ጥቅም ላይ ይውላል።", reply_markup=get_main_menu())
    await state.clear()

# --- 📡 ቻናሎችን ማስተዳደር ---

@dp.callback_query(F.data == "main_manage_channels")
async def manage_channels_menu(callback: types.CallbackQuery):
    channels = load_channels()
    text = "📡 **የቻናሎች ማስተዳደሪያ**\n\n📋 **የተመዘገቡ ቻናሎች፦**\n"
    for name, cid in channels.items(): text += f"• {name} (`{cid}`)\n"
    if not channels: text += "⚠️ ምንም የተመዘገበ ቻናል የለም።"
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="➕ አዲስ ቻናል ጨምር", callback_data="chan_add_start"))
    if channels: builder.add(types.InlineKeyboardButton(text="❌ ቻናል ሰርዝ", callback_data="chan_delete_start"))
    builder.add(types.InlineKeyboardButton(text="↩️ ወደ ዋናው ማውጫ", callback_data="go_to_main"))
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "chan_add_start")
async def channel_add_step1(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_channel_link)
    await callback.message.edit_text(
        "🔗 **አዲስ ቻናል መጨመሪያ**\n\n1. ቦቱን በቻናልዎ ላይ **Admin** ያድርጉት።\n2. የቻናሉን **@username** ወይም ID ይላኩሉኝ፦",
        reply_markup=InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="main_manage_channels")).as_markup()
    )

@dp.message(BotFlow.waiting_for_channel_link)
async def channel_add_step2_check_admin(message: types.Message, state: FSMContext):
    chat_id = message.text.strip()
    if "t.me/" in chat_id:
        parts = chat_id.split('/')
        chat_id = f"-100{parts[parts.index('c')+1]}" if 'c' in parts else f"@{parts[-1]}"
    elif not chat_id.startswith("@") and not chat_id.startswith("-"):
        chat_id = f"@{chat_id}"

    try:
        chat = await bot.get_chat(chat_id)
        bot_member = await bot.get_chat_member(chat_id=chat.id, user_id=bot.id)
        if bot_member.status in ["administrator", "creator"]:
            await state.update_data(verified_chat_id=str(chat.id))
            await state.set_state(BotFlow.waiting_for_channel_name)
            await message.reply(f"✅ አድሚንነቱ ተረጋግጧል! (`{chat.title}`)\n\n✍️ በመምረጫ ማውጫ ላይ እንዲመጣ የሚፈልጉትን **የቻናሉን መለያ ስም** ይጻፉልኝ፦")
        else:
            await message.reply("❌ ቦቱ በቻናሉ ላይ አድሚን አልተደረገም። እባክዎ መጀመሪያ አድሚን ያድርጉት።")
    except Exception:
        await message.reply("❌ ቻናሉ አልተገኘም! ቦቱ መታከሉን ያረጋግጡ።")

@dp.message(BotFlow.waiting_for_channel_name)
async def channel_add_step3_save(message: types.Message, state: FSMContext):
    display_name = message.text.strip()
    data = await state.get_data()
    channels = load_channels()
    channels[display_name] = data.get("verified_chat_id")
    save_channels(channels)
    await message.reply(f"✅ '{display_name}' በተሳካ ሁኔታ ተመዝግቧል!", reply_markup=get_main_menu())
    await state.clear()

@dp.callback_query(F.data == "chan_delete_start")
async def channel_delete_menu(callback: types.CallbackQuery):
    channels = load_channels()
    builder = InlineKeyboardBuilder()
    for name in channels.keys(): builder.add(types.InlineKeyboardButton(text=f"🗑 {name}", callback_data=f"delc_{name}"))
    builder.add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="main_manage_channels"))
    builder.adjust(1)
    await callback.message.edit_text("❌ መሰረዝ የሚፈልጉትን ቻናል ይምረጡ፦", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("delc_"))
async def channel_delete_execute(callback: types.CallbackQuery):
    chan_name = callback.data.split("delc_")[1]
    channels = load_channels()
    if chan_name in channels:
        del channels[chan_name]
        save_channels(channels)
    await manage_channels_menu(callback)

# --- 💸 የሪፈራል ፖስት ፈጣሪ (Groq AI) ---

@dp.callback_query(F.data == "main_referral_ai")
async def handle_referral_ai(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_referral_info)
    await callback.message.edit_text("💰 ስለ ስራው መረጃዎችን ይንገሩኝ፤ AI ይጽፍልዎታል፦", reply_markup=InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main")).as_markup())

@dp.message(BotFlow.waiting_for_referral_info)
async def process_referral_ai(message: types.Message, state: FSMContext):
    waiting_msg = await message.reply("⏳ AI እያዘጋጀ ነው...")
    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": REFERRAL_PROMPT}, {"role": "user", "content": message.text}],
            model="llama-3.3-70b-versatile",
        )
        ai_text = completion.choices[0].message.content
        await state.update_data(final_text=ai_text, content_type="text", file_id=None, post_type="regular", btn_text=None, btn_url=None)
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.reply(f"✨ **የተዘጋጀ ፅሁፍ፦**\n\n{ai_text}", reply_markup=get_post_options_menu(), parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ ስህተት: {e}", reply_markup=get_main_menu())

# --- 📝 መደበኛ እና ማስታወቂያ ፖስት መቀበያ (ንፁህ ይዘት) ---

@dp.callback_query(F.data.in_({"main_regular_post", "main_ad_post"}))
async def handle_post_input_start(callback: types.CallbackQuery, state: FSMContext):
    ptype = "regular" if callback.data == "main_regular_post" else "ad"
    await state.set_state(BotFlow.waiting_for_regular_post if ptype == "regular" else BotFlow.waiting_for_ad_post)
    await state.update_data(post_type=ptype)
    
    label = "📝 መደበኛ ፖስት" if ptype == "regular" else "📢 የማስታወቂያ ፖስት"
    await callback.message.edit_text(f"{label} ማዘጋጃ\n\nእባክዎን ፖስቱን እዚህ ይላኩ ወይም ከሌላ ቦታ **Forward** ያድርጉልኝ፦", reply_markup=InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main")).as_markup())

@dp.message(BotFlow.waiting_for_regular_post)
@dp.message(BotFlow.waiting_for_ad_post)
async def process_incoming_post(message: types.Message, state: FSMContext):
    content_type = "text"
    file_id = None
    if message.photo:
        content_type = "photo"; file_id = message.photo[-1].file_id
    elif message.video:
        content_type = "video"; file_id = message.video.file_id
    elif message.animation:
        content_type = "animation"; file_id = message.animation.file_id

    # ⚠️ እርስዎ የላኩት የማስታወቂያ ፅሁፍ ላይ ምንም አይነት ተጨማሪ ነገር ሳይጨመር እንዳለ ንፁህ ይዘቱ ይወሰዳል
    raw_text = message.html_text if message.html_text else ""
    await state.update_data(final_text=raw_text, content_type=content_type, file_id=file_id, btn_text=None, btn_url=None)
    await message.reply("✅ **ይዘቱ በተሳካ ሁኔታ ተይዟል!**", reply_markup=get_post_options_menu(), parse_mode="HTML")

# --- 🔗 Inline ሊንክ ቁልፍ ---

@dp.callback_query(F.data == "flow_add_button")
async def handle_flow_add_button(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.reply("✏️ በቁልፉ ላይ የሚጻፈውን ስም ያስገቡ፦")
    await state.set_state(BotFlow.waiting_for_btn_text)

@dp.message(BotFlow.waiting_for_btn_text)
async def get_flow_btn_text(message: types.Message, state: FSMContext):
    await state.update_data(btn_text=message.text)
    await message.reply("🔗 ሊንኩን (URL) ያስገቡ፦")
    await state.set_state(BotFlow.waiting_for_btn_url)

@dp.message(BotFlow.waiting_for_btn_url)
async def get_flow_btn_url(message: types.Message, state: FSMContext):
    if not message.text.startswith(("http://", "https://", "t.me/")): return await message.reply("❌ ስህተት ሊንክ!")
    await state.update_data(btn_url=message.text)
    await message.reply("✅ ሊንኩ ተይዟል።", reply_markup=get_post_options_menu(has_button=True))

# --- 📊 የቻናሎች እና የጊዜ ምርጫ ማውጫ ---

@dp.callback_query(F.data == "flow_choose_channel")
async def handle_flow_choose_channel(callback: types.CallbackQuery):
    channels = load_channels()
    if not channels:
        return await callback.message.edit_text("⚠️ መጀመሪያ ቻናል ይመዝግቡ!", reply_markup=get_main_menu())
    builder = InlineKeyboardBuilder()
    for name, cid in channels.items(): builder.add(types.InlineKeyboardButton(text=name, callback_data=f"selchan_{cid}"))
    builder.add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main"))
    builder.adjust(2)
    await callback.message.edit_text("🚀 **ቻናል ይምረጡ፦**", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("selchan_"))
async def process_channel_selection(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(target_channel=callback.data.split("selchan_")[1])
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="⚡️ አሁኑኑ ቀጥታ", callback_data="sched_0"))
    builder.add(types.InlineKeyboardButton(text="⏱ ከ 30 ደቂቃ በኋላ", callback_data="sched_30"))
    builder.add(types.InlineKeyboardButton(text="⏱ ከ 1 ሰዓት በኋላ", callback_data="sched_60"))
    builder.adjust(1)
    await callback.message.edit_text("⏰ **የመልቀቂያ ሰዓት፦**", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("sched_"))
async def process_schedule_selection(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(schedule_after_mins=int(callback.data.split("sched_")[1]))
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="♾ ለዘላለም ይኑር", callback_data="deltime_never"))
    builder.add(types.InlineKeyboardButton(text="🗑 ከ 1 ሰዓት በኋላ (+6 ደቂቃ)", callback_data="deltime_60"))
    builder.add(types.InlineKeyboardButton(text="🗑 ከ 6 ሰዓት በኋላ (+6 ደቂቃ)", callback_data="deltime_360"))
    builder.add(types.InlineKeyboardButton(text="🗑 ከ 24 ሰዓት በኋላ (+6 ደቂቃ)", callback_data="deltime_1440"))
    builder.adjust(1)
    await callback.message.edit_text("🗑 **የማጥፊያ ሰዓት (Auto-Delete)፦**", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("deltime_"))
async def handle_confirmation_screen(callback: types.CallbackQuery, state: FSMContext):
    del_data = callback.data.split("deltime_")[1]
    delete_mins = 0 if del_data == "never" else int(del_data)
    await state.update_data(delete_after_mins=delete_mins)
    
    data = await state.get_data()
    post_type_label = "📢 ማስታወቂያ (ምልክት ይከተለዋል)" if data.get("post_type") == "ad" else "📝 መደበኛ ፖስት"
    
    confirm_text = (
        "⚠️ **የመጨረሻ ማረጋገጫ**\n\n"
        f"🔹 **አይነት፦** {post_type_label}\n"
        f"📢 **መድረሻ፦** `{data.get('target_channel')}`\n"
        f"⏰ **መልቀቂያ፦** ከ {data.get('schedule_after_mins')} ደቂቃ በኋላ\n"
        f"🗑 **ማጥፊያ፦** ከ {delete_mins} ደቂቃ በኋላ\n\n"
        f"📄 **የፖስቱ ቅድመ-ዕይታ፦**\n"
        f"---------------------------\n"
        f"{data.get('final_text')[:200]}...\n"
        f"---------------------------"
    )
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="✅ ሁሉንም አረጋግጣለሁ - ፈጽም! 🚀", callback_data="execute_final_post"))
    builder.add(types.InlineKeyboardButton(text="❌ ሰርዝና ተመለስ", callback_data="go_to_main"))
    builder.adjust(1)
    await callback.message.edit_text(confirm_text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "execute_final_post")
async def execute_final_post(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    post_text = data.get("final_text")
    content_type = data.get("content_type")
    file_id = data.get("file_id")
    target_chan = data.get("target_channel")
    sched_mins = data.get("schedule_after_mins", 0)
    delete_mins = data.get("delete_after_mins", 0)
    post_type = data.get("post_type", "regular")
    
    reply_markup = None
    if data.get("btn_text") and data.get("btn_url"):
        kb_builder = InlineKeyboardBuilder()
        kb_builder.add(types.InlineKeyboardButton(text=data["btn_text"], url=data["btn_url"]))
        reply_markup = kb_builder.as_markup()
        
    if sched_mins > 0:
        run_time = datetime.now() + timedelta(minutes=sched_mins)
        scheduler.add_job(send_scheduled_post, 'date', run_date=run_time, args=[target_chan, content_type, file_id, post_text, reply_markup, post_type, delete_mins])
        msg_out = "📅 ፖስቱ በተሳካ ሁኔታ ተቀጥሯል!"
    else:
        await send_scheduled_post(target_chan, content_type, file_id, post_text, reply_markup, post_type, delete_mins)
        msg_out = "🚀 ፖስቱ አሁኑኑ ቀጥታ ተለቋል!"
        
    await callback.message.edit_text(f"{msg_out}", reply_markup=get_main_menu(), parse_mode="HTML")
    await state.clear()

# --- 🗑 በማንዋል የፖሰቱትን ማጥፊያ (በሊንክ) ---

@dp.callback_query(F.data == "main_link_delete")
async def manual_link_delete_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_manual_post_link)
    await callback.message.edit_text("🗑 **በሊንክ ማጥፊያ**\n\nእባክዎን የፖስቱን ሊንክ እዚህ ይላኩሉኝ፦", reply_markup=InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main")).as_markup())

@dp.message(BotFlow.waiting_for_manual_post_link)
async def process_manual_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    try:
        parts = link.split('/')
        msg_id = int(parts[-1])
        channel_identifier = parts[-2]
        channel_id = f"-100{parts[-3]}" if channel_identifier == "c" else f"@{channel_identifier}"
            
        await state.update_data(target_channel=channel_id, manual_msg_id=msg_id)
        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(text="🗑 ከ 1 ሰዓት በኋላ (+6 ደቂቃ)", callback_data="man_del_60"))
        builder.add(types.InlineKeyboardButton(text="🗑 ከ 24 ሰዓት በኋላ (+6 ደቂቃ)", callback_data="man_del_1440"))
        builder.adjust(1)
        await message.reply(f"📍 ፖስቱ ተለይቷል! ከስንት ሰዓት በኋላ ይጥፋ?", reply_markup=builder.as_markup())
    except Exception:
        await message.reply("❌ የላኩት ሊንክ ትክክል አይደለም።", reply_markup=get_main_menu())

@dp.callback_query(F.data.startswith("man_del_"))
async def execute_manual_link_delete(callback: types.CallbackQuery, state: FSMContext):
    del_mins = int(callback.data.split("man_del_")[1])
    data = await state.get_data()
    actual_delay = del_mins + 6
    run_time = datetime.now() + timedelta(minutes=actual_delay)
    scheduler.add_job(delete_expired_posts, 'date', run_date=run_time, args=[data.get("target_channel"), [data.get("manual_msg_id")]])
    await callback.message.edit_text(f"✅ ከ {actual_delay} ደቂቃ በኋላ እንዲጠፋ ተቀጥሯል!", reply_markup=get_main_menu())
    await state.clear()

async def main():
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
