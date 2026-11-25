FROM python:3.12-slim

WORKDIR /app
# ffmpeg — ролики событий из архива регистратора (tg_bot/nvr_clip.py)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --default-timeout=100 --no-cache-dir -r requirements.txt

COPY bot.py nvr_clip.py ./

CMD ["python", "bot.py"]
