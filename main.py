# -*- coding: utf-8 -*-
"""بوت تليجرام لتوليد فيديوهات قرآنية - النسخة المطورة"""
import asyncio
import hashlib
import json
import logging
import os
import random
import re
import tempfile
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from config import BOT_TOKEN, DEFAULT_RECITER, ALLOWED_USERS
from video_gen import fetch_ayah, make_video, RECITERS, VERSE_COUNTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RECITER_NAMES = {k: v[0] for k, v in RECITERS.items()}

# 2:255 أو 2:255-258
AYAH_RE = re.compile(r"^(\d{1,3})\s*[:/]\s*(\d{1,3})(?:\s*-\s*(\d{1,3}))?$")

# تخزين بيانات القناة المرتبطة (للاستمرار بعد إعادة التشغيل: DATA_DIR على volume)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DATA_FILE = os.path.join(DATA_DIR, "bot_data.json")
CAIRO = ZoneInfo("Africa/Cairo")


def load_data():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_data(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _allowed(user_id):
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return

    keyboard = [
        [InlineKeyboardButton("📱 افتح صانع الفيديوهات (Mini App)", web_app=WebAppInfo(url="https://example.com/webapp"))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🌙 أهلًا بك في بوت الفيديوهات القرآنية المطوّر!\n\n"
        "أرسل رقم السورة والآية مباشرة:\n"
        "`2:255` أو نطاق `2:255-258`\n\n"
        "أو استخدم الأوامر المتقدمة:\n"
        "• بقارئ وثيم: `/video 2:255 husary sunset`\n"
        "• مع ترجمة: `/video 2:255 alafasy en`\n"
        "• مع تفسير: `/video 2:255 alafasy tafsir`\n"
        "• للحفظ (تكرار 3x): `/video 2:255 alafasy repeat`\n"
        "• خلفية ذكاء اصطناعي: `/video 2:255 alafasy ai`\n\n"
        "اللغات: `en fr tr ru es de id bn ur fa hi ta ml sw uz`\n"
        "المفسرون: `tafsir` (الميسر) `jalalayn` (جلالين)\n\n"
        "القناة:\n"
        "• `/linkchannel` — ربط قناة لآية اليوم\n"
        "• `/channel` — حالة القناة المرتبطة\n"
        "• `/daily on|off` — تشغيل/إيقاف آية اليوم\n\n"
        "القراء المتاحون:\n"
        + "\n".join(f"`{k}` — {v}" for k, v in RECITER_NAMES.items()) +
        "\n\n🎬 الفيديو بدقة 9:16 جاهز للشورتس والريلز والاستوري",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


# ---------------------------------------------------------------- توليد الفيديو

async def handle_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE, surah: int, ayah_from: int,
                       ayah_to: int, reciter: str, lang: str, style: str = "gradient",
                       theme: str = "default", repeat: int = 1):
    label = f"سورة {surah} آية {ayah_from}" + (f"-{ayah_to}" if ayah_to != ayah_from else "")
    repeat_txt = f" — تكرار {repeat}x" if repeat > 1 else ""
    msg = await update.message.reply_text(
        f"🎬 جاري تجهيز الفيديو المطوّر...\n{label}{repeat_txt} — {RECITER_NAMES.get(reciter, reciter)}")
    try:
        # كاش: نفس الطلب => نفس الملف => رد فوري
        cache_dir = os.environ.get("CACHE_DIR", os.path.join(tempfile.gettempdir(), "quran_cache"))
        os.makedirs(cache_dir, exist_ok=True)
        key = hashlib.md5(
            f"{surah}:{ayah_from}-{ayah_to}:{reciter}:{lang}:{style}:{theme}:{repeat}:{os.environ.get('VIDEO_RES','720x1280')}".encode()
        ).hexdigest()
        out = os.path.join(cache_dir, f"{key}.mp4")
        if os.path.isfile(out):
            log.info(f"كاش: {label} موجود — رد فوري")
            with open(out, "rb") as f:
                await update.message.reply_video(
                    f,
                    caption=f"﴿ {label} ﴾ (من الكاش)\n🎙 {RECITER_NAMES.get(reciter, reciter)}",
                    supports_streaming=True,
                )
            await msg.delete()
            return

        infos = [fetch_ayah(surah, a, reciter=reciter, lang=lang)
                 for a in range(ayah_from, ayah_to + 1)]
        tmp = tempfile.mkdtemp(prefix="quran_bot_")
        # توليد في thread منفصل حتى لا يتجمد البوت أثناء التوليد
        await asyncio.to_thread(make_video, infos, out, workdir=tmp,
                                style=style, theme=theme, repeat=repeat)
        with open(out, "rb") as f:
            await update.message.reply_video(
                f,
                caption=f"﴿ {infos[0]['surah_name']} — الآيات {ayah_from}-{ayah_to} ﴾\n"
                        f"🎙 {RECITER_NAMES.get(reciter, reciter)}",
                supports_streaming=True,
            )
        await msg.delete()
    except ValueError as e:
        await msg.edit_text(f"❌ {e}")
    except Exception as e:
        log.exception("فشل توليد الفيديو")
        await msg.edit_text(f"❌ حصل خطأ: {e}\nتأكد إن رقم السورة والآية صحيحين.")


async def cmd_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("استخدم: `/video 2:255` أو `/video 2:255 husary sunset`",
                                        parse_mode="Markdown")
        return
    m = AYAH_RE.match(args[0])
    if not m:
        await update.message.reply_text("❌ الصيغة غلط. استخدم مثلًا: `2:255` أو `2:255-258`",
                                        parse_mode="Markdown")
        return
    surah, ayah_from = int(m.group(1)), int(m.group(2))
    ayah_to = int(m.group(3)) if m.group(3) else ayah_from

    reciter = args[1] if len(args) > 1 and args[1] in RECITERS else DEFAULT_RECITER
    lang = args[2] if len(args) > 2 and len(args[2]) <= 10 and args[2] not in ["sunset", "dark", "nature", "gradient"] else None

    style = "ai" if "ai" in args else ("nature" if "nature" in args else "gradient")
    theme = "sunset" if "sunset" in args else ("dark" if "dark" in args else "default")
    repeat = 3 if ("repeat" in args or "x3" in args) else 1

    await handle_video(update, ctx, surah, ayah_from, ayah_to, reciter, lang, style, theme, repeat)


async def plain_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return

    # Check if coming from Mini App web_app_data
    if update.message.web_app_data:
        try:
            data = json.loads(update.message.web_app_data.data)
            ayah_str = data.get("ayah", "2:255")
            reciter = data.get("reciter", DEFAULT_RECITER)
            theme = data.get("theme", "default")

            m = AYAH_RE.match(ayah_str)
            if m:
                surah, ayah_from = int(m.group(1)), int(m.group(2))
                ayah_to = int(m.group(3)) if m.group(3) else ayah_from
                await handle_video(update, ctx, surah, ayah_from, ayah_to, reciter, None, "gradient", theme)
                return
        except Exception as e:
            log.error(f"Web app data error: {e}")

    text = (update.message.text or "").strip()
    m = AYAH_RE.match(text)
    if m:
        ayah_to = int(m.group(3)) if m.group(3) else int(m.group(2))
        await handle_video(update, ctx, int(m.group(1)), int(m.group(2)), ayah_to,
                           DEFAULT_RECITER, None)
    else:
        await update.message.reply_text("أرسل رقم الآية بصيغة `2:255` أو استخدم `/start`",
                                        parse_mode="Markdown")


# ---------------------------------------------------------------- ربط القناة

async def cmd_linkchannel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "📢 لربط قناة لآية اليوم:\n\n"
        "1. افتح قناتك → الإعدادات → المشرفين\n"
        "2. أضف البوت كأدمن (صلاحية نشر الرسائل)\n"
        "3. ارجع هنا وأرسل `/confirm`\n\n"
        "ملاحظة: لو البوت مش أدمن، مش هيقدر ينشر في القناة.",
        parse_mode="Markdown")


async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    data = load_data()
    pending = data.get("pending_channel")
    if not pending:
        await update.message.reply_text(
            "مفيش قناة معلّقة.\nأضف البوت كأدمن في القناة الأول، ثم أرسل `/confirm`.",
            parse_mode="Markdown")
        return
    data["channel_id"] = pending["id"]
    data["channel_title"] = pending["title"]
    data.pop("pending_channel", None)
    save_data(data)
    log.info(f"تم ربط القناة: {pending['title']} ({pending['id']})")
    await update.message.reply_text(
        f"✅ تم ربط القناة: **{pending['title']}**\n"
        f"آية اليوم هتتنشر تلقائياً (افتراضياً 6 صباحاً).\n"
        f"للتحكم: `/daily on|off` — `/unlinkchannel`",
        parse_mode="Markdown")


async def cmd_unlinkchannel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    data = load_data()
    title = data.get("channel_title")
    data["channel_id"] = None
    data["channel_title"] = None
    save_data(data)
    await update.message.reply_text(
        f"تم فك ربط القناة{f' ({title})' if title else ''}. آية اليوم هتتوقف.")


async def cmd_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    data = load_data()
    if data.get("channel_id"):
        daily = "مفعلة" if data.get("daily_enabled", True) else "موقفة"
        await update.message.reply_text(
            f"📢 القناة المرتبطة: **{data.get('channel_title', 'قناة')}**\n"
            f"آية اليوم: {daily}\n"
            f"الوقت: {data.get('daily_time', '06:00')} (بتوقيت القاهرة)",
            parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "مفيش قناة مرتبطة.\nاستخدم `/linkchannel` للربط.",
            parse_mode="Markdown")


async def cmd_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    data = load_data()
    arg = (ctx.args[0] if ctx.args else "").lower()
    if arg == "on":
        data["daily_enabled"] = True
        save_data(data)
        await update.message.reply_text("✅ آية اليوم مفعلة.")
    elif arg == "off":
        data["daily_enabled"] = False
        save_data(data)
        await update.message.reply_text("⏸ آية اليوم موقفة.")
    else:
        state = "مفعلة" if data.get("daily_enabled", True) else "موقفة"
        await update.message.reply_text(f"آية اليوم حالياً: {state}\nاستخدم `/daily on` أو `/daily off`",
                                        parse_mode="Markdown")


async def my_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """عند إضافة البوت لقناة أو إزالته منها"""
    mcm = update.my_chat_member
    chat = mcm.chat
    if chat.type != "channel":
        return
    status = mcm.new_chat_member.status
    data = load_data()
    if status in ("administrator", "creator"):
        data["pending_channel"] = {"id": chat.id, "title": chat.title or "قناة"}
        save_data(data)
        log.info(f"البوت اتضاف لقناة: {chat.title} ({chat.id}) — في انتظار /confirm")
    elif status in ("left", "kicked"):
        if data.get("channel_id") == chat.id:
            data["channel_id"] = None
            data["channel_title"] = None
            save_data(data)
            log.info(f"البوت اتشال من القناة المرتبطة: {chat.title}")


# ---------------------------------------------------------------- آية اليوم

async def daily_ayah_job(ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    channel_id = data.get("channel_id")
    if not channel_id or not data.get("daily_enabled", True):
        return
    try:
        surah = random.randint(1, 114)
        ayah = random.randint(1, VERSE_COUNTS[surah])
        info = fetch_ayah(surah, ayah, reciter=DEFAULT_RECITER)
        tmp = tempfile.mkdtemp(prefix="quran_daily_")
        out = os.path.join(tmp, "daily.mp4")
        await asyncio.to_thread(make_video, info, out, workdir=tmp,
                                style="gradient", zoom=True)
        with open(out, "rb") as f:
            await ctx.bot.send_video(
                channel_id, f,
                caption=f"﴿ آية اليوم: {info['surah_name']} — {ayah} ﴾\n"
                        f"🎙 {RECITER_NAMES.get(DEFAULT_RECITER, DEFAULT_RECITER)}",
                supports_streaming=True)
        log.info(f"آية اليوم اتنشرت: {surah}:{ayah} -> {channel_id}")
    except Exception as e:
        log.exception("فشل نشر آية اليوم")


def main():
    # تشخيص البيئة: نسخة ffmpeg + الذاكرة المتاحة
    try:
        import subprocess
        fv = subprocess.run(["ffmpeg", "-version"], capture_output=True,
                            text=True, timeout=10).stdout.splitlines()[0]
        log.info(f"FFMPEG: {fv}")
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal") or line.startswith("MemAvailable"):
                        log.info(f"MEM: {line.strip()}")
    except Exception as e:
        log.warning(f"تشخيص البيئة فشل: {e}")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("video", cmd_video))
    app.add_handler(CommandHandler("linkchannel", cmd_linkchannel))
    app.add_handler(CommandHandler("confirm", cmd_confirm))
    app.add_handler(CommandHandler("unlinkchannel", cmd_unlinkchannel))
    app.add_handler(CommandHandler("channel", cmd_channel))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_message))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, plain_message))
    app.add_handler(MessageHandler(filters.StatusUpdate.MY_CHAT_MEMBER, my_chat_member))

    # جدولة آية اليوم (افتراضياً 06:00 بتوقيت القاهرة)
    daily_time = os.environ.get("DAILY_TIME", "06:00")
    try:
        h, m = (int(x) for x in daily_time.split(":"))
        app.job_queue.run_daily(daily_ayah_job, time=dtime(h, m, tzinfo=CAIRO))
        log.info(f"آية اليوم مجدولة: {daily_time} بتوقيت القاهرة")
    except Exception as e:
        log.warning(f"فشل جدولة آية اليوم: {e}")

    # Webhook mode على Railway (أسرع وأخف من polling)
    public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    webhook_url = os.environ.get("WEBHOOK_URL", "").strip() or (
        f"https://{public_domain}" if public_domain else "")
    if webhook_url:
        port = int(os.environ.get("PORT", "8080"))
        url_path = BOT_TOKEN.replace(":", "-")  # مسار سري لا يعرفه غير تليجرام
        secret = BOT_TOKEN.replace(":", "-")    # تليجرام يرفض ":" في الـ secret token
        full_url = f"{webhook_url}/{url_path}"

        log.info(f"Webhook mode: {full_url} على المنفذ {port}")
        # PTB بيعمل setWebhook لوحده في bootstrap بالـ webhook_url ده
        app.run_webhook(listen="0.0.0.0", port=port, url_path=url_path,
                        webhook_url=full_url, secret_token=secret,
                        drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    else:
        log.info("Polling mode (مفيش WEBHOOK_URL — تشغيل محلي)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()