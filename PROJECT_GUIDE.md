   # BankAssistant — документация для передачи коллеге

   Краткий технический гайд по проекту: что внутри, как запустить, как обновлять базу знаний и шаблоны.

   ## 1) Что это за сервис

   `BankAssistant` — backend + виджет для:
   - ответов по внутренней инструкции (с указанием пунктов-источников),
   - диалогового заполнения шаблонов,
   - генерации `.docx` документов.

   Проект ориентирован на локальный/контурный запуск (без внешних API по умолчанию).

   ## 2) Стек

   - **Python / FastAPI** — API
   - **Uvicorn** — ASGI-сервер
   - **docxtpl + python-docx** — генерация/обработка Word
   - **Локальный BM25-поиск** — поиск по базе знаний
   - **(опционально) Ollama** — локальная LLM
   - **(опционально) OpenAI-compatible API** — внешняя или внутренняя нейросеть
   - **Docker + Caddy** — контейнерный деплой и reverse proxy

   ## 3) Структура проекта

   - `app/main.py` — FastAPI-приложение и API-роуты
   - `app/dialog.py` — диалоговый движок (состояния сессии)
   - `app/knowledge.py` — поиск по базе знаний и формирование ответа
   - `app/render.py` — подстановка данных в `.docx` шаблоны
   - `app/ingest.py` — загрузка/обновление версии инструкции в `kb/chunks.json`
   - `templates/templates.json` — метаданные шаблонов и поля
   - `kb/chunks.json` — база знаний (пункты инструкции)
   - `static/widget.js` — встраиваемый виджет
   - `tests/test_dialog.py` — тесты ключевого сценария

   ## 4) Быстрый запуск локально (Windows PowerShell)

   ```powershell
   cd Z:\BankAssistant
   py -3.14 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   python -m uvicorn app.main:app --reload
   ```

   Проверки:
   - `http://127.0.0.1:8000/api/health`
   - `http://127.0.0.1:8000/docs`
   - `http://127.0.0.1:8000/` (демо-страница)

   Остановка: `Ctrl + C`.

   ## 5) Запуск через Docker

   ```powershell
   cd Z:\BankAssistant
   copy .env.example .env
   docker compose up -d --build
   ```

   Сервисы:
   - `api` — FastAPI
   - `caddy` — reverse proxy
   - `ollama` — опционально (профиль `llm`)

   Для LLM:
   ```powershell
   docker compose --profile llm up -d
   docker compose exec ollama ollama pull qwen2.5:7b-instruct
   ```
   После этого заполнить в `.env`:
   - `LLM_URL=http://ollama:11434`
   - `LLM_MODEL=qwen2.5:7b-instruct`

   ## 6) Переменные окружения (.env)

   См. `.env.example`.

   Ключевые:
   - `DOMAIN` — адрес/домен для Caddy
   - `ALLOWED_ORIGINS` — CORS
   - `AUTH_TOKENS` — роли доступа (`token:role,token:role`)
   - `ADMIN_TOKEN` — доступ к `POST /api/admin/kb/reload`
   - `LLM_URL`, `LLM_MODEL` — локальная LLM (опционально)
   - `AI_PROVIDER` — `extractive`, `ollama` или `openai`
   - `AI_API_KEY` — ключ OpenAI-compatible API (не коммитить в Git)
   - `AI_CONFIG_PATH` — путь к JSON-конфигурации ограничений

   Для подключения OpenAI-compatible API в `.env`:

   ```text
   AI_PROVIDER=openai
   LLM_URL=https://ai.starimg.ru/v1
   LLM_MODEL=<название-модели>
   AI_API_KEY=<секретный-ключ>
   ```

   Запрос отправляет вопрос пользователя и найденные пункты инструкции. Перед отправкой
   e-mail и номера телефонов маскируются. При ошибке API сервис автоматически возвращается
   к ответу из локальной базы знаний.

   Файл `config/ai.json` уже добавлен как точка расширения для ограничений:
   `max_input_chars`, `max_output_tokens`, `min_relevance`, `allowed_topics`,
   `blocked_topics`, `requests_per_minute`. Значения `null`/пустые списки означают,
   что ограничение пока не включено.

   Если `AUTH_TOKENS` пустой, включается демо-режим (роль `employee` по умолчанию).

   ## 7) Основные API-эндпоинты

   - `GET /api/health` — здоровье сервиса
   - `GET /api/templates` — шаблоны для текущей роли
   - `POST /api/sessions` — старт сессии (`template_id` опционально)
   - `POST /api/sessions/{id}/messages` — сообщение в диалог
   - `GET /api/sessions/{id}/document` — скачать готовый `.docx`
   - `GET /api/kb/documents` — версии документов в базе знаний
   - `POST /api/admin/kb/reload` — перечитать `kb/chunks.json`

   ## 8) Как обновлять базу знаний (Инструкцию)

   1. Подготовить файл `.docx`, `.txt` или `.md` с пунктами вида `3.4. Текст...`.
   2. Выполнить:

   ```powershell
   python -m app.ingest kb\Инструкция.docx --doc "Инструкция по документообороту" --version 2.0
   ```

   3. Применить без перезапуска API:

   ```powershell
   curl -X POST http://127.0.0.1:8000/api/admin/kb/reload -H "X-Admin-Token: <ADMIN_TOKEN>"
   ```

   Новая версия становится `active`, предыдущая автоматически архивируется.

   ## 9) Как добавлять/менять шаблоны документов

   1. Положить `.docx` в `templates/`.
   2. Использовать маркеры `{{ field_name }}` в документе.
   3. Описать шаблон в `templates/templates.json`:
      - `id`, `title`, `keywords`, `file`, `output_name`, `roles`,
      - `source`, `visa`,
      - `fields` (типы: `text`, `date`, `int`, `phone`, `email`, `choice`).
   4. Перезапустить сервис.

   ## 10) Тестирование

   Быстрая проверка:

   ```powershell
   python tests\test_dialog.py
   ```

   Покрываются:
   - поиск и честный отказ при отсутствии данных,
   - уточняющие вопросы,
   - сценарий заполнения шаблона,
   - роли доступа,
   - валидация полей,
   - версионность `ingest`.

   ## 11) Ограничения текущего прототипа

   - Сессии хранятся в памяти процесса (для масштабирования нужен Redis/внешнее хранилище).
   - Поиск лексический (BM25 + стемминг), не векторный.
   - Демо-данные в `kb/chunks.json` и `templates/` — заменить на реальные документы.

   ---

   Если нужен режим «только для передачи коллеге», достаточно отправить ему этот файл + `.env.example`.
