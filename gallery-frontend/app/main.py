from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import os
import requests
from datetime import datetime, timedelta
from typing import Optional

app = FastAPI(title="Public Gallery")
BASE = os.getenv("BACKEND_BASE", "http://localhost:9000").rstrip("/")
API_KEY = os.getenv("API_KEY", "")
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Simple in-memory cache to reduce backend calls
_cache: dict = {}
_cache_time: dict = {}
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))  # seconds

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # adjust for production: os.getenv("ALLOWED_ORIGINS", "*").split(",")
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get(path: str):
    """
    Fetch data from backend API with caching.
    Returns cached data if still valid, otherwise fetches fresh data.
    """
    # Return cached value if fresh
    last = _cache_time.get(path)
    if path in _cache and last and (datetime.now() - last) < timedelta(seconds=CACHE_TTL):
        return _cache[path]

    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    try:
        r = requests.get(f"{BASE}{path}", headers=headers, timeout=20)
        if not r.ok:
            raise HTTPException(status_code=r.status_code, detail=r.text)

        data = r.json()
        _cache[path] = data
        _cache_time[path] = datetime.now()
        return data
    except requests.RequestException as e:
        # Handle network errors gracefully
        raise HTTPException(status_code=503, detail=f"Backend service unavailable: {str(e)}")


@app.get("/")
def root():
    """Health check endpoint"""
    return {"status": "ok", "app": "Public Gallery", "version": "1.0"}


@app.get("/gallery")
def gallery_index(
    request: Request,
    q: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    medium: Optional[str] = None,
    page: int = 1,
    per_page: int = 24,
):
    """
    Gallery listing page with search, filters, and pagination.
    """
    # Validate pagination parameters
    if per_page < 1 or per_page > 100:
        per_page = 24
    if page < 1:
        page = 1

    items = _get("/api/artworks") or []

    # Text search across several fields
    if q:
        ql = q.lower().strip()
        if ql:  # Only filter if query is not empty after stripping
            def matches_query(a):
                haystack = f"{a.get('artwork_id','')} {a.get('title','')} {a.get('keywords','')} {a.get('medium','')} {a.get('surface','')}".lower()
                return ql in haystack
            items = [a for a in items if matches_query(a)]

    # Year filters with safe int conversion
    if year_from is not None:
        def year_gte(a):
            year = a.get('year')
            if not year:
                return False
            try:
                return int(year) >= year_from
            except (ValueError, TypeError):
                return False
        items = [a for a in items if year_gte(a)]

    if year_to is not None:
        def year_lte(a):
            year = a.get('year')
            if not year:
                return False
            try:
                return int(year) <= year_to
            except (ValueError, TypeError):
                return False
        items = [a for a in items if year_lte(a)]

    # Medium filter (case-insensitive exact match)
    if medium:
        medium_lower = medium.lower().strip()
        items = [a for a in items if a.get('medium', '').lower() == medium_lower]

    # Get unique mediums for dropdown (from all artworks, not filtered)
    all_artworks = _get("/api/artworks") or []
    mediums = sorted({
        a.get('medium', '').strip() 
        for a in all_artworks 
        if a.get('medium', '').strip()
    })

    # Pagination
    total_items = len(items)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    
    # Clamp page to valid range
    page = max(1, min(page, total_pages if total_items > 0 else 1))
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_items = items[start_idx:end_idx]

    return templates.TemplateResponse('gallery_list.html', {
        'request': request,
        'artworks': paginated_items,
        'mediums': mediums,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_items': total_items,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': page < total_pages
        },
        'filters': {
            'q': q or '',
            'year_from': year_from if year_from is not None else '',
            'year_to': year_to if year_to is not None else '',
            'medium': medium or ''
        }
    })


@app.get("/gallery/{artwork_id}")
def gallery_show(artwork_id: str, request: Request):
    """
    Individual artwork detail page.
    """
    # Validate artwork_id format (basic security check)
    if not artwork_id or len(artwork_id) > 50:
        raise HTTPException(status_code=400, detail="Invalid artwork ID")
    
    try:
        artwork = _get(f"/api/artworks/{artwork_id}")
        return templates.TemplateResponse("gallery_show.html", {
            "request": request, 
            "artwork": artwork
        })
    except HTTPException as e:
        if e.status_code == 404:
            # Render a friendly 404 page
            return templates.TemplateResponse(
                "404.html", 
                {"request": request, "message": "Artwork not found"}, 
                status_code=404
            )
        raise


@app.get("/media/{full_path:path}")
def media_proxy(full_path: str):
    """
    Proxy media files from backend to avoid CORS issues.
    """
    # Basic security: prevent path traversal
    if ".." in full_path or full_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid media path")
    
    url = f"{BASE}/media/{full_path}"
    
    try:
        r = requests.get(url, stream=True, timeout=30)
        if not r.ok:
            raise HTTPException(status_code=r.status_code, detail="Media not found")
        
        # Determine content type
        content_type = r.headers.get("Content-Type", "application/octet-stream")
        
        # Add security headers
        headers = {
            "Content-Type": content_type,
            "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
        }
        
        return StreamingResponse(
            r.iter_content(chunk_size=64*1024), 
            headers=headers
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Media service unavailable: {str(e)}")


@app.get("/api/stats")
def stats():
    """
    Statistics endpoint showing artwork distribution.
    """
    items = _get("/api/artworks") or []
    
    mediums = {}
    years = {}
    
    for item in items:
        # Count by medium
        medium = item.get('medium')
        if medium:
            medium = medium.strip()
            mediums[medium] = mediums.get(medium, 0) + 1
        else:
            mediums['Unknown'] = mediums.get('Unknown', 0) + 1
        
        # Count by year
        year = item.get('year')
        if year:
            try:
                year = str(int(year))  # Normalize year format
                years[year] = years.get(year, 0) + 1
            except (ValueError, TypeError):
                years['Unknown'] = years.get('Unknown', 0) + 1
        else:
            years['Unknown'] = years.get('Unknown', 0) + 1

    return {
        "total_artworks": len(items),
        "by_medium": dict(sorted(mediums.items())),
        "by_year": dict(sorted(years.items(), reverse=True))
    }


@app.get("/health")
def health_check():
    """
    Health check endpoint for monitoring.
    """
    try:
        # Test backend connectivity
        _get("/api/artworks")
        return {
            "status": "healthy",
            "backend": "connected",
            "cache_size": len(_cache),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "backend": "disconnected",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# Optional: Add endpoint to clear cache (useful for debugging)
@app.post("/api/cache/clear")
def clear_cache(api_key: str):
    """
    Clear the cache. Requires API key for security.
    """
    if api_key != API_KEY or not API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    _cache.clear()
    _cache_time.clear()
    
    return {
        "status": "success",
        "message": "Cache cleared",
        "timestamp": datetime.now().isoformat()
    }