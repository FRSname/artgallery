# Gallery Frontend (read‑only)

Public gallery on port **9900**, consuming your ArtworkDB on `http://192.168.88.103:9000`.

## Start
```bash
docker compose up --build -d
# open http://<host>:9900/gallery
```

## Env
- `BACKEND_BASE` – URL of your admin/API app (default http://192.168.88.103:9000)
- `API_KEY` – must match backend's `X-API-Key` requirement
