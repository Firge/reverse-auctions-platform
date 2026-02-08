# reverse-auctions-platform



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