FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aventura_bot ./aventura_bot
COPY lore ./lore
COPY prompts ./prompts
COPY rules.md ./rules.md
COPY README.md ./README.md
COPY docs ./docs
COPY examples ./examples
COPY resolution_notes ./resolution_notes
COPY turn_seeds ./turn_seeds

CMD ["python", "-m", "aventura_bot.bot"]
