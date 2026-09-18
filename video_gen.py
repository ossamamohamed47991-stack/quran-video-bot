# -*- coding: utf-8 -*-
"""توليد فيديوهات قرآنية: تلاوة + نص عثماني + خلفية -> MP4
مبني على أفضل ممارسات من المشاريع الجاهزة:
- Quran-Reels-Generator: قص الصمت بعتبة ديناميكية (mean-16dB)، fade صوتي 0.2s،
  خلفيات فيديو طبيعية، 11 قارئ عبر everyayah.com
- QuranVidGen: عرض النص العربي عبر ASS subtitles + libass (HarfBuzz)
  => تشكيل عربي سليم وتموضع علامات الرسم العثماني فوق الحروف صح
"""
import os
import re
import random
import subprocess
import tempfile
import logging
import requests
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

log = logging.getLogger(__name__)

API_BASE = "https://api.alquran.cloud/v1"
EVERYAYAH_BASE = "https://everyayah.com/data"

# اختصارات اللغات → إصدارات alquran.cloud
LANG_MAP = {
    "en": "en.sahih", "fr": "fr.hamidullah", "tr": "tr.diyanet",
    "ru": "ru.kuliev", "es": "es.cortes", "de": "de.aburida",
    "id": "id.indonesian", "bn": "bn.bengali", "ur": "ur.jalandhry",
    "fa": "fa.ansarian", "hi": "hi.farooq", "ta": "ta.tamil",
    "ml": "ml.abdulhameed", "sw": "sw.barwani", "uz": "uz.mahmut",
    "tafsir": "ar.muyassar", "jalalayn": "ar.jalalayn",
}

# رمز السطر الجديد في ASS (خارج الـ f-string عشان يتوافق مع Python < 3.12)
_N = "\\N"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE_DIR, "assets", "fonts")
BG_DIR = os.path.join(BASE_DIR, "assets", "bg")

# أسماء عائلات الخطوط في ASS (لازم تطابق أسماء العائلات داخل ملفات الخطوط)
ASS_FONT_AYAH = "Arabic Typesetting"   # تغطية كاملة لعلامات الرسم العثماني
ASS_FONT_HEADER = "Dubai Medium"
ASS_FONT_RECITER = "Dubai"
ASS_FONT_TRANS = "Arial"

# للقياس في PIL (نفس مقاس em)
FONT_ARABIC = os.path.join(FONT_DIR, "arabtype.ttf")
FONT_LATIN = os.path.join(FONT_DIR, "arial.ttf")

# القراء: id -> (اسم عربي, مجلد everyayah)
RECITERS = {
    "alafasy": ("مشاري العفاسي", "Alafasy_64kbps"),
    "abdulbasit": ("عبد الباسط عبد الصمد (مرتل)", "Abdul_Basit_Murattal_64kbps"),
    "abdulbasit_mj": ("عبد الباسط عبد الصمد (مجود)", "AbdulSamad_64kbps_QuranExplorer.Com"),
    "husary": ("محمود خليل الحصري", "Husary_64kbps"),
    "minshawi": ("محمد صديق المنشاوي (مجود)", "Minshawy_Mujawwad_64kbps"),
    "sudais": ("عبد الرحمن السديس", "Abdurrahmaan_As-Sudais_64kbps"),
    "shuraym": ("سعود الشريم", "Saood_ash-Shuraym_64kbps"),
    "gamdi": ("سعد الغامدي", "Saad_Al-Ghamdi_64kbps"),
    "maher": ("ماهر المعيقلي", "Maher_AlMuaiqly_64kbps"),
    "hudhaify": ("عبد الله الحذيفي", "Hudhaify_64kbps"),
    "shatri": ("أبو بكر الشاطري", "Abu_Bakr_Ash-Shaatree_128kbps"),
    "banna": ("محمود علي البنا", "mahmoud_ali_al_banna_32kbps"),
}

# عدد آيات كل سورة (للتحقق)
VERSE_COUNTS = {
    1: 7, 2: 286, 3: 200, 4: 176, 5: 120, 6: 165, 7: 206, 8: 75, 9: 129, 10: 109,
    11: 123, 12: 111, 13: 43, 14: 52, 15: 99, 16: 128, 17: 111, 18: 110, 19: 98, 20: 135,
    21: 112, 22: 78, 23: 118, 24: 64, 25: 77, 26: 227, 27: 93, 28: 88, 29: 69, 30: 60,
    31: 34, 32: 30, 33: 73, 34: 54, 35: 45, 36: 83, 37: 182, 38: 88, 39: 75, 40: 85,
    41: 54, 42: 53, 43: 89, 44: 59, 45: 37, 46: 35, 47: 38, 48: 29, 49: 18, 50: 45,
    51: 60, 52: 49, 53: 62, 54: 55, 55: 78, 56: 96, 57: 29, 58: 22, 59: 24, 60: 13,
    61: 14, 62: 11, 63: 11, 64: 18, 65: 12, 66: 12, 67: 30, 68: 52, 69: 52, 70: 44,
    71: 28, 72: 28, 73: 20, 74: 56, 75: 40, 76: 31, 77: 50, 78: 40, 79: 46, 80: 42,
    81: 29, 82: 19, 83: 36, 84: 25, 85: 22, 86: 17, 87: 19, 88: 26, 89: 30, 90: 20,
    91: 15, 92: 21, 93: 11, 94: 8, 95: 8, 96: 19, 97: 5, 98: 8, 99: 8, 100: 11,
    101: 11, 102: 8, 103: 3, 104: 9, 105: 5, 106: 4, 107: 7, 108: 3, 109: 6, 110: 3,
    111: 5, 112: 4, 113: 5, 114: 6,
}

# دقة الفيديو: 720x1280 افتراضياً (تناسب ذاكرة الاستضافة المجانية).
# للدقة الكاملة 1080x1920: حط متغير البيئة VIDEO_RES=1080x1920
_res = os.environ.get("VIDEO_RES", "720x1280")
W, H = (int(x) for x in _res.lower().split("x"))  # 9:16

# مساحة تخطيط الترجمة (ASS) ثابتة — libass بيقيسها تلقائياً لدقة الفيديو
ASS_W, ASS_H = 1080, 1920


def _ffmpeg_major():
    """نسخة ffmpeg الرئيسية — ffmpeg 7+ شال خيار eval من فلتر crop"""
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True,
                             text=True, timeout=10).stdout
        m = re.search(r"ffmpeg version (\d+)", out)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


FFMPEG_MAJOR = _ffmpeg_major()


def _ar(text):
    return get_display(arabic_reshaper.reshape(text))


def _arabic_digits(n):
    return str(n).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def validate_ayah(surah, ayah):
    if surah < 1 or surah > 114:
        raise ValueError("رقم السورة لازم يكون بين 1 و 114")
    if ayah < 1 or ayah > VERSE_COUNTS[surah]:
        raise ValueError(f"سورة {surah} فيها {VERSE_COUNTS[surah]} آية بس")


def fetch_ayah(surah, ayah, reciter="alafasy", lang=None):
    validate_ayah(surah, ayah)
    r = requests.get(f"{API_BASE}/ayah/{surah}:{ayah}/quran-uthmani", timeout=30)
    r.raise_for_status()
    data = r.json()["data"]
    result = {
        "text": data["text"],
        "surah": surah,
        "surah_name": data["surah"]["name"],
        "surah_en": data["surah"]["englishName"],
        "ayah": data["numberInSurah"],
        "reciter": reciter,
        "translation": None,
    }
    reciter_name, folder = RECITERS.get(reciter, RECITERS["alafasy"])
    result["audio_url"] = f"{EVERYAYAH_BASE}/{folder}/{surah:03d}{ayah:03d}.mp3"
    if lang:
        edition = LANG_MAP.get(lang, lang)  # اختصار -> إصدار كامل، أو إصدار مكتوب صراحة
        r3 = requests.get(f"{API_BASE}/ayah/{surah}:{ayah}/{edition}", timeout=30)
        if r3.status_code == 200:
            result["translation"] = r3.json()["data"]["text"]
    return result


# ---------------------------------------------------------------- PIL: الخلفية

def _gradient_bg(top=(12, 45, 62), bottom=(6, 22, 36), theme="default"):
    """دعم ثيمات خلفيات متعددة"""
    if theme == "sunset":
        top, bottom = (60, 20, 40), (20, 10, 25)
    elif theme == "dark":
        top, bottom = (10, 10, 10), (2, 2, 2)
    elif theme == "nature_gradient":
        top, bottom = (20, 60, 40), (5, 20, 15)
    
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=color)
    return img


def _decorate(img):
    from PIL import ImageFilter
    d = ImageDraw.Draw(img, "RGBA")
    m = 60
    d.rectangle([m, m, W - m, H - m], outline=(255, 215, 130, 90), width=3)
    d.rectangle([m + 12, m + 12, W - m - 12, H - m - 12], outline=(255, 215, 130, 40), width=1)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-300, -400, W + 300, 500], fill=(255, 220, 140, 26))
    gd.ellipse([-300, H - 500, W + 300, H + 400], fill=(255, 220, 140, 18))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    return Image.alpha_composite(img.convert("RGBA"), glow)


def make_bg(out_png, theme="default"):
    """خلفية التدرج + الزخارف حسب الثيم"""
    img = _gradient_bg(theme=theme)
    img = _decorate(img)
    img.convert("RGB").save(out_png)


def _ai_bg(out_png, prompt, theme="default"):
    """خلفية مولّدة بالذكاء الاصطناعي من معنى الآية (Pollinations — مجاني، من غير API key)"""
    url = ("https://image.pollinations.ai/prompt/"
           f"{requests.utils.quote(prompt[:300])}"
           f"?width={W}&height={H}&nologo=true&seed={random.randint(0, 99999)}")
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    with open(out_png, "wb") as f:
        f.write(r.content)


# ---------------------------------------------------------------- ASS: النصوص

def _ass_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_escape(text):
    return (text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").strip())


def _wrap_text(d, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for w in words:
        trial = (current + " " + w).strip()
        if d.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


def _font_size_for(word_count):
    if word_count > 60:
        return 44
    elif word_count > 40:
        return 52
    elif word_count > 25:
        return 62
    elif word_count > 15:
        return 72
    else:
        return 82


def _fit_block(d, text, font_path, start_size, max_w, max_h, min_size, line_ratio):
    """يلف النص ويصغّر الخط لحد ما يلائم max_h (آخر حل: قطع مع علامة حذف)"""
    fs = start_size
    while fs >= min_size:
        font = ImageFont.truetype(font_path, fs)
        lines = _wrap_text(d, text, font, max_w)
        h = len(lines) * int(fs * line_ratio)
        if h <= max_h:
            return lines, fs, h
        fs -= 4
    font = ImageFont.truetype(font_path, min_size)
    lines = _wrap_text(d, text, font, max_w)
    line_h = int(min_size * line_ratio)
    while len(lines) * line_h > max_h and len(lines) > 1:
        lines.pop()
        lines[-1] = lines[-1].rstrip() + " …"
    return lines, min_size, len(lines) * line_h


def build_ass(ayah_info, duration, out_ass):
    """يبني ملف ASS لعرض نص الآية + الترجمة بتشكيل سليم (libass/HarfBuzz)"""
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    max_w = ASS_W - 160
    top, bottom = 340, ASS_H - 260

    # نص الآية
    words = len(ayah_info["text"].split())
    ar_lines, ar_fs, ar_h = _fit_block(d, ayah_info["text"], FONT_ARABIC,
                                       _font_size_for(words), max_w, bottom - top,
                                       min_size=30, line_ratio=1.5)

    # الترجمة (لو عربية => خط عربي)
    tr_lines, tr_fs, tr_h = [], 0, 0
    tr_arabic = False
    if ayah_info.get("translation"):
        tr_arabic = bool(re.search(r"[\u0600-\u06FF]", ayah_info["translation"]))
        tr_max = int((bottom - top) * 0.45)
        tr_font = FONT_ARABIC if tr_arabic else FONT_LATIN
        tr_lines, tr_fs, tr_h = _fit_block(d, ayah_info["translation"], tr_font,
                                           36, max_w, tr_max, min_size=22,
                                           line_ratio=1.5 if tr_arabic else 1.4)

    total_h = ar_h + (60 + tr_h if tr_lines else 0)
    y_start = top + max(0.0, (bottom - top - total_h) / 2)
    y_ar_center = y_start + ar_h / 2
    y_tr_center = y_start + ar_h + 60 + tr_h / 2 if tr_lines else 0

    reciter_name = RECITERS.get(ayah_info["reciter"], ("", ""))[0]
    header = f"سورة {ayah_info['surah_name']} — الآية {_arabic_digits(ayah_info['ayah'])}"
    reciter = f"﴿ {reciter_name} ﴾"
    num = f"﴿{_arabic_digits(ayah_info['ayah'])}﴾"

    start = _ass_time(0)
    end = _ass_time(duration)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {ASS_W}",
        f"PlayResY: {ASS_H}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Header,{ASS_FONT_HEADER},54,&H0082D7FF,&H0082D7FF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,2,1,8,60,60,140,1",
        f"Style: Reciter,{ASS_FONT_RECITER},40,&H00DCD2C8,&H00DCD2C8,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,2,1,8,60,60,230,1",
        f"Style: Ayah,{ASS_FONT_AYAH},{ar_fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,3,1,5,60,60,0,1",
        f"Style: Trans,{ASS_FONT_AYAH if tr_arabic else ASS_FONT_TRANS},{tr_fs or 30},&H00EBEBEB,&H00EBEBEB,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,2,1,5,60,60,0,1",
        f"Style: Num,{ASS_FONT_AYAH},50,&H0082D7FF,&H0082D7FF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,2,1,5,60,60,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{start},{end},Header,,0,0,0,,{{\\an8\\pos(540,140)}}{_ass_escape(header)}",
        f"Dialogue: 0,{start},{end},Reciter,,0,0,0,,{{\\an8\\pos(540,235)}}{_ass_escape(reciter)}",
        f"Dialogue: 0,{start},{end},Ayah,,0,0,0,,{{\\an5\\pos(540,{y_ar_center:.0f})}}{_ass_escape(chr(10).join(ar_lines)).replace(chr(10), _N)}",
    ]
    if tr_lines:
        lines.append(
            f"Dialogue: 0,{start},{end},Trans,,0,0,0,,{{\\an5\\pos(540,{y_tr_center:.0f})}}{_ass_escape(chr(10).join(tr_lines)).replace(chr(10), _N)}")
    lines.append(
        f"Dialogue: 0,{start},{end},Num,,0,0,0,,{{\\an5\\pos(540,{ASS_H - 250})}}{_ass_escape(num)}")

    with open(out_ass, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))
    return out_ass


# ---------------------------------------------------------------- الصوت

def _trim_silence(mp3_in, mp3_out):
    """قص الصمت بعتبة ديناميكية (mean_volume - 16dB) زي مشروع Quran-Reels-Generator"""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", mp3_in, "-af", "volumedetect",
                          "-f", "null", "-"], capture_output=True, text=True, timeout=60)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", out.stderr)
    mean = float(m.group(1)) if m else -25.0
    thr = mean - 16
    cmd = ["ffmpeg", "-y", "-i", mp3_in,
           "-af", (f"silenceremove=start_periods=1:start_threshold={thr:.1f}dB:start_silence=0.25,"
                   "areverse,"
                   f"silenceremove=start_periods=1:start_threshold={thr:.1f}dB:start_silence=0.25,"
                   "areverse"),
           "-c:a", "libmp3lame", "-q:a", "2", mp3_out]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)


def _audio_duration(mp3_path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", mp3_path], capture_output=True, text=True, timeout=30)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 30.0


def _repeat_audio(audio_in, audio_out, times=3, gap=1.5):
    """تكرار الصوت times مرات مع فجوة gap ثواني بين كل مرة (وضع الحفظ)"""
    branches = "".join(f"[a{i}]" for i in range(times))
    pads = "".join(f"[a{i}]apad=pad_dur={gap}[a{i}p];" for i in range(times))
    concat_in = "".join(f"[a{i}p]" for i in range(times))
    cmd = ["ffmpeg", "-y", "-i", audio_in, "-filter_complex",
           f"[0:a]asplit={times}{branches};{pads}{concat_in}concat=n={times}:v=0:a=1[a]",
           "-map", "[a]", "-c:a", "libmp3lame", "-q:a", "2", audio_out]
    subprocess.run(cmd, check=True, capture_output=True, timeout=180)


# ---------------------------------------------------------------- التشفير

def _encode_segment(bg_png, audio_mp3, ass_file, out_mp4, style="gradient", zoom=True,
                    cwd=None):
    """تشفير مقطع واحد. cwd = مجلد العمل (فيه fonts/ والـ ass) => مسارات نسبية
    من غير نقطتين ولا مسافات => مفيش مشاكل escape في الفلتر"""
    dur = _audio_duration(audio_mp3)
    fade_out = max(0.0, dur - 0.7)
    af = (f"afade=t=in:st=0:d=0.2,afade=t=out:st={max(0.0, dur - 0.2):.2f}:d=0.2")
    ass_rel = os.path.basename(ass_file)

    if style == "nature":
        bg_video = os.path.join(BG_DIR, "nature_part31.mp4")
        vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},eq=brightness=-0.12:saturation=1.05,"
              f"ass={ass_rel}:fontsdir=fonts,"
              f"fade=t=in:st=0:d=0.6,fade=t=out:st={fade_out:.2f}:d=0.7[v]")
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-t", f"{dur:.3f}", "-i", bg_video,
               "-i", audio_mp3, "-filter_complex", vf,
               "-map", "[v]", "-map", "1:a",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-c:a", "aac", "-b:a", "192k", "-af", af,
               "-pix_fmt", "yuv420p", "-shortest", "-movflags", "+faststart", out_mp4]
    else:
        if zoom:
            # Ken Burns خفيف على الذاكرة: scale + crop بتقييم لكل فريم (بدل zoompan
            # اللي بيكدس فريمات في الذاكرة => SIGKILL على استضافة 512MB)
            z = f"1+0.15*min(t/{dur:.3f},1)"
            eval_opt = "" if FFMPEG_MAJOR >= 7 else ":eval=frame"
            dark = "eq=brightness=-0.12:saturation=1.05," if style == "ai" else ""
            vf = (f"scale=trunc(iw*1.2/2)*2:trunc(ih*1.2/2)*2,"
                  f"crop=w='iw/({z})':h='ih/({z})':x='(iw-ow)/2':y='(ih-oh)/2'{eval_opt},"
                  f"scale={W}:{H},{dark}"
                  f"ass={ass_rel}:fontsdir=fonts,"
                  f"fade=t=in:st=0:d=0.6,fade=t=out:st={fade_out:.2f}:d=0.7")
        else:
            dark = "eq=brightness=-0.12:saturation=1.05," if style == "ai" else ""
            vf = (f"{dark}ass={ass_rel}:fontsdir=fonts,"
                  f"fade=t=in:st=0:d=0.6,fade=t=out:st={fade_out:.2f}:d=0.7")
        cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{dur:.3f}", "-i", bg_png,
               "-i", audio_mp3,
               "-vf", vf, "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-c:a", "aac", "-b:a", "192k", "-af", af,
               "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", out_mp4]
    subprocess.run(cmd, check=True, capture_output=True, timeout=900, cwd=cwd)


def _concat_segments(segments, out_mp4):
    list_file = os.path.join(os.path.dirname(segments[0]), "concat.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for s in segments:
            f.write(f"file '{s.replace(os.sep, '/')}'\n")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
           "-c", "copy", "-movflags", "+faststart", out_mp4]
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)


def _rss_mb():
    """ذاكرة العملية الحالية (Linux) — للتشخيص"""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return None


def make_video(ayah_infos, out_mp4, workdir=None, style="gradient", zoom=True, theme="default",
               repeat=1):
    """توليد فيديو لآية واحدة أو نطاق آيات. style: gradient | nature, theme: default | sunset | dark | nature_gradient
    repeat: عدد مرات تكرار التلاوة (وضع الحفظ)"""
    if isinstance(ayah_infos, dict):
        ayah_infos = [ayah_infos]
    tmp = workdir or tempfile.mkdtemp(prefix="quran_")
    fonts_tmp = os.path.join(tmp, "fonts")
    os.makedirs(fonts_tmp, exist_ok=True)
    for fn in ("arabtype.ttf", "arial.ttf", "DUBAI-BOLD.TTF", "DUBAI-MEDIUM.TTF",
               "DUBAI-REGULAR.TTF", "DUBAI-LIGHT.TTF"):
        src = os.path.join(FONT_DIR, fn)
        if os.path.isfile(src):
            dst = os.path.join(fonts_tmp, fn)
            if not os.path.isfile(dst):
                import shutil
                shutil.copy2(src, dst)
    segments = []
    for i, info in enumerate(ayah_infos):
        bg_png = os.path.join(tmp, f"bg_{i}.png")
        audio_raw = os.path.join(tmp, f"audio_{i}.mp3")
        audio_trim = os.path.join(tmp, f"audio_{i}_trim.mp3")
        ass_file = os.path.join(tmp, f"subs_{i}.ass")
        seg_mp4 = os.path.join(tmp, f"seg_{i}.mp4")

        if style == "nature":
            bg_png = None
        elif style == "ai":
            # خلفية AI من معنى الآية (الترجمة الإنجليزية كـ prompt)
            prompt = info.get("translation") or ""
            if not prompt:
                try:
                    r = requests.get(
                        f"{API_BASE}/ayah/{info['surah']}:{info['ayah']}/en.sahih",
                        timeout=30)
                    prompt = r.json()["data"]["text"]
                except Exception:
                    prompt = ""
            if not prompt:
                prompt = f"beautiful islamic art, quran, {info['surah_name']}"
            try:
                _ai_bg(bg_png, prompt)
            except Exception as e:
                log.warning(f"خلفية AI فشلت: {e} — بديل: تدرج")
                make_bg(bg_png, theme=theme)
        else:
            make_bg(bg_png, theme=theme)

        r = requests.get(info["audio_url"], timeout=120)
        r.raise_for_status()
        with open(audio_raw, "wb") as f:
            f.write(r.content)

        _trim_silence(audio_raw, audio_trim)
        if repeat > 1:
            audio_repeat = os.path.join(tmp, f"audio_{i}_repeat.mp3")
            _repeat_audio(audio_trim, audio_repeat, times=repeat)
            audio_trim = audio_repeat
        dur = _audio_duration(audio_trim)
        build_ass(info, dur, ass_file)
        log.info(f"RSS قبل التشفير: {_rss_mb()} MB (مدة الصوت {dur:.1f}s)")
        try:
            _encode_segment(bg_png, audio_trim, ass_file, seg_mp4, style=style, zoom=zoom,
                            cwd=tmp)
        except subprocess.CalledProcessError:
            if zoom:
                # شبكة أمان: لو التشفير وقع (ذاكرة/مشكلة ffmpeg) => من غير zoom
                log.warning("التشفير بالـ zoom فشل — إعادة المحاولة من غير zoom")
                _encode_segment(bg_png, audio_trim, ass_file, seg_mp4, style=style,
                                zoom=False, cwd=tmp)
            else:
                raise
        segments.append(seg_mp4)

    if len(segments) == 1:
        os.replace(segments[0], out_mp4)
    else:
        _concat_segments(segments, out_mp4)
    return out_mp4