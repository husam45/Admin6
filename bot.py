import os
import logging
import asyncio
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from groq import Groq
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 📝 የሊኑክስ/Railway ሎግ መቆጣጠሪያ
logging.basicConfig(level=logging.INFO)

# 🔑 የአካባቢ ተለዋዋጮች
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
groq_client = Groq(api_key=GROQ_API_KEY)
scheduler = AsyncIOScheduler()

# 📌 በጊዜያዊ ሚሞሪ የሚቀመጥ የማስታወቂያ ማጠቃለያ ፅሁፍ (Default Footer)
system_settings = {
    "ad_footer": "\n\nማስታወቂያ ብቻ ❗️"
}

REFERRAL_PROMPT = """
You are an expert Amharic digital marketer and copywriter. 
The user will give you raw data about an online referral job/gig (how much it pays, what tasks to do, how to earn).
Your task is to write a highly compelling, professional, and clear Telegram channel post in natural Amharic.
Use appropriate emojis, structure it with bullet points, make the earning potential sound exciting but realistic, and ensure it motivates users to click the link and register immediately.
Do NOT include any generic tags, just output the ready-to-post Amharic text.
"""

CHANNELS = {
    "X Forex 🎬": "@your_x_forex_channel",
    "Squad 4x™ (Main) 🚀": "@your_squad4x_main",
    "Squad 4xx 📚 (PDF)": "@your_squad4xx_pdf",
    "ATA BOOTCAMP 🎯": "@your_ata_bootcamp",
    "HF Trading Hustler 💼": "@your_hf_trading",
    "7ኛው ቻናል ✨": "@your_seventh_channel",
    "Hope fx 🌱": "@your_hope_fx"
}

# 🎭 የቦቱ የሂደት ደረጃዎች (FSM)
class BotFlow(StatesGroup):
    waiting_for_referral_info = State()
    waiting_for_regular_post = State()
    waiting_for_ad_post = State()
    waiting_for_ad_footer_input = State()
    waiting_for_manual_post_link = State()
    waiting_for_btn_text = State()
    waiting_for_btn_url = State()

# --- 🛠 የጀርባ ስራዎች (Scheduler Tasks) ---

async def send_scheduled_post(channel_id, content_type, file_id, text_content, reply_markup, delete_after_mins=None):
    try:
        msg = None
        # ሚዲያዎችን አይነታቸውን ለይቶ በሊንክ ቁልፍ ማስተላለፍ
        if content_type == "text":
            msg = await bot.send_message(chat_id=channel_id, text=text_content, reply_markup=reply_markup, parse_mode="HTML")
        elif content_type == "photo":
            msg = await bot.send_photo(chat_id=channel_id, photo=file_id, caption=text_content, reply_markup=reply_markup, parse_mode="HTML")
        elif content_type == "video":
            msg = await bot.send_video(chat_id=channel_id, video=file_id, caption=text_content, reply_markup=reply_markup, parse_mode="HTML")
        elif content_type == "animation":
            msg = await bot.send_animation(chat_id=channel_id, animation=file_id, caption=text_content, reply_markup=reply_markup, parse_mode="HTML")
            
        if msg:
            logging.info(f"ፖስት በተሳካ ሁኔታ ተለቋል: {channel_id}")
            # ⏱ የተጠቃሚው ሰዓት ላይ 6 ደቂቃ ጨምሮ ማጥፋት (Buffer Time)
            if delete_after_mins and delete_after_mins > 0:
                actual_delay = delete_after_mins + 6
                run_time = datetime.now() + timedelta(minutes=actual_delay)
                scheduler.add_job(delete_expired_post, 'date', run_date=run_time, args=[channel_id, msg.message_id])
    except Exception as e:
        logging.error(f"መላክ አልተቻለም: {e}")

async def delete_expired_post(channel_id, message_id):
    try:
        await bot.delete_message(chat_id=channel_id, message_id=message_id)
        logging.info(f"ማስታወቂያው/ፖስቱ በራሱ ጊዜ ጠፍቷል: {message_id}")
    except Exception as e:
        logging.error(f"ማጥፋት አልተቻለም: {e}")

# --- 🎛 የቁልፍ ሰሌዳዎች (Modular Keyboards) ---

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="💸 የሪፈራል ፖስት በ AI ፍጠር", callback_data="main_referral_ai"))
    builder.add(types.InlineKeyboardButton(text="📝 መደበኛ ፖስት (ፅሁፍ/ፎቶ/ቪዲዮ)", callback_data="main_regular_post"))
    builder.add(types.InlineKeyboardButton(text="📢 ማስታወቂያ ፖስት (ፅሁፍ/ፎቶ/ቪዲዮ)", callback_data="main_ad_post"))
    builder.add(types.InlineKeyboardButton(text="🗑 በማንዋል የፖሰቱትን ማጥፊያ (በሊንክ)", callback_data="main_link_delete"))
    builder.add(types.InlineKeyboardButton(text="⚙️ የማስታወቂያ ፅሁፍ (Footer) ቀይር", callback_data="main_change_footer"))
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
    if message.from_user.id != ADMIN_ID:
        return await message.reply("🔒 ፍቃድ የለዎትም።")
    await state.clear()
    await message.reply("👑 **እንኳን ወደ ማስተዳደሪያ ማዕከሉ በሰላም መጡ!**\nከታች ካሉት አማራጮች አንዱን ይጫኑ፦", reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "go_to_main")
async def handle_go_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🎛 **ዋናው ማውጫ**\nየሚፈልጉትን ተግባር ከታች ይምረጡ፦", reply_markup=get_main_menu(), parse_mode="Markdown")
    await callback.answer()

# --- ⚙️ የማስታወቂያ ፅሁፍ (Footer) ማስተካከያ ክፍል ---

@dp.callback_query(F.data == "main_change_footer")
async def change_footer_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_ad_footer_input)
    current = system_settings['ad_footer'].replace('\n', '')
    await callback.message.edit_text(
        f"⚙️ **የማስታወቂያ ማሳሰቢያ ፅሁፍ መቀየሪያ**\n\nአሁን ያለው ፅሁፍ: `{current}`\n\nእባክዎን አዲስ እንዲሆን የሚፈልጉትን ማሳሰቢያ ይጻፉልኝ (ምሳሌ: `\n\nማስታወቂያ ብቻ ❗️`):",
        reply_markup=InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main")).as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(BotFlow.waiting_for_ad_footer_input)
async def change_footer_save(message: types.Message, state: FSMContext):
    system_settings["ad_footer"] = "\n\n" + message.text.strip()
    await message.reply(f"✅ የማስታወቂያ ማሳሰቢያው በተሳካ ሁኔታ ተቀይሯል! ወደፊት ለሚለቀቁ ማስታወቂያዎች ጥቅም ላይ ይውላል።", reply_markup=get_main_menu())
    await state.clear()

# --- 💸 ክፍል 1፦ የሪፈራል ፖስት ፈጣሪ (Groq AI) ---

@dp.callback_query(F.data == "main_referral_ai")
async def handle_referral_ai(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_referral_info)
    await callback.message.edit_text(
        "💰 **የሪፈራል ፖስት ማዘጋጃ ክፍል (Groq AI)**\n\nስለ ኦንላይን ስራው መረጃዎችን (የሚከፈለውን ብር፣ የሳይቱን ስም) ይንገሩኝ፤ እሱ ማራኪ አድርጎ ይጽፍልዎታል፦",
        reply_markup=InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main")).as_markup()
    )
    await callback.answer()

@dp.message(BotFlow.waiting_for_referral_info)
async def process_referral_ai(message: types.Message, state: FSMContext):
    waiting_msg = await message.reply("⏳ Groq AI የሪፈራል ፖስቱን እያዘጋጀ ነው...")
    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": REFERRAL_PROMPT}, {"role": "user", "content": message.text}],
            model="llama-3.3-70b-versatile",
        )
        ai_text = completion.choices[0].message.content
        await state.update_data(final_text=ai_text, content_type="text", file_id=None, post_type="regular", btn_text=None, btn_url=None)
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.reply(f"✨ **በ AI የተዘጋጀ ፅሁፍ፦**\n\n{ai_text}", reply_markup=get_post_options_menu(), parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ ስህተት: {e}", reply_markup=get_main_menu())

# --- 📝 ክፍል 2 እና 3፦ መደበኛ እና ማስታወቂያ ፖስት መቀበያ (ሁሉንም ሚዲያ እና ፎርዋርድ የሚደግፍ) ---

@dp.callback_query(F.data.in_({"main_regular_post", "main_ad_post"}))
async def handle_post_input_start(callback: types.CallbackQuery, state: FSMContext):
    ptype = "regular" if callback.data == "main_regular_post" else "ad"
    current_state = BotFlow.waiting_for_regular_post if ptype == "regular" else BotFlow.waiting_for_ad_post
    await state.set_state(current_state)
    await state.update_data(post_type=ptype)
    
    label = "📝 መደበኛ ፖስት" if ptype == "regular" else "📢 የማስታወቂያ ፖስት"
    await callback.message.edit_text(
        f"{label} ማዘጋጃ\n\nእባክዎን ፖስት የሚሆነውን **ፅሁፍ፣ ፎቶ፣ ቪዲዮ ወይም ፋይል** እዚህ ይላኩ ወይም ከሌላ ቻናል **Forward** አድርገው ይላኩሉኝ፦",
        reply_markup=InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main")).as_markup()
    )
    await callback.answer()

@dp.message(BotFlow.waiting_for_regular_post)
@dp.message(BotFlow.waiting_for_ad_post)
async def process_incoming_post(message: types.Message, state: FSMContext):
    data = await state.get_data()
    post_type = data.get("post_type", "regular")
    
    # የይዘት አይነት እና ሚዲያ መለየት
    content_type = "text"
    file_id = None
    if message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
    elif message.animation:
        content_type = "animation"
        file_id = message.animation.file_id

    # የኦሪጂናል ፅሁፍ ወይም የካፕሽን ይዘትን ከነፎርማቱ በ HTML መውሰድ
    raw_text = message.html_text if message.html_text else ""
    
    # ማስታወቂያ ከሆነ እርስዎ ያስቀመጡትን ፅሁፍ ብቻ ከስር መቀጠል
    if post_type == "ad":
        raw_text += system_settings["ad_footer"]

    await state.update_data(final_text=raw_text, content_type=content_type, file_id=file_id, btn_text=None, btn_url=None)
    
    await message.reply(
        "✅ **ይዘቱ በተሳካ ሁኔታ ተዘጋጅቷል!**\nከታች ካሉት አማራጮች ቀጣዩን ይምረጡ፦",
        reply_markup=get_post_options_menu(),
        parse_mode="HTML"
    )

# --- 🔗 Inline ሊንክ ቁልፍ ማያያዣ መስመር ---

@dp.callback_query(F.data == "flow_add_button")
async def handle_flow_add_button(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.reply("✏️ በሊንክ ቁልፉ ላይ የሚጻፈውን ስም ያስገቡ (ምሳሌ: `የቴሌግራም ቻናል`):")
    await state.set_state(BotFlow.waiting_for_btn_text)
    await callback.answer()

@dp.message(BotFlow.waiting_for_btn_text)
async def get_flow_btn_text(message: types.Message, state: FSMContext):
    await state.update_data(btn_text=message.text)
    await message.reply("🔗 አሁን ደግሞ ሊንኩን (URL) ያስገቡ፦")
    await state.set_state(BotFlow.waiting_for_btn_url)

@dp.message(BotFlow.waiting_for_btn_url)
async def get_flow_btn_url(message: types.Message, state: FSMContext):
    if not message.text.startswith(("http://", "https://", "t.me/")):
        return await message.reply("❌ እባክህ ትክክለኛ ሊንክ ያስገቡ!")
    await state.update_data(btn_url=message.text)
    await message.reply("✅ የሊንክ ቁልፉ ተይዟል። መድረሻ ቻናል ለመምረጥ ቀጣይ የሚለውን ይጫኑ፦", reply_markup=get_post_options_menu(has_button=True))

# --- 📊 የቻናሎች መምረጫ እና የጊዜ ማስተካከያ ማውጫዎች ---

@dp.callback_query(F.data == "flow_choose_channel")
async def handle_flow_choose_channel(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for name, cid in CHANNELS.items():
        builder.add(types.InlineKeyboardButton(text=name, callback_data=f"selchan_{cid}"))
    builder.add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main"))
    builder.adjust(2)
    await callback.message.edit_text("🚀 **ለመልቀቅ የፈለጉትን ቻናል ይምረጡ፦**", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("selchan_"))
async def process_channel_selection(callback: types.CallbackQuery, state: FSMContext):
    selected_channel = callback.data.split("selchan_")[1]
    await state.update_data(target_channel=selected_channel)
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="⚡️ አሁኑኑ ቀጥታ", callback_data="sched_0"))
    builder.add(types.InlineKeyboardButton(text="⏱ ከ 30 ደቂቃ በኋላ", callback_data="sched_30"))
    builder.add(types.InlineKeyboardButton(text="⏱ ከ 1 ሰዓት በኋላ", callback_data="sched_60"))
    builder.adjust(1)
    await callback.message.edit_text("⏰ **ይህ ፖስት መቼ እንዲለቀቅ ይፈልጋሉ?**", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("sched_"))
async def process_schedule_selection(callback: types.CallbackQuery, state: FSMContext):
    sched_mins = int(callback.data.split("sched_")[1])
    await state.update_data(schedule_after_mins=sched_mins)
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="♾ ለዘላለም ይኑር (አይጥፋ)", callback_data="deltime_never"))
    builder.add(types.InlineKeyboardButton(text="🗑 ከ 1 ሰዓት በኋላ (+6 ደቂቃ ትርፍ)", callback_data="deltime_60"))
    builder.add(types.InlineKeyboardButton(text="🗑 ከ 6 ሰዓት በኋላ (+6 ደቂቃ ትርፍ)", callback_data="deltime_360"))
    builder.add(types.InlineKeyboardButton(text="🗑 ከ 24 ሰዓት በኋላ (+6 ደቂቃ ትርፍ)", callback_data="deltime_1440"))
    builder.adjust(1)
    await callback.message.edit_text("🗑 **ፖስቱ ከቻናሉ ላይ የሚጠፋበት ሰዓት (Auto-Delete)፦**", reply_markup=builder.as_markup())
    await callback.answer()

# --- ⚠️ የመጨረሻ ማረጋገጫ ማውጫ (Double-Check Screen) ---

@dp.callback_query(F.data.startswith("deltime_"))
async def handle_confirmation_screen(callback: types.CallbackQuery, state: FSMContext):
    del_data = callback.data.split("deltime_")[1]
    delete_mins = 0 if del_data == "never" else int(del_data)
    await state.update_data(delete_after_mins=delete_mins)
    
    data = await state.get_data()
    post_type_label = "📢 ማስታወቂያ" if data.get("post_type") == "ad" else "📝 መደበኛ/የሪፈራል ፖስት"
    sched_label = "⚡️ አሁኑኑ" if data.get("schedule_after_mins") == 0 else f"⏱ ከ {data.get('schedule_after_mins')} ደቂቃ በኋላ"
    del_label = f"🗑 ከ {delete_mins + 6} ደቂቃ በኋላ (6 ደቂቃ ትርፍ ተጨምሯል)" if delete_mins > 0 else "♾ ለዘላለም ይኖራል"
        
    confirm_text = (
        "⚠️ **የመጨረሻ ማረጋገጫ (Double-Check)**\n\n"
        f"🔹 **የፖስት አይነት፦** {post_type_label}\n"
        f"📢 **መድረሻ ቻናል፦** {data.get('target_channel')}\n"
        f"⏰ **የመልቀቂያ ሰዓት፦** {sched_label}\n"
        f"🗑 **የማጥፊያ ሰዓት፦** {del_label}\n\n"
        f"📄 **የፅሁፉ ቅድመ-ዕይታ፦**\n"
        f"---------------------------\n"
        f"{data.get('final_text')[:400]}...\n"
        f"---------------------------"
    )
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="✅ ሁሉንም አረጋግጣለሁ - ፈጽም! 🚀", callback_data="execute_final_post"))
    builder.add(types.InlineKeyboardButton(text="❌ ስህተት አለ - ሰርዝና ተመለስ", callback_data="go_to_main"))
    builder.adjust(1)
    
    await callback.message.edit_text(confirm_text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "execute_final_post")
async def execute_final_post(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    post_text = data.get("final_text")
    content_type = data.get("content_type")
    file_id = data.get("file_id")
    target_chan = data.get("target_channel")
    sched_mins = data.get("schedule_after_mins", 0)
    delete_mins = data.get("delete_after_mins", 0)
    
    reply_markup = None
    if data.get("btn_text") and data.get("btn_url"):
        kb_builder = InlineKeyboardBuilder()
        kb_builder.add(types.InlineKeyboardButton(text=data["btn_text"], url=data["btn_url"]))
        reply_markup = kb_builder.as_markup()
        
    if sched_mins > 0:
        run_time = datetime.now() + timedelta(minutes=sched_mins)
        scheduler.add_job(send_scheduled_post, 'date', run_date=run_time, args=[target_chan, content_type, file_id, post_text, reply_markup, delete_mins])
        msg_out = "📅 ፖስቱ በተሳካ ሁኔታ ተቀጥሯል!"
    else:
        await send_scheduled_post(target_chan, content_type, file_id, post_text, reply_markup, delete_mins)
        msg_out = "🚀 ፖስቱ አሁኑኑ ቀጥታ ወደ ቻናልዎ ተለቋል!"
        
    await callback.message.edit_text(f"{msg_out}\n\nወደ ዋናው ማውጫ ተመልሰናል፦", reply_markup=get_main_menu(), parse_mode="HTML")
    await state.clear()
    await callback.answer()

# --- 🗑 ክፍል 4፦ የማንዋል ፖስት ማጥፊያ (በሊንክ) ---

@dp.callback_query(F.data == "main_link_delete")
async def manual_link_delete_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_manual_post_link)
    await callback.message.edit_text(
        "🗑 **የማንዋል ፖስት በሊንክ ማጥፊያ ማዘዣ**\n\nእባክዎን በቻናሉ ላይ በግል የፖሰቱትን የትኛውንም መልዕክት ሊንክ (Post Link) ኮፒ አድርገው እዚህ ይላኩሉኝ፦",
        reply_markup=InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="go_to_main")).as_markup()
    )
    await callback.answer()

@dp.message(BotFlow.waiting_for_manual_post_link)
async def process_manual_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    try:
        # የቴሌግራም ሊንክን ቻናል ID እና የሜሴጅ ID ለመለየት የሚደረግ አሰሳ
        parts = link.split('/')
        msg_id = int(parts[-1])
        channel_identifier = parts[-2]
        
        if channel_identifier == "c":
            raw_id = parts[-3]
            channel_id = f"-100{raw_id}" if not raw_id.startswith("-100") else raw_id
        else:
            channel_id = f"@{channel_identifier}"
            
        await state.update_data(target_channel=channel_id, manual_msg_id=msg_id)
        
        # የሰዓት ምርጫ
        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(text="🗑 ከ 1 ሰዓት በኋላ (+6 ደቂቃ ትርፍ)", callback_data="man_del_60"))
        builder.add(types.InlineKeyboardButton(text="🗑 ከ 24 ሰዓት በኋላ (+6 ደቂቃ ትርፍ)", callback_data="man_del_1440"))
        builder.add(types.InlineKeyboardButton(text="❌ ሰርዝ", callback_data="go_to_main"))
        builder.adjust(1)
        
        await message.reply(f"📍 ፖስቱ ተለይቷል! (ቻናል: `{channel_id}`, መታወቂያ: `{msg_id}`)\n\nከስንት ሰዓት በኋላ እንዲጠፋ ይፈልጋሉ?", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception:
        await message.reply("❌ የላኩት ሊንክ ትክክል አይደለም። እባክዎን ትክክለኛ የቴሌግራም ፖስት ሊንክ መሆኑን አረጋግጠው ድጋሚ ይሞክሩ።", reply_markup=get_main_menu())

@dp.callback_query(F.data.startswith("man_del_"))
async def execute_manual_link_delete(callback: types.CallbackQuery, state: FSMContext):
    del_mins = int(callback.data.split("man_del_")[1])
    data = await state.get_data()
    
    channel_id = data.get("target_channel")
    msg_id = data.get("manual_msg_id")
    actual_delay = del_mins + 6
    
    run_time = datetime.now() + timedelta(minutes=actual_delay)
    scheduler.add_job(delete_expired_post, 'date', run_date=run_time, args=[channel_id, msg_id])
    
    await callback.message.edit_text(
        f"✅ **የማንዋል ማጥፊያ ማዘዣ ተመዝግቧል!**\n\nፖስቱ ከ {actual_delay} ደቂቃ በኋላ ከቻናሉ ላይ በራሱ ይጠፋል።",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )
    await state.clear()
    await callback.answer()

# --- 🚀 ማስነሻ ---
async def main():
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
