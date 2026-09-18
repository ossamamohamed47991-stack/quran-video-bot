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
import time
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (Application, CommandHandler, MessageHandler, ContextTypes,
                          filters, ChatMemberHandler, CallbackQueryHandler, InlineQueryHandler)

from config import BOT_TOKEN, DEFAULT_RECITER, ALLOWED_USERS, OWNER_USERNAME, OWNER_USER_IDS
from video_gen import fetch_ayah, make_video, RECITERS, VERSE_COUNTS, FONT_OPTIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RECITER_NAMES = {k: v[0] for k, v in RECITERS.items()}

# 2:255 أو 2:255-258
AYAH_RE = re.compile(r"^(\d{1,3})\s*[:/]\s*(\d{1,3})(?:\s*-\s*(\d{1,3}))?$")

# تخزين بيانات القناة المرتبطة (للاستمرار بعد إعادة التشغيل: DATA_DIR على volume)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DATA_FILE = os.path.join(DATA_DIR, "bot_data.json")
CAIRO = ZoneInfo("Africa/Cairo")
BOT_START = time.time()


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


def _is_owner(user):
    if not user:
        return False
    if user.id in OWNER_USER_IDS:
        return True
    return bool(user.username) and user.username.lower() == OWNER_USERNAME.lower()


def track_user(user_id, username=None):
    """تسجيل المستخدمين للإحصائيات والبث"""
    data = load_data()
    users = data.setdefault("users", {})
    key = str(user_id)
    now = time.strftime("%Y-%m-%d %H:%M")
    if key in users:
        users[key]["last_seen"] = now
        users[key]["requests"] = users[key].get("requests", 0) + 1
    else:
        users[key] = {"username": username, "first_seen": now,
                      "last_seen": now, "requests": 1}
    save_data(data)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    track_user(update.effective_user.id, update.effective_user.username)

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
        "• خلفية ذكاء اصطناعي: `/video 2:255 alafasy ai`\n"
        "• بخط مختلف: `/video 2:255 alafasy amiri` (أو `kufi` أو `ruqaa`)\n"
        "• بحث بالكلمة: `/search الصبر`\n"
        "• نص مخصص: `/text اللهم صل وسلم على نبينا محمد`\n"
        "• في أي شات: اكتب `@itQURAN_BOT 2:255` (Inline)\n\n"
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
                       theme: str = "default", repeat: int = 1, font: str = "default",
                       custom_text: str = None):
    if custom_text:
        label = "نص مخصص"
        short = custom_text[:40] + ("…" if len(custom_text) > 40 else "")
    else:
        label = f"سورة {surah} آية {ayah_from}" + (f"-{ayah_to}" if ayah_to != ayah_from else "")
        short = label
    repeat_txt = f" — تكرار {repeat}x" if repeat > 1 else ""
    msg = await update.message.reply_text(
        f"🎬 جاري تجهيز الفيديو المطوّر...\n{label}{repeat_txt} — {RECITER_NAMES.get(reciter, reciter)}")
    try:
        # كاش: نفس الطلب => نفس الملف => رد فوري
        cache_dir = os.environ.get("CACHE_DIR", os.path.join(tempfile.gettempdir(), "quran_cache"))
        os.makedirs(cache_dir, exist_ok=True)
        key = hashlib.md5(
            f"{surah}:{ayah_from}-{ayah_to}:{reciter}:{lang}:{style}:{theme}:{repeat}:{font}:{custom_text}:{os.environ.get('VIDEO_RES','720x1280')}".encode()
        ).hexdigest()
        out = os.path.join(cache_dir, f"{key}.mp4")
        if os.path.isfile(out):
            log.info(f"كاش: {label} موجود — رد فوري")
            with open(out, "rb") as f:
                sent = await update.message.reply_video(
                    f,
                    caption=f"﴿ {short} ﴾ (من الكاش)\n🎙 {RECITER_NAMES.get(reciter, reciter)}",
                    supports_streaming=True,
                )
            await msg.delete()
            _save_video_file_id(surah, ayah_from, ayah_to, sent)
            return

        if custom_text:
            infos = [{"text": custom_text, "surah_name": "", "ayah": "",
                      "reciter": reciter}]
        else:
            infos = [fetch_ayah(surah, a, reciter=reciter, lang=lang)
                     for a in range(ayah_from, ayah_to + 1)]
        tmp = tempfile.mkdtemp(prefix="quran_bot_")

        # شريط تقدم: تحديث رسالة بنسبة مئوية أثناء التوليد
        loop = asyncio.get_running_loop()
        last_pct = [0]
        progress_msg = await update.message.reply_text("⏳ جاري التوليد... 0%")

        async def edit_progress(pct):
            try:
                await progress_msg.edit_text(f"⏳ جاري التوليد... {pct}%")
            except Exception:
                pass

        def cb(pct):
            if pct - last_pct[0] >= 10 or pct == 100:
                last_pct[0] = pct
                asyncio.run_coroutine_threadsafe(edit_progress(pct), loop)

        # توليد في thread منفصل حتى لا يتجمد البوت أثناء التوليد
        await asyncio.to_thread(make_video, infos, out, workdir=tmp,
                                style=style, theme=theme, repeat=repeat,
                                custom_text=custom_text, font=font, progress_cb=cb)
        with open(out, "rb") as f:
            sent = await update.message.reply_video(
                f,
                caption=f"﴿ {short} ﴾\n🎙 {RECITER_NAMES.get(reciter, reciter)}",
                supports_streaming=True,
            )
        await progress_msg.delete()
        await msg.delete()
        _save_video_file_id(surah, ayah_from, ayah_to, sent)
    except ValueError as e:
        await msg.edit_text(f"❌ {e}")
    except Exception as e:
        log.exception("فشل توليد الفيديو")
        await msg.edit_text(f"❌ حصل خطأ: {e}\nتأكد إن رقم السورة والآية صحيحين.")


def _save_video_file_id(surah, ayah_from, ayah_to, sent):
    """حفظ file_id للفيديوهات المولدة — للاستخدام في الـ inline mode"""
    try:
        if not sent or not sent.video:
            return
        data = load_data()
        videos = data.setdefault("videos", {})
        fid = sent.video.file_id
        if ayah_to == ayah_from:
            videos[f"{surah}:{ayah_from}"] = {"file_id": fid, "title": f"سورة {surah} آية {ayah_from}"}
        videos[f"{surah}:{ayah_from}-{ayah_to}"] = {"file_id": fid, "title": f"سورة {surah} آيات {ayah_from}-{ayah_to}"}
        save_data(data)
    except Exception as e:
        log.warning(f"حفظ file_id فشل: {e}")


async def cmd_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    track_user(update.effective_user.id, update.effective_user.username)
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

    style = "ai" if "ai" in args else ("nature" if "nature" in args else "gradient")
    theme = "sunset" if "sunset" in args else ("dark" if "dark" in args else "default")
    repeat = 3 if ("repeat" in args or "x3" in args) else 1
    font = "default"
    for a in args:
        if a.startswith("font="):
            font = a.split("=", 1)[1].lower()
        elif a in FONT_OPTIONS and a != "default":
            font = a

    remaining = [a for a in args[1:] if a not in ("ai", "nature", "sunset", "dark",
                                                   "repeat", "x3") and not a.startswith("font=")
                 and a not in FONT_OPTIONS]
    reciter = remaining[0] if remaining and remaining[0] in RECITERS else DEFAULT_RECITER
    lang = remaining[1] if len(remaining) > 1 and len(remaining[1]) <= 10 and remaining[1] not in FONT_OPTIONS else None

    await handle_video(update, ctx, surah, ayah_from, ayah_to, reciter, lang, style, theme,
                       repeat, font)


async def plain_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    track_user(update.effective_user.id, update.effective_user.username)

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


# ---------------------------------------------------------------- بحث + نص مخصص + Inline

async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    track_user(update.effective_user.id, update.effective_user.username)
    keyword = " ".join(ctx.args).strip()
    if not keyword:
        await update.message.reply_text("استخدم: `/search كلمة`\nمثال: `/search الصبر`",
                                        parse_mode="Markdown")
        return
    try:
        import requests as _rq
        from urllib.parse import quote
        r = _rq.get(f"https://api.alquran.cloud/v1/search/{quote(keyword)}/all/quran-uthmani",
                    timeout=30)
        data = r.json().get("data", {})
        matches = data.get("matches", [])
        if not matches:
            await update.message.reply_text(f"🔍 مفيش نتائج لـ «{keyword}».")
            return
        keyboard = []
        for m in matches[:3]:
            s, a = m["surah"]["number"], m["numberInSurah"]
            keyboard.append([InlineKeyboardButton(
                f"﴿ {m['surah']['englishName']} {a} ﴾", callback_data=f"srch_{s}:{a}")])
        await update.message.reply_text(
            f"🔍 نتائج البحث عن «{keyword}» ({len(matches)} نتيجة):\n\n"
            f"«{matches[0]['text'][:120]}…»\n\nاختر آية لتوليد فيديو:",
            reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        log.exception("فشل البحث")
        await update.message.reply_text(f"❌ حصل خطأ في البحث: {e}")


async def search_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        s, a = (int(x) for x in q.data.split("_")[1].split(":"))
        await q.edit_message_text(f"🎬 جاري توليد فيديو سورة {s} آية {a}...")
        await handle_video(update, ctx, s, a, a, DEFAULT_RECITER, None)
    except Exception as e:
        log.exception("فشل توليد من البحث")
        await q.edit_message_text(f"❌ حصل خطأ: {e}")


async def cmd_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    track_user(update.effective_user.id, update.effective_user.username)
    text = " ".join(ctx.args).strip()
    if not text:
        await update.message.reply_text(
            "استخدم: `/text نصك`\nمثال: `/text اللهم صل وسلم على نبينا محمد`",
            parse_mode="Markdown")
        return
    if len(text) > 500:
        await update.message.reply_text("❌ النص طويل جداً (الحد الأقصى 500 حرف).")
        return
    await handle_video(update, ctx, 0, 0, 0, DEFAULT_RECITER, None, custom_text=text)


async def inline_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """@bot 2:255 في أي شات — يرجع فيديوهات من الكاش أو اقتراح توليد"""
    from telegram import InlineQueryResultCachedVideo, InlineQueryResultArticle, InputTextMessageContent
    q = (update.inline_query.query or "").strip()
    data = load_data()
    videos = data.get("videos", {})
    results = []

    if q:
        m = AYAH_RE.match(q)
        if m:
            key = f"{int(m.group(1))}:{int(m.group(2))}"
            hit = videos.get(key)
            if hit:
                results.append(InlineQueryResultCachedVideo(
                    id=f"v{key}", video_file_id=hit["file_id"],
                    title=f"﴿ {hit['title']} ﴾", description="فيديو جاهز من الكاش",
                    caption=f"﴿ {hit['title']} ﴾"))
            else:
                results.append(InlineQueryResultArticle(
                    id=f"g{key}", title=f"🎬 توليد {key}",
                    description="اضغط لفتح البوت وتوليد الفيديو",
                    input_message_content=InputTextMessageContent(
                        f"ابعت للبوت: /video {key}")))
    else:
        # آخر الفيديوهات المولدة
        for key, v in list(videos.items())[-8:]:
            results.append(InlineQueryResultCachedVideo(
                id=f"r{key}", video_file_id=v["file_id"],
                title=f"﴿ {v['title']} ﴾", description="فيديو جاهز",
                caption=f"﴿ {v['title']} ﴾"))

    if not results:
        results.append(InlineQueryResultArticle(
            id="h", title="🌙 بوت الفيديوهات القرآنية",
            description="اكتب 2:255 مثلاً، أو افتح البوت",
            input_message_content=InputTextMessageContent(
                "🌙 بوت الفيديوهات القرآنية — جرب: /video 2:255")))

    await update.inline_query.answer(results, cache_time=0, is_personal=True)


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


# ---------------------------------------------------------------- لوحة التحكم

def _cache_stats():
    cache_dir = os.environ.get("CACHE_DIR", os.path.join(tempfile.gettempdir(), "quran_cache"))
    try:
        files = [f for f in os.listdir(cache_dir) if f.endswith(".mp4")]
        size = sum(os.path.getsize(os.path.join(cache_dir, f)) for f in files)
        return len(files), round(size / 1024 / 1024, 1)
    except Exception:
        return 0, 0.0


def _uptime():
    secs = int(time.time() - BOT_START)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}س {m}د {s}ث"


def _rss():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS"):
                    return f"{round(int(line.split()[1]) / 1024, 1)} MB"
    except Exception:
        pass
    return "—"


def _admin_panel_text():
    data = load_data()
    users = data.get("users", {})
    n_cache, cache_mb = _cache_stats()
    channel = data.get("channel_title") or "مفيش"
    daily = "مفعلة" if data.get("daily_enabled", True) else "موقفة"
    total_req = sum(u.get("requests", 0) for u in users.values())
    return (
        "🔧 لوحة التحكم\n\n"
        f"👥 المستخدمون: {len(users)}\n"
        f"🎬 طلبات الفيديو: {total_req}\n"
        f"💾 الكاش: {n_cache} ملف ({cache_mb} MB)\n"
        f"📢 القناة: {channel}\n"
        f"⏰ آية اليوم: {daily} (06:00)\n"
        f"🕐 شغال منذ: {_uptime()}\n"
        f"🧠 ذاكرة البوت: {_rss()}"
    )


def _admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 إحصائيات", callback_data="adm_stats"),
         InlineKeyboardButton("🧹 مسح الكاش", callback_data="adm_cache")],
        [InlineKeyboardButton("📢 القناة", callback_data="adm_channel"),
         InlineKeyboardButton("⏰ آية اليوم", callback_data="adm_daily")],
        [InlineKeyboardButton("📨 بث للجميع", callback_data="adm_broadcast"),
         InlineKeyboardButton("🔄 تحديث", callback_data="adm_refresh")],
    ])


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update.effective_user):
        await update.message.reply_text("❌ دي لوحة مخصوصة لصاحب البوت.")
        return
    await update.message.reply_text(_admin_panel_text(), reply_markup=_admin_keyboard())


async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not _is_owner(q.from_user):
        await q.edit_message_text("❌ دي لوحة مخصوصة لصاحب البوت.")
        return
    data = load_data()
    action = q.data

    if action == "adm_stats":
        users = data.get("users", {})
        lines = ["📊 إحصائيات المستخدمين:\n"]
        for uid, u in sorted(users.items(), key=lambda x: -x[1].get("requests", 0))[:10]:
            name = u.get("username") or uid
            lines.append(f"• @{name} — {u.get('requests', 0)} طلب")
        await q.edit_message_text("\n".join(lines) or "مفيش مستخدمين لسه.",
                                  reply_markup=_admin_keyboard())

    elif action == "adm_cache":
        cache_dir = os.environ.get("CACHE_DIR", os.path.join(tempfile.gettempdir(), "quran_cache"))
        n = 0
        try:
            for f in os.listdir(cache_dir):
                if f.endswith(".mp4"):
                    os.remove(os.path.join(cache_dir, f))
                    n += 1
        except Exception as e:
            log.warning(f"مسح الكاش فشل: {e}")
        await q.edit_message_text(f"🧹 اتمسح {n} ملف كاش.",
                                  reply_markup=_admin_keyboard())

    elif action == "adm_channel":
        if data.get("channel_id"):
            await q.edit_message_text(
                f"📢 القناة المرتبطة: **{data.get('channel_title')}**\n"
                f"ID: `{data.get('channel_id')}`\n"
                f"لفك الربط: `/unlinkchannel`",
                parse_mode="Markdown", reply_markup=_admin_keyboard())
        else:
            await q.edit_message_text(
                "📢 مفيش قناة مرتبطة.\n"
                "1. أضف البوت كأدمن في قناتك\n"
                "2. أرسل `/confirm`",
                parse_mode="Markdown", reply_markup=_admin_keyboard())

    elif action == "adm_daily":
        data["daily_enabled"] = not data.get("daily_enabled", True)
        save_data(data)
        state = "مفعلة ✅" if data["daily_enabled"] else "موقفة ⏸"
        await q.edit_message_text(f"⏰ آية اليوم: {state}",
                                  reply_markup=_admin_keyboard())

    elif action == "adm_broadcast":
        await q.edit_message_text(
            "📨 للبث للجميع:\nأرسل `/broadcast رسالتك`\n\n"
            "مثال: `/broadcast السلام عليكم 🌙`",
            parse_mode="Markdown", reply_markup=_admin_keyboard())

    elif action == "adm_refresh":
        await q.edit_message_text(_admin_panel_text(), reply_markup=_admin_keyboard())


async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update.effective_user):
        await update.message.reply_text("❌ دي ميزة مخصوصة لصاحب البوت.")
        return
    text = " ".join(ctx.args).strip()
    if not text:
        await update.message.reply_text("استخدم: `/broadcast رسالتك`", parse_mode="Markdown")
        return
    data = load_data()
    users = data.get("users", {})
    sent, failed = 0, 0
    for uid in users:
        try:
            await ctx.bot.send_message(int(uid), text)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"📨 تم البث: {sent} وصلت، {failed} فشلت (من أصل {len(users)}).")


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
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("text", cmd_text))
    app.add_handler(CommandHandler("linkchannel", cmd_linkchannel))
    app.add_handler(CommandHandler("confirm", cmd_confirm))
    app.add_handler(CommandHandler("unlinkchannel", cmd_unlinkchannel))
    app.add_handler(CommandHandler("channel", cmd_channel))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("panel", cmd_admin))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(search_callback, pattern="^srch_"))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_message))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, plain_message))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

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