# reverse-auctions-platform

## Run / Setup Guide
See `docs/RUNBOOK.md` for startup modes (local/Docker, online/offline), troubleshooting, and environment setup.

## CI/CD Docker artifacts

The repository publishes Docker artifacts to GHCR on each push to `main` via GitHub Actions.

Published images:
- `ghcr.io/<owner>/<repo>/backend:<sha>` and `:latest`
- `ghcr.io/<owner>/<repo>/frontend:<sha>` and `:latest`
- `ghcr.io/<owner>/<repo>/tools:<sha>` and `:latest`

Pipeline files:
- `.github/workflows/docker-image.yml`
- `docker-compose.build.hcl`

To run image-based deployment locally:
1. Copy `.env.prod.example` to `.env.prod` and set `IMAGE_NAMESPACE`.
2. Pull images from GHCR:
	- `docker pull ghcr.io/<owner>/<repo>/backend:latest`
	- `docker pull ghcr.io/<owner>/<repo>/frontend:latest`
3. Start production compose:
	- `docker compose --env-file .env.prod -f docker-compose.prod.yaml up -d`



## Tools & automation
Для генерации на данном этапе предлагается использовать питон скрипт для создания каталога.
Чтобы заполнить бд необходимо выполнить следующие команды:
1. `docker compose up -d postgres`
2. `docker compose --profile pipeline run --rm pipeline`
Данный профиль спарсит таблицу pdf формата и заполнит бд

### Database schema
Нормализованная схема состоит из трех таблиц:

#### catalog_nodes
Дерево каталога (section -> subsection -> group -> spec).

| Column    | Type    | Notes |
|-----------|---------|-------|
| id        | bigserial | PK |
| kind      | text    | section/subsection/group/spec |
| name      | text    | Название узла |
| parent_id | bigint  | FK -> catalog_nodes.id |

#### catalog_sources
Источники (одна запись на PDF).

| Column | Type     | Notes |
|--------|----------|-------|
| id     | bigserial | PK |
| name   | text     | UNIQUE |

#### catalog_items
Листовые позиции каталога.

| Column        | Type        | Notes |
|---------------|-------------|-------|
| id            | bigserial   | PK |
| code          | text        | Код позиции |
| name          | text        | Название позиции |
| unit          | text        | Ед. измерения |
| price_release | numeric(14,2) | Цена отпускная |
| price_estimate| numeric(14,2) | Цена сметная |
| node_id       | bigint      | FK -> catalog_nodes.id |
| source_id     | bigint      | FK -> catalog_sources.id |
