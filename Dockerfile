FROM python:3.10-slim

ENV TZ=UTC

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Make sure session folder exists
RUN mkdir -p /app/telethon_prod_session

# Copy session file
COPY telethon_prod_session/*.session /app/telethon_prod_session/

EXPOSE 3040

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3040"]
