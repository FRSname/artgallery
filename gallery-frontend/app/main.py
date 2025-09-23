from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os, requests

app = FastAPI(title="Public Gallery")
BASE = os.getenv("BACKEND_BASE", "http://localhost:9000").rstrip("/")
API_KEY = os.getenv("API_KEY", "")
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

def _get(path):
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    r = requests.get(f"{BASE}{path}", headers=headers, timeout=20)
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()

@app.get("/gallery")
def gallery_index(request: Request, q: str | None = None, year_from: str | None = None, year_to: str | None = None):
    items = _get("/api/artworks")
    if q:
        ql = q.lower()
        def hay(a): return f"{a.get('artwork_id','')} {a.get('title','')} {a.get('keywords','')} {a.get('medium','')} {a.get('surface','')}"
        items = [a for a in items if ql in hay(a).lower()]
    if year_from:
        items = [a for a in items if a.get('year','') >= year_from]
    if year_to:
        items = [a for a in items if a.get('year','') <= year_to]
    return templates.TemplateResponse('gallery_list.html', {'request': request, 'artworks': items, 'filters': {'q': q or '', 'year_from': year_from or '', 'year_to': year_to or ''}})

@app.get("/gallery/{artwork_id}")
def gallery_show(artwork_id: str, request: Request):
    a = _get(f"/api/artworks/{artwork_id}")
    return templates.TemplateResponse("gallery_show.html", {"request": request, "artwork": a})

@app.get("/media/{full_path:path}")
def media_proxy(full_path: str):
    url = f"{BASE}/media/{full_path}"
    r = requests.get(url, stream=True, timeout=30)
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail="Media not found")
    return StreamingResponse(r.iter_content(64*1024), headers={"Content-Type": r.headers.get("Content-Type","image/jpeg")})
