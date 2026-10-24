# Карта API и ограничений

Обозначения:

- `[API]` — HTTP API или настройки запуска API.
- `[AI]` — подключение нейросети.
- `[LIMITS]` — ограничения, фильтры или правила доступа.

## [API] Сервер и контейнеры

- `[API]` [app/main.py](./app/main.py) — FastAPI-приложение, маршруты, CORS, авторизация и выдача документов.
- `[API]` [app/__init__.py](./app/__init__.py) — Python-пакет приложения.
- `[API]` [requirements.txt](./requirements.txt) — FastAPI, Uvicorn и библиотеки документов.
- `[API]` [Dockerfile](./Dockerfile) — контейнер API.
- `[API]` [docker-compose.yml](./docker-compose.yml) — сервис API и Caddy.
- `[API]` [Caddyfile](./Caddyfile) — reverse proxy перед API.
- `[API]` [static/widget.js](./static/widget.js) — клиентский виджет, который вызывает API.
- `[API]` [static/demo.html](./static/demo.html) — тестовая страница с подключённым виджетом.

## [AI] Подключение нейросети

- `[AI]` [app/knowledge.py](./app/knowledge.py) — локальный BM25 и `LocalRAGAnswerer`, без внешней нейросети.
- `[AI]` [config/ai.json](./config/ai.json) — включение провайдера и JSON-настройки лимитов.
- `[AI]` [.env.example](./.env.example) — безопасный шаблон `local_rag` без API-ключей.

Локальный `.env` не добавлять в Git; внешние API-ключи проекту не нужны.

## [LIMITS] Ограничения и доступ

- `[LIMITS]` [config/ai.json](./config/ai.json) — заготовки для `max_input_chars`, `max_output_tokens`, `min_relevance`, тем и rate limit.
- `[LIMITS]` [app/main.py](./app/main.py) — `AUTH_TOKENS`, `ADMIN_TOKEN`, CORS и ограничения длины сообщений.
- `[LIMITS]` [app/dialog.py](./app/dialog.py) — состояния сессии, TTL, максимум сессий, проверка полей и ролей.
- `[LIMITS]` [app/knowledge.py](./app/knowledge.py) — `MIN_RELEVANCE`, ролевой доступ к пунктам и маскирование персональных данных.
- `[LIMITS]` [kb/chunks.json](./kb/chunks.json) — поле `access` у пунктов базы знаний.
- `[LIMITS]` [templates/templates.json](./templates/templates.json) — поле `roles`, типы, обязательность и максимальная длина полей.

## Быстрая навигация

Если нужно изменить:

- API-маршрут — [app/main.py](./app/main.py);
- формат запроса к нейросети — [app/knowledge.py](./app/knowledge.py);
- локальную модель — `LLM_URL` и `LLM_MODEL` в `.env` по образцу [.env.example](./.env.example);
- JSON-лимиты — [config/ai.json](./config/ai.json);
- лимит релевантности — переменная `MIN_RELEVANCE`;
- доступ роли к шаблону — [templates/templates.json](./templates/templates.json);
- доступ роли к пункту инструкции — [kb/chunks.json](./kb/chunks.json).
