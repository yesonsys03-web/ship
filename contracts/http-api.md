# Shipment Prototype HTTP API

All prototype endpoints exchange JSON over HTTP.

## Sender backend

`POST /scan`

Request:

```json
{ "path": "/Users/me/Desktop/ShipmentFolder" }
```

Response: shipment manifest draft with `files` populated from the folder.

`POST /send`

Request: shipment manifest. The sender backend writes it to the shared SQLite DB selected from these directories, preferring the first candidate that already contains `shipments.sqlite3`:

1. `/USA_DB/test_jn/ship_db`
2. `/System/Volumes/Data/mnt/USA_DB/test_jn/ship_db`

The DB file name is `shipments.sqlite3`. `SHIP_DB_DIR` can override the directory for development/testing.

Response:

```json
{ "ok": true, "id": "ship-...", "folder_name": "HH_304", "db_path": "/USA_DB/test_jn/ship_db/shipments.sqlite3" }
```

`GET /history`

Returns sender previous-transfer history from the same shared SQLite DB. If the DB file is missing, this returns an empty array and does not create a DB file.

Response:

```json
[]
```

## Manager backend

`POST /shipments`

Receives a shipment manifest and stores it in the same shared SQLite DB. This endpoint remains for compatibility/manual tests; the sender no longer needs to call the manager PC over HTTP.

`GET /shipments`

Returns a year/month/folder navigation tree from the shared SQLite DB.

`GET /shipment?id=<shipment-id>`

Returns one stored shipment manifest from the shared SQLite DB.
