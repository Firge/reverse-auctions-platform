# Setup Hints (Backend + Frontend)

Практическая памятка по разворачиванию проекта на разных машинах.

## Что уже есть в `docker-compose.yaml`

`docker-compose.yaml` уже достаточен для нормального старта инфраструктуры и backend-сервисов:

- `postgres`
- `redis`
- `web` (Django)
- `celery_worker`
- `celery_beat`
- `parser/loader/pipeline` (профили для каталога)

Поэтому обязательных правок в `docker-compose.yaml` для базового запуска не требуется.

## Порты по умолчанию

- Backend (Django): `http://127.0.0.1:8000`
- Frontend (Vite dev): `http://127.0.0.1:5173`
- Postgres: `5432`
- Redis: `6379`

## Вариант A (рекомендуется): Docker только для Postgres/Redis, backend и frontend локально

Это самый удобный путь для разработки.

### 1. Предварительные требования

Нужно установить на машину:

- Python 3.12+ (или совместимую версию для `backend/requirements.txt`)
- Node.js + npm
- Docker Desktop (или другой Docker runtime)

Проверка:

```powershell
python --version
npm --version
docker --version
docker compose version
```

### 2. Поднять инфраструктуру (Postgres + Redis)

Из корня проекта:

```powershell
docker compose up -d postgres redis
```

Проверка статуса:

```powershell
docker compose ps
```

### 3. Подготовить backend до `runserver`

Из корня проекта:

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Если `backend/.env` уже настроен под ваш локальный запуск, можно идти дальше. Если нет, убедитесь, что он соответствует доступной БД.

Быстрая проверка подключения и конфигурации Django:

```powershell
venv\Scripts\python.exe backend\manage.py check
```

Применить миграции:

```powershell
venv\Scripts\python.exe backend\manage.py migrate
```

Запустить backend (`runserver`):

```powershell
venv\Scripts\python.exe backend\manage.py runserver
```

После этого backend должен отвечать на:

- `http://127.0.0.1:8000/api/auctions/`

### 4. Подготовить frontend до `npm run dev`

Откройте новый терминал и перейдите в папку frontend:

```powershell
cd frontend
```

Установить зависимости:

```powershell
npm install
```

Запустить frontend:

```powershell
npm run dev
```

Открыть в браузере:

- `http://127.0.0.1:5173`

### 5. Как frontend ходит в backend

В dev-режиме frontend использует Vite proxy (`frontend/vite.config.js`) и отправляет запросы на `/api/...`.

То есть:

- Браузер -> `http://127.0.0.1:5173/api/...`
- Vite proxy -> `http://127.0.0.1:8000/api/...`

### 6. Быстрая проверка frontend proxy

При запущенном Vite:

```powershell
Invoke-RestMethod http://127.0.0.1:5173/api/auctions/
```

Если вернулся JSON, связка frontend/backend работает.

## Вариант B: Полностью через Docker (backend тоже в контейнере)

Поднять backend + infra:

```powershell
docker compose up --build web postgres redis
```

Опционально Celery:

```powershell
docker compose up --build celery_worker celery_beat
```

Frontend при этом обычно все равно удобнее запускать локально (`npm run dev`), чтобы видеть быстрый hot reload.

## Вариант C: Полностью локально (без Docker)

Нужно локально установить и запустить:

- PostgreSQL
- Redis
- Python
- Node.js + npm

Дальше backend/frontend поднимаются теми же командами, что в Варианте A (без `docker compose up`).

## Запуск на машине без интернета (offline)

На новой машине без интернета установка зависимостей не сработает, если нет заранее подготовленных пакетов.

Рабочие варианты:

1. Перенести готовые локальные зависимости с совместимой машины (одинаковая ОС/архитектура):
- `venv/`
- `frontend/node_modules/`

2. Использовать локальные кэши пакетов:
- Python wheels: `pip --no-index --find-links <папка_с_wheels> -r backend/requirements.txt`
- npm cache: `npm ci --offline`

3. Использовать заранее скачанные Docker-образы:
- `postgres`
- `redis`
- образ backend (если собирался заранее)

## Частые проблемы и быстрые решения

### 1) Frontend пишет `Unexpected server response`

Обычно это значит, что вместо JSON пришел HTML.

Проверьте:

1. Backend реально запущен на `:8000`
2. Frontend открыт через Vite (`:5173`), а не через `dist/index.html`
3. Vite запущен (`npm run dev`)
4. В браузере нет старого `API base` в `localStorage`

Сбросить в консоли браузера:

```js
localStorage.removeItem("bidfall_api_base");
localStorage.removeItem("bidfall_tokens");
location.reload();
```

### 2) `migrate` не проходит

Проверьте:

1. Установлены зависимости именно из `backend/requirements.txt`
2. Доступна БД из `backend/.env`
3. Поднят Postgres (если используете Docker)

## Что не трогаем при переносе

- `docker-compose.yaml` (основной файл сервисов)

## Связанные документы

- `docs/RUNBOOK.md` — расширенный runbook / troubleshooting
- `docs/CLOSED_STATUS_NOTE.md` — зачем нужен статус `CLOSED`
