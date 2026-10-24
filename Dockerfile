FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 OUTPUT_DIR=/tmp/docgen
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m app && chown -R app /srv
USER app
EXPOSE 8000
# Один воркер: сессии хранятся в памяти процесса
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
