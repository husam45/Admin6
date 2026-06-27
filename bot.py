import os
import logging
import asyncio
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

# 🧠 ለሪፈራል ስራዎች የተዘጋጀ ልዩ የ AI መመሪያ (System Prompt)
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
    waiting_for_regular_text = State()
    waiting_for_ad_text = State()
    waiting_for_btn_text = State()
    waiting_for_btn_url = State()

# --- 🛠 የጀርባ ስራዎች (Scheduler Tasks) ---

async def send_scheduled_post(channel_id, text, reply_markup, delete_after_mins=None):
    try:
        msg = await bot.send_message(chat_id=channel_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")
        logging.info(f"ፖስት በቻናሉ ላይ ተለቋል: {channel_id}")
        
        # ⏱ የተጠቃሚው ሰዓት ላይ 6 ደቂቃ ጨምሮ ማጥፋት (Buffer Time)
        if delete_after_mins and delete_after_mins > 0:
            actual_delete_delay = delete_after_mins + 6
            run_time = datetime.now() + timedelta(minutes=actual_delete_delay)
            scheduler.add_job(delete_expired_post, 'date', run_date=run_time, args=[channel_id, msg.message_id])
            logging.info(f"ይህ ፖስት ከ {actual_delete_delay} ደቂቃ በኋላ እንዲጠፋ ተቀጥሯል (6 ደቂቃ ማቆያ ተጨምሯል)።")
    except Exception as e:
        logging.error(f"መላክ አልተቻለም: {e}")

async def delete_expired_post(channel_id, message_id):
    try:
        await bot.delete_message(chat_id=channel_id, message_id=message_id)
        logging.info(f"ማስታወቂያው በራሱ ጊዜ ጠፍቷል: {message_id}")
    except Exception as e:
        logging.error(f"ማጥፋት አልተቻለም: {e}")

# --- 🎛 የቁልፍ ሰሌዳዎች (Modular Keyboards with BACK Buttons) ---

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="💸 የሪፈራል ፖስት በ AI ፍጠር", callback_data="main_referral_ai"))
    builder.add(types.InlineKeyboardButton(text="📝 የራሴን መደበኛ ፖስት ስራ", callback_data="main_regular_post"))
    builder.add(types.InlineKeyboardButton(text="📢 የማስታወቂያ ፖስት ስራ", callback_data="main_ad_post"))
    builder.add(types.InlineKeyboardButton(text="📊 የቻናሎች ሁኔታ", callback_data="main_status"))
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
    
    welcome_text = (
        "👑 **እንኳን ወደ 7ቱ ቻናሎች ማስተዳደሪያ ማዕከል በሰላም መጡ!**\n\n"
        "ሁሉም ነገር ለየብቻ በቁልፎች ተከፋፍሏል። የሚፈልጉትን ክፍል ይምረጡ፦"
    )
    await message.reply(welcome_text, reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "go_to_main")
async def handle_go_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🎛 **ዋናው ማውጫ**\n\nየሚፈልጉትን ተግባር ከታች ይምረጡ፦", 
        reply_markup=get_main_menu(), 
        parse_mode="Markdown"
    )
    await callback.answer()

# --- 💸 ክፍል 1፦ የሪፈራል ፖስት ፈጣሪ (Groq AI) ---

@dp.callback_query(F.data == "main_referral_ai")
async def handle_referral_ai(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_referral_info)
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="↩️ ወደ ኋላ ተመለስ", callback_data="go_to_main"))
    
    info_text = (
        "💰 **የሪፈラル ፖስት ማዘጋጃ ክፍል (Groq AI)**\n\n"
        "እባክዎን ስለ ኦንላይን ስራው ዝርዝር መረጃ እዚህ ይጻፉልኝ።\n"
        "*(ለምሳሌ፦ የሳይቱ ስም፣ በሪፈራል ስንት እንደሚከፍል፣ ምን ተጠቃሚዎች ምን መስራት እንዳለባቸው እና ሊንክዎን አብረው ይላኩ)*"
    )
    await callback.message.edit_text(info_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.message(BotFlow.waiting_for_referral_info)
async def process_referral_ai(message: types.Message, state: FSMContext):
    waiting_msg = await message.reply("⏳ Groq AI የሪፈራል ፖስቱን በባለሙያ አጻጻፍ እያዘጋጀ ነው...")
    
    try:
        completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": REFERRAL_PROMPT},
                {"role": "user", "content": message.text}
            ],
            model="llama-3.3-70b-versatile",
        )
        ai_generated_text = completion.choices[0].message.content
        
        # መረጃዎችን ማስቀመጥ (ይህ መደበኛ ፖስት ተደርጎ ይቆጠራል)
        await state.update_data(final_text=ai_generated_text, post_type="regular", btn_text=None, btn_url=None)
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        
        await message.reply(
            f"✨ **በ AI የተዘጋጀ ማራኪ የሪፈራል ፖስት፦**\n\n{ai_generated_text}", 
            reply_markup=get_post_options_menu(), 
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.reply(f"❌ ስህተት ተፈጥሯል: {e}", reply_markup=get_main_menu())

# --- 📝 ክፍል 2፦ የራሴ መደበኛ ፖስት ማዘጋጃ ---

@dp.callback_query(F.data == "main_regular_post")
async def handle_regular_post(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_regular_text)
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="↩️ ወደ ኋላ ተመለስ", callback_data="go_to_main"))
    
    await callback.message.edit_text(
        "📝 **የራስዎን መደበኛ ፖስት ማዘጋጃ**\n\nእባክዎን በቻናሉ ላይ መለጠፍ የሚፈልጉትን ይዘት እዚህ ይጻፉ/ይላኩ፦",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(BotFlow.waiting_for_regular_text)
async def process_regular_text(message: types.Message, state: FSMContext):
    await state.update_data(final_text=message.text, post_type="regular", btn_text=None, btn_url=None)
    await message.reply(
        f"✅ **መደበኛ ፖስት ተዘጋጅቷል!**\n\nቀጣዩን ምርጫ ይምረጡ፦",
        reply_markup=get_post_options_menu(),
        parse_mode="Markdown"
    )

# --- 📢 ክፍል 3፦ የማስታወቂያ ፖስት ማዘጋጃ (ከፎቶው ላይ ካለው ምልክት ጋር) ---

@dp.callback_query(F.data == "main_ad_post")
async def handle_ad_post(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotFlow.waiting_for_ad_text)
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="↩️ ወደ ኋላ ተመለስ", callback_data="go_to_main"))
    
    await callback.message.edit_text(
        "📢 **የማስታወቂያ ፖስት ማዘጋጃ**\n\nእባክዎን የማስታወቂያውን ፅሁፍ እዚህ ይላኩ። ቦቱ በራሱ ከስር **'ማስታወቂያ ብቻ ❗️'** የሚለውን ፅሁፍ ይጨምርበታል።",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(BotFlow.waiting_for_ad_text)
async def process_ad_text(message: types.Message, state: FSMContext):
    # 📸 ከተሰጠው ፎቶ መሰረት "ማስታወቂያ ብቻ ❗️" የሚለውን ጽሁፍ አውቶማቲክ አድርጎ ከስር መቀጠል
    ad_footer = "\n\nማስታወቂያ ብቻ ❗️"
    full_ad_text = message.text + ad_footer
    
    await state.update_data(final_text=full_ad_text, post_type="ad", btn_text=None, btn_url=None)
    await message.reply(
        f"✅ **የማስታወቂያ ፖስት ከነማጠቃለያው ተዘጋጅቷል፦**\n\n{full_ad_text}",
        reply_markup=get_post_options_menu(),
        parse_mode="Markdown"
    )

# --- 🔗 Inline ሊንክ ቁልፍ ማያያዣ መስመር ---

@dp.callback_query(F.data == "flow_add_button")
async def handle_flow_add_button(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.reply("✏️ በሊንክ ቁልፉ ላይ የሚጻፈውን ስም ያስገቡ (ምሳሌ: `REGISTER HERE`):")
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
        return await message.reply("❌ እባክህ ትክክለኛ ሊንክ አስገባ!")
    
    await state.update_data(btn_url=message.text)
    await message.reply(
        "✅ የሊንክ ቁልፉ ተይዟል። አሁን መድረሻ ቻናል ለመምረጥ ቁልፉን ይጫኑ፦",
        reply_markup=get_post_options_menu(has_button=True),
        parse_mode="Markdown"
    )

# --- 📊 የቻናሎች መምረጫ እና የጊዜ ማስተካከያ ማውጫዎች ---

@dp.callback_query(F.data == "flow_choose_channel")
async def handle_flow_choose_channel(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for name, cid in CHANNELS.items():
        builder.add(types.InlineKeyboardButton(text=name, callback_data=f"selchan_{cid}"))
    builder.add(types.InlineKeyboardButton(text="↩️ ወደ ኋላ ተመለስ", callback_data="go_to_main"))
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
    builder.add(types.InlineKeyboardButton(text="⏱ ከ 2 ሰዓት በኋላ", callback_data="sched_120"))
    builder.add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="flow_choose_channel"))
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
    builder.add(types.InlineKeyboardButton(text="↩️ ተመለስ", callback_data="flow_choose_channel"))
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
    
    # 📝 የማረጋገጫ ማጠቃለያ መረጃ ማደራጀት
    post_type_label = "📢 ማስታወቂያ" if data.get("post_type") == "ad" else "📝 መደበኛ/የሪፈራል ፖስት"
    sched_label = "⚡️ አሁኑኑ" if data.get("schedule_after_mins") == 0 else f"⏱ ከ {data.get('schedule_after_mins')} ደቂቃ በኋላ"
    
    if delete_mins > 0:
        del_label = f"🗑 ከ {delete_mins} ደቂቃ + 6 ደቂቃ ቦነስ = ከ {delete_mins + 6} ደቂቃ በኋላ"
    else:
        del_label = "♾ ለዘላለም ይኖራል"
        
    confirm_text = (
        "⚠️ **የመጨረሻ ማረጋገጫ (Double-Check)**\n\n"
        f"🔹 **የፖስት አይነት፦** {post_type_label}\n"
        f"📢 **መድረሻ ቻናል፦** {data.get('target_channel')}\n"
        f"⏰ **የመልቀቂያ ሰዓት፦** {sched_label}\n"
        f"🗑 **የማጥፊያ ሰዓት፦** {del_label}\n\n"
        f"📄 **የፅሁፉ ቅድመ-ዕይታ፦**\n"
        f"---------------------------\n"
        f"{data.get('final_text')}\n"
        f"---------------------------"
    )
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="✅ ሁሉንም አረጋግጣለሁ - ፈጽም! 🚀", callback_data="execute_final_post"))
    builder.add(types.InlineKeyboardButton(text="❌ ስህተት አለ - ሰርዝና ተመለስ", callback_data="go_to_main"))
    builder.adjust(1)
    
    await callback.message.edit_text(confirm_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "execute_final_post")
async def execute_final_post(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    post_text = data.get("final_text")
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
        scheduler.add_job(send_scheduled_post, 'date', run_date=run_time, args=[target_chan, post_text, reply_markup, delete_mins])
        msg_out = "📅 ፖስቱ በተሳካ ሁኔታ ተቀጥሯል!"
    else:
        await send_scheduled_post(target_chan, post_text, reply_markup, delete_mins)
        msg_out = "🚀 ፖስቱ አሁኑኑ ቀጥታ ወደ ቻናልዎ ተለቋል!"
        
    await callback.message.edit_text(f"{msg_out}\n\nወደ ዋናው ማውጫ ተመልሰናል፦", reply_markup=get_main_menu(), parse_mode="Markdown")
    await state.clear()
    await callback.answer()

# --- 📊 የቻናሎች ሁኔታ ክፍል ---

@dp.callback_query(F.data == "main_status")
async def handle_main_status(callback: types.CallbackQuery):
    status_text = "📊 **የሰባቱ ቻናሎችህ ወቅታዊ ሁኔታ፦**\n\n"
    for name, cid in CHANNELS.items():
        status_text += f"🔹 {name} ➔ `ንቁ (Active)`\n"
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="↩️ ወደ ዋናው ማውጫ", callback_data="go_to_main"))
    await callback.message.edit_text(status_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

# --- 🚀 ማስነሻ ---

async def main():
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
