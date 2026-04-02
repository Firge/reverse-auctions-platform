# Catalog API Frontend Contract (v0.1)

API-контракт, который нужен frontend для выбора лотов (поиск + дерево) и передачи лотов в create/update аукциона.

## Scope

Покрываем:
- чтение дерева каталога;
- поиск и фильтрацию позиций каталога;
- восстановление позиций по id;
- формат поля `lots` в create/update аукциона;
- валидационные и прикладные ошибки, которые frontend умеет показать.

Не покрываем:
- детали внутренней backend-реализации;
- SQL/ORM оптимизации;
- миграции и административные интерфейсы.

## Auth

- Read-only endpoints каталога: допускается anonymous доступ.
- Create/Update auction: требуется Bearer token.

## Endpoint Matrix

1) `GET /api/catalog/nodes/`
- Назначение: загрузка узлов дерева каталога.
- Query параметры:
  - `parent_id` (number, optional): вернуть дочерние узлы.
  - `q` (string, optional): поиск по названию узла.
  - `limit` (number, optional).
  - `offset` (number, optional).
- `200` response:

```json
{
  "count": 2,
  "results": [
    {
      "id": 34,
      "name": "Сухие смеси",
      "parent_id": 12,
      "has_children": false,
      "items_count": 148
    }
  ]
}
```

2) `GET /api/catalog/items/`
- Назначение: поиск и фильтрация позиций.
- Query параметры:
  - `q` (string, optional): поиск по `code` и `name`.
  - `node_id` (number, optional).
  - `source_id` (number, optional).
  - `limit` (number, optional).
  - `offset` (number, optional).
- `200` response:

```json
{
  "count": 1,
  "results": [
    {
      "id": 120451,
      "code": "03.02.01",
      "name": "Смесь штукатурная цементная",
      "unit": "кг",
      "node_id": 34,
      "source_id": 5,
      "default_quantity": "1.00"
    }
  ]
}
```

3) `GET /api/catalog/items/by-ids/`
- Назначение: массовое восстановление карточек по id (например, при открытии DRAFT).
- Query параметры:
  - `ids` (string, required): список id через запятую, например `101,102,205`.
- `200` response:

```json
[
  {
    "id": 101,
    "code": "03.02.01",
    "name": "Смесь штукатурная цементная",
    "unit": "кг",
    "node_id": 34,
    "source_id": 5,
    "default_quantity": "1.00"
  }
]
```

## Auction Create/Update Contract Extension

### POST `/api/auctions/`
### PATCH `/api/auctions/{id}/`

Добавляется/поддерживается поле `lots`:

```json
{
  "title": "Закупка отделочных материалов",
  "description": "С поставкой в течение 10 дней",
  "start_price": 100000,
  "start_date": "2026-04-03T09:00:00.000Z",
  "end_date": "2026-04-05T09:00:00.000Z",
  "auction_type": "reverseenglishauction",
  "min_bid_decrement": 500,
  "lots": [
    { "id": 101, "quantity": "120.50" },
    { "id": 103, "quantity": "3" }
  ]
}
```

Правила:
- `lots` обязателен для создания и не должен быть пустым.
- `id` должен ссылаться на `catalog_item.id`.
- `quantity` строкой в decimal формате, значение > 0.
- Дубликаты `id` недопустимы (frontend предварительно dedupe, backend валидирует).
- Изменение `lots` после публикации запрещено (backend должен вернуть прикладную ошибку).

## Auction Read Compatibility

`GET /api/auctions/{id}/` должен возвращать `lots` в структуре, пригодной для текущего UI:

```json
{
  "id": 9001,
  "title": "Закупка отделочных материалов",
  "lots": [
    {
      "id": 101,
      "code": "03.02.01",
      "name": "Смесь штукатурная цементная",
      "unit": "кг",
      "quantity": "120.50"
    }
  ]
}
```

Переходная совместимость:
- на время миграции допускается `catalog_items` вместо `lots`;
- frontend нормализует `lots ?? catalog_items`.

## Error Taxonomy

### 400 Validation

```json
{
  "lots": ["Выберите хотя бы один лот"],
  "lots[0].quantity": ["Должно быть числом больше 0"]
}
```

### 401 Unauthorized

```json
{
  "detail": "Authentication credentials were not provided."
}
```

### 403 Forbidden

```json
{
  "detail": "У вас нет прав на изменение этого аукциона."
}
```

### 409 Draft-only change rejected

```json
{
  "error": "draft_only",
  "detail": "Изменение лотов доступно только для DRAFT аукциона."
}
```

## Frontend Mapping

`CatalogNode`:
- `id: number`
- `name: string`
- `parent_id: number | null`
- `has_children: boolean`
- `items_count: number`

`CatalogItem`:
- `id: number`
- `code: string`
- `name: string`
- `unit: string`
- `node_id: number`
- `source_id: number | null`
- `default_quantity?: string | null`

`AuctionLotInput`:
- `id: number`
- `quantity: string`

## Acceptance Checklist

1. Frontend может загрузить узлы каталога и позиции по поиску.
2. Frontend может восстановить позиции по id через bulk endpoint.
3. Create auction с `lots` валидируется по agreed правилам.
4. Patch auction с `lots` работает только в DRAFT.
5. Ошибки по `lots` приходят в field-ориентированном формате.
6. Read auction возвращает `lots` (или совместимый `catalog_items` на переходный период).

## Integration Notes


Во frontend добавлен переключаемый прототипный режим каталога:
- `VITE_CATALOG_API_MODE=mock` для локальной отладки без backend endpoint-ов;
- `VITE_CATALOG_API_MODE=real` для работы с backend.

Дополнительно режим можно переключить в браузере через localStorage key `bidfall_catalog_api_mode`.
