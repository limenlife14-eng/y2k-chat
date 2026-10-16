import threading
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# 🔑 تنظیمات تلگرام (اطلاعات خودت را اینجا جایگزین کن)
BOT_TOKEN = "8737024613:AAFcOBTcHaq8BVbJqnaFWPBIZhTwJeYFvug"
ADMIN_ID = "1707952451"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# 🗄️ دیتابیس حافظه
messages = []
# ساختار کاربر: {username: {"avatar": "", "premium_until": 0, "ban_until": 0, "last_seen": 0, "support_msgs": []}}
users = {}
support_tickets = {}
ticket_counter = 1

def get_user(username):
    if username not in users:
        users[username] = {
            "avatar": "",
            "premium_until": 0,
            "ban_until": 0,
            "last_seen": time.time(),
            "support_msgs": []
        }
    return users[username]

def is_user_premium(username):
    u = get_user(username)
    return u["premium_until"] > time.time()

def get_ban_status(username):
    u = get_user(username)
    now = time.time()
    if u["ban_until"] == -1:
        return True, "حساب شما به صورت دائمی مسدود شده است! 🚫"
    elif u["ban_until"] > now:
        rem_hours = int((u["ban_until"] - now) // 3600)
        rem_mins = int(((u["ban_until"] - now) % 3600) // 60)
        return True, f"حساب شما به دلیل تخلف تا {rem_hours} ساعت و {rem_mins} دقیقه دیگر مسدود است. ⏳"
    return False, ""

# --- مسیرهای وب‌سایت (Flask API) ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/sync', methods=['POST'])
def sync_data():
    """همگام‌سازی پیام‌ها، وضعیت آنلاین، پروفایل و پشتیبانی"""
    data = request.json
    username = data.get('username', '').strip()
    now = time.time()

    user_info = None
    if username:
        u = get_user(username)
        u["last_seen"] = now
        prem_rem_days = max(0, int((u["premium_until"] - now) // 86400)) if u["premium_until"] > now else 0
        banned, ban_msg = get_ban_status(username)
        user_info = {
            "username": username,
            "avatar": u["avatar"],
            "is_premium": u["premium_until"] > now,
            "premium_days": prem_rem_days,
            "banned": banned,
            "ban_msg": ban_msg,
            "support_msgs": u["support_msgs"]
        }

    # محاسبه افراد آنلاین (فعال در ۱۵ ثانیه اخیر)
    online_users = [uname for uname, udata in users.items() if now - udata["last_seen"] < 15]

    return jsonify({
        "messages": messages,
        "online_count": len(online_users),
        "online_users": online_users,
        "user_info": user_info
    })

@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    """تغییر نام کاربری و عکس پروفایل"""
    data = request.json
    old_name = data.get('old_username', '').strip()
    new_name = data.get('new_username', '').strip()
    avatar = data.get('avatar', '').strip()

    if not new_name:
        return jsonify({"status": "error", "message": "نام کاربری نمی‌تواند خالی باشد"}), 400

    if old_name and old_name in users and old_name != new_name:
        if new_name in users:
            return jsonify({"status": "error", "message": "این نام کاربری قبلاً انتخاب شده است!"}), 400
        users[new_name] = users.pop(old_name)
        for m in messages:
            if m["username"] == old_name:
                m["username"] = new_name
    
    u = get_user(new_name)
    u["avatar"] = avatar
    for m in messages:
        if m["username"] == new_name:
            m["avatar"] = avatar

    return jsonify({"status": "success", "username": new_name, "avatar": avatar})

@app.route('/api/send', methods=['POST'])
def send_message():
    """ارسال پیام در چت عمومی با ساعت دقیق"""
    data = request.json
    username = data.get('username', '').strip()
    text = data.get('text', '').strip()

    if not username or not text:
        return jsonify({"status": "error"}), 400

    banned, ban_msg = get_ban_status(username)
    if banned:
        return jsonify({"status": "error", "message": ban_msg}), 403

    u = get_user(username)
    msg_id = len(messages) + 1
    new_msg = {
        "id": msg_id,
        "username": username,
        "avatar": u["avatar"],
        "text": text,
        "time": datetime.now().strftime("%H:%M"),
        "is_premium": is_user_premium(username),
        "is_broadcast": False
    }
    messages.append(new_msg)
    return jsonify({"status": "success"})

@app.route('/api/report', methods=['POST'])
def report_message():
    """ارسال گزارش تخلف با دکمه‌های جریمه ۵ ساعته، ۱ روزه و دائمی"""
    data = request.json
    msg_id = data.get('msg_id')
    target = next((m for m in messages if m["id"] == msg_id), None)
    if not target:
        return jsonify({"status": "error"}), 404

    t_user = target['username']
    markup = InlineKeyboardMarkup(row_width=2)
    btn_del = InlineKeyboardButton("🗑️ حذف پیام", callback_data=f"del_{msg_id}")
    btn_ban5h = InlineKeyboardButton("⏳ مسدود ۵ ساعته", callback_data=f"ban5h_{t_user}")
    btn_ban1d = InlineKeyboardButton("📅 مسدود ۱ روزه", callback_data=f"ban1d_{t_user}")
    btn_banperm = InlineKeyboardButton("🚫 مسدود دائمی", callback_data=f"banperm_{t_user}")
    markup.add(btn_del, btn_ban5h, btn_ban1d, btn_banperm)

    report_text = f"🚨 **گزارش تخلف جدید**\n\n👤 کاربر: `{t_user}`\n💬 پیام: {target['text']}\n🕒 ساعت: {target['time']}"
    bot.send_message(ADMIN_ID, report_text, reply_markup=markup, parse_mode="Markdown")
    return jsonify({"status": "success"})

@app.route('/api/request_premium', methods=['POST'])
def request_premium():
    data = request.json
    username = data.get('username')
    plan = int(data.get('plan', 1))

    markup = InlineKeyboardMarkup()
    btn_approve = InlineKeyboardButton(f"✅ فعال‌سازی پریمیوم ({plan} ماهه)", callback_data=f"prem_{plan}_{username}")
    markup.add(btn_approve)

    text = f"⭐ **درخواست اشتراک پریمیوم**\n\n👤 کاربر: `{username}`\n📦 پلن: {plan} ماهه"
    bot.send_message(ADMIN_ID, text, reply_markup=markup, parse_mode="Markdown")
    return jsonify({"status": "success"})

@app.route('/api/support/send', methods=['POST'])
def send_support():
    global ticket_counter
    data = request.json
    username = data.get('username')
    text = data.get('text')

    u = get_user(username)
    now_str = datetime.now().strftime("%H:%M")
    u["support_msgs"].append({"sender": "user", "text": text, "time": now_str})

    ticket_id = ticket_counter
    support_tickets[ticket_id] = username
    ticket_counter += 1

    msg = f"🎧 **تیکت پشتیبانی (#{ticket_id})**\n👤 کاربر: `{username}`\n💬 پیام: {text}\n\n✍️ برای پاسخ بنویسید:\n`/reply {ticket_id} متن پاسخ`"
    bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
    return jsonify({"status": "success"})

# --- پنل مدیریت حرفه‌ای در ربات تلگرام ---

def get_admin_panel_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌟 لیست کاربران پریمیوم", callback_data="panel_prems"),
        InlineKeyboardButton("🟢 آمار و افراد آنلاین", callback_data="panel_stats"),
        InlineKeyboardButton("🔍 راهنمای جستجوی کاربر", callback_data="panel_search_help"),
        InlineKeyboardButton("📢 راهنمای پیام همگانی", callback_data="panel_bc_help")
    )
    return markup

@bot.message_handler(commands=['start', 'panel'])
def show_panel(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    text = "🎛 **پنل مدیریت پیشرفته Y2K**\n\nاز دکمه‌های زیر برای مدیریت کاربران، اشتراک‌ها و پیام‌ها استفاده کنید:"
    bot.send_message(ADMIN_ID, text, reply_markup=get_admin_panel_markup(), parse_mode="Markdown")

@bot.message_handler(commands=['search'])
def search_user_cmd(message):
    """جستجوی کاربر با دستور /search نام"""
    if str(message.chat.id) != str(ADMIN_ID):
        return
    parts = message.text.split(' ', 1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ لطفاً نام کاربر را بنویسید. مثال:\n`/search Ali`", parse_mode="Markdown")
        return
    query = parts[1].strip().lower()
    found = [uname for uname in users.keys() if query in uname.lower()]
    if not found:
        bot.reply_to(message, "❌ هیچ کاربری با این مشخصات پیدا نشد.")
        return
    
    for uname in found:
        u = users[uname]
        is_p = is_user_premium(uname)
        rem_d = max(0, int((u["premium_until"] - time.time()) // 86400)) if is_p else 0
        status_str = f"🌟 پریمیوم ({rem_d} روز مانده)" if is_p else "👤 عادی"
        
        markup = InlineKeyboardMarkup(row_width=2)
        if is_p:
            markup.add(InlineKeyboardButton("❌ لغو پریمیوم", callback_data=f"revokeprem_{uname}"))
        else:
            markup.add(InlineKeyboardButton("⭐ اهدای ۱ ماه پریمیوم", callback_data=f"prem_1_{uname}"))
        markup.add(
            InlineKeyboardButton("⏳ بن ۵ ساعته", callback_data=f"ban5h_{uname}"),
            InlineKeyboardButton("📅 بن ۱ روزه", callback_data=f"ban1d_{uname}"),
            InlineKeyboardButton("🚫 بن دائمی", callback_data=f"banperm_{uname}"),
            InlineKeyboardButton("🔓 رفع مسدودیت", callback_data=f"unban_{uname}")
        )
        bot.send_message(ADMIN_ID, f"🔎 **نتیجه جستجو:**\n👤 نام: `{uname}`\n📊 وضعیت: {status_str}", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(message):
    """ارسال پیام همگانی مدیر در چت"""
    if str(message.chat.id) != str(ADMIN_ID):
        return
    parts = message.text.split(' ', 1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ متن پیام همگانی را بنویسید. مثال:\n`/broadcast به چت‌روم Y2K خوش آمدید!`", parse_mode="Markdown")
        return
    bc_text = parts[1].strip()
    messages.append({
        "id": len(messages) + 1,
        "username": "📢 پیام مدیریت Y2K",
        "avatar": "👑",
        "text": bc_text,
        "time": datetime.now().strftime("%H:%M"),
        "is_premium": True,
        "is_broadcast": True
    })
    bot.reply_to(message, "✅ پیام همگانی با موفقیت در چت‌روم منتشر شد.")

@bot.message_handler(commands=['reply'])
def reply_support(message):
    """پاسخ مستقیم به صندوق پشتیبانی کاربر"""
    if str(message.chat.id) != str(ADMIN_ID):
        return
    try:
        parts = message.text.split(' ', 2)
        ticket_id = int(parts[1])
        reply_content = parts[2]
        target_username = support_tickets.get(ticket_id)
        if target_username:
            u = get_user(target_username)
            u["support_msgs"].append({
                "sender": "admin",
                "text": reply_content,
                "time": datetime.now().strftime("%H:%M")
            })
            bot.reply_to(message, f"✅ پاسخ شما به صندوق پشتیبانی `{target_username}` ارسال شد.", parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ تیکت پیدا نشد.")
    except Exception:
        bot.reply_to(message, "⚠️ فرمت اشتباه! مثال:\n`/reply 1 سلام، مشکل بررسی شد`", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    global messages
    data = call.data
    now = time.time()

    if data == "panel_prems":
        prems = [u for u in users.keys() if is_user_premium(u)]
        if not prems:
            bot.answer_callback_query(call.id, "هیچ کاربر پریمیومی وجود ندارد!")
            return
        for uname in prems:
            rem_d = max(0, int((users[uname]["premium_until"] - now) // 86400))
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("❌ لغو اشتراک پریمیوم", callback_data=f"revokeprem_{uname}"))
            bot.send_message(ADMIN_ID, f"🌟 کاربر: `{uname}`\n⏳ زمان باقی‌مانده: {rem_d} روز", reply_markup=markup, parse_mode="Markdown")
        bot.answer_callback_query(call.id)

    elif data == "panel_stats":
        online_u = [u for u, d in users.items() if now - d["last_seen"] < 15]
        text = f"📊 **وضعیت لحظه‌ای سرور:**\n\n👥 کل کاربران: {len(users)}\n🟢 آنلاین‌ها ({len(online_u)} نفر): {', '.join(online_u) if online_u else 'هیچکس'}\n💬 کل پیام‌ها: {len(messages)}"
        bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
        bot.answer_callback_query(call.id)

    elif data == "panel_search_help":
        bot.send_message(ADMIN_ID, "🔍 برای جستجوی کاربر (پریمیوم یا عادی) و مدیریت حسابش، دستور زیر را بفرستید:\n`/search نام_کاربر`", parse_mode="Markdown")
        bot.answer_callback_query(call.id)

    elif data == "panel_bc_help":
        bot.send_message(ADMIN_ID, "📢 برای ارسال پیام همگانی با کادر ویژه در چت‌روم، دستور زیر را بفرستید:\n`/broadcast متن پیام شما`", parse_mode="Markdown")
        bot.answer_callback_query(call.id)

    elif data.startswith("del_"):
        msg_id = int(data.split("_")[1])
        messages = [m for m in messages if m["id"] != msg_id]
        bot.answer_callback_query(call.id, "پیام حذف شد.")
        bot.edit_message_text(f"✅ پیام شماره {msg_id} از چت‌روم حذف شد.", call.message.chat.id, call.message.message_id)

    elif data.startswith("ban5h_"):
        uname = data.split("_", 1)[1]
        get_user(uname)["ban_until"] = now + (5 * 3600)
        bot.answer_callback_query(call.id, "کاربر ۵ ساعت مسدود شد.")
        bot.send_message(ADMIN_ID, f"⏳ کاربر `{uname}` به مدت **۵ ساعت** مسدود شد.", parse_mode="Markdown")

    elif data.startswith("ban1d_"):
        uname = data.split("_", 1)[1]
        get_user(uname)["ban_until"] = now + (24 * 3600)
        bot.answer_callback_query(call.id, "کاربر ۱ روز مسدود شد.")
        bot.send_message(ADMIN_ID, f"📅 کاربر `{uname}` به مدت **۱ روز (۲۴ ساعت)** مسدود شد.", parse_mode="Markdown")

    elif data.startswith("banperm_"):
        uname = data.split("_", 1)[1]
        get_user(uname)["ban_until"] = -1
        bot.answer_callback_query(call.id, "کاربر دائماً مسدود شد.")
        bot.send_message(ADMIN_ID, f"🚫 کاربر `{uname}` به صورت **دائمی** مسدود شد.", parse_mode="Markdown")

    elif data.startswith("unban_"):
        uname = data.split("_", 1)[1]
        get_user(uname)["ban_until"] = 0
        bot.answer_callback_query(call.id, "مسدودیت رفع شد.")
        bot.send_message(ADMIN_ID, f"🔓 مسدودیت کاربر `{uname}` برداشته شد.", parse_mode="Markdown")

    elif data.startswith("prem_"):
        parts = data.split("_", 2)
        months = int(parts[1])
        uname = parts[2]
        u = get_user(uname)
        base_time = max(now, u["premium_until"])
        u["premium_until"] = base_time + (months * 30 * 86400)
        for m in messages:
            if m["username"] == uname:
                m["is_premium"] = True
        bot.answer_callback_query(call.id, "پریمیوم فعال شد!")
        bot.send_message(ADMIN_ID, f"🌟 اشتراک پریمیوم **{months} ماهه** برای `{uname}` فعال شد.", parse_mode="Markdown")

    elif data.startswith("revokeprem_"):
        uname = data.split("_", 1)[1]
        get_user(uname)["premium_until"] = 0
        for m in messages:
            if m["username"] == uname:
                m["is_premium"] = False
        bot.answer_callback_query(call.id, "اشتراک لغو شد.")
        bot.send_message(ADMIN_ID, f"❌ اشتراک پریمیوم کاربر `{uname}` به دلیل تخلف لغو گردید.", parse_mode="Markdown")

def run_telebot():
    bot.infinity_polling()

if __name__ == '__main__':
    t = threading.Thread(target=run_telebot, daemon=True)
    t.start()
    print("🚀 سرور پیشرفته Y2K روشن شد!")
    app.run(host='0.0.0.0', port=5000, debug=False)