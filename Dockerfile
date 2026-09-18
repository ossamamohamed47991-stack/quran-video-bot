FROM python:3.12-slim

# تثبيت FFmpeg والأدوات الضرورية
RUN apt-get update && apt-get install -y ffmpeg libfontconfig1 && rm -rf /var/lib/apt/lists/*

# تعيين مجلد العمل
WORKDIR /app

# نسخ الملفات وتثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات الكود
COPY . .

# تشغيل البوت
CMD ["python", "main.py"]
