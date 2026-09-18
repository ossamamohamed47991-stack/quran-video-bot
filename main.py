# -*- coding: utf-8 -*-
"""بوت تليجرام لتوليد فيديوهات قرآنية - النسخة المطورة"""
import logging
import os
import re
import tempfile
import json

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from config import BOT_TOKEN, DEFAULT_RECITER, ALLOWED_USERS
from video_gen import fetch_ayah, make_video, RECITERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RECITER_NAMES = {k: v[0] for k, v in RECITERS.items()}

# 2:255 أو 2:255-258
AYAH_RE = re.compile(r"^(\d{1,3})\s*[:/]\s*(\d{1,3})(?:\s*-\s*(\d{1,3}))?$")


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
        "• مع ترجمة: `/video 2:255 alafasy en`\n\n"
        "القراء المتاحون:\n"
        + "\n".join(f"`{k}` — {v}" for k, v in RECITER_NAMES.items()) +
        "\n\n🎬 الفيديو بدقة 9:16 جاهز للشورتس والريلز والاستوري",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


async def handle_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE, surah: int, ayah_from: int,
                       ayah_to: int, reciter: str, lang: str, style: str = "gradient", theme: str = "default"):
    label = f"سورة {surah} آية {ayah_from}" + (f"-{ayah_to}" if ayah_to != ayah_from else "")
    msg = await update.message.reply_text(
        f"🎬 جاري تجهيز الفيديو المطوّر...\n{label} — {RECITER_NAMES.get(reciter, reciter)}")
    try:
        infos = [fetch_ayah(surah, a, reciter=reciter, lang=lang)
                 for a in range(ayah_from, ayah_to + 1)]
        tmp = tempfile.mkdtemp(prefix="quran_bot_")
        out = os.path.join(tmp, f"video_{surah}_{ayah_from}-{ayah_to}.mp4")
        make_video(infos, out, workdir=tmp, style=style, theme=theme)
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
    
    style = "nature" if "nature" in args else "gradient"
    theme = "sunset" if "sunset" in args else ("dark" if "dark" in args else "default")
    
    await handle_video(update, ctx, surah, ayah_from, ayah_to, reciter, lang, style, theme)


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

    # Webhook mode على Railway (أسرع وأخف من polling)
    public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    webhook_url = os.environ.get("WEBHOOK_URL", "").strip() or (
        f"https://{public_domain}" if public_domain else "")
    if webhook_url:
        port = int(os.environ.get("PORT", "8080"))
        url_path = BOT_TOKEN.replace(":", "-")  # مسار سري لا يعرفه غير تليجرام
        secret = BOT_TOKEN.replace(":", "-")    # تليجرام يرفض ":" في الـ secret token

        async def post_init(application):
            await application.bot.set_webhook(
                url=f"{webhook_url}/{url_path}",
                secret_token=secret,
                drop_pending_updates=True,
            )
            log.info(f"Webhook set: {webhook_url}/{url_path}")

        app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("video", cmd_video))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_message))
        app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, plain_message))
        log.info(f"Webhook mode على المنفذ {port}")
        app.run_webhook(listen="0.0.0.0", port=port, url_path=url_path,
                        secret_token=secret, allowed_updates=Update.ALL_TYPES)
    else:
        log.info("Polling mode (مفيش WEBHOOK_URL — تشغيل محلي)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()