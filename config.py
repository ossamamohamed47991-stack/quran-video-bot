# -*- coding: utf-8 -*-
"""إعدادات البوت — يقرأ التوكن من متغير البيئة أو من هنا"""
import os

# توكن البوت من @BotFather (القراءة من Environment Variable أولاً)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# القارئ الافتراضي
DEFAULT_RECITER = "alafasy"

# لو فاضي => أي حد يستخدم البوت. لو حاطط IDs => محدود عليهم بس
ALLOWED_USERS = []

# صاحب البوت (الـ admin) — باليوزرنيم أو بالـ ID
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "ZI_83")
OWNER_USER_IDS = [int(x) for x in os.environ.get("OWNER_USER_IDS", "").split(",") if x.strip()]
