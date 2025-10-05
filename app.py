# app.py
from __future__ import annotations

import importlib
import os
import pkgutil
import traceback
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

APP_VERSION = "2.4.0"

app = FastAPI(
    title="Juriscraper API",
    description=(
        "Scrapes federal & state court opinions via Juriscraper. "
        "Supports full metadata or short summaries for LLMs."
    ),
    version=APP_VERSION,
)

# --- CORS: allow use from CustomGPT Actions and web clients ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # tighten if you want
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- In-memory cache of available courts (built at startup) ---
COURT_MODULES: List[str] = []
COURT_INDEX_BUILT_AT: Optional[str] = None


def _short_tb() -> List[str]:
    """Return the last few lines of the traceback for lean error payloads."""
    return traceback.format_exc().splitlines()[-8:]


def _build_court_index() -> List[str]:
    """
    Walk the juriscraper.opinions package and record all modules that expose a Site class.
    We collect paths like: 'united_states.federal_appellate.ca9_p'
    """
    modules: List[str] = []
    try:
        import juriscraper.opinions as opinions_pkg
    except Exception:
        # Juriscraper not installed or import error
        return modules

    prefix_pkg = opinions_pkg.__name__ + "."
    for mod in pkgutil.walk_packages(opinions_pkg.__path__, prefix=prefix_pkg):
        modname = mod.name
        # Only leaf modules (skip packages) are actual scrapers
        if mod.ispkg:
            continue
        try:
            m = importlib.import_module(modname)
            if hasattr(m, "Site"):
                # Convert 'juriscraper.opinions.X.Y' -> 'X.Y' for API parameter usage
                if modname.startswith(prefix_pkg):
                    modules.append(modname[len(prefix_pkg):])
        except Exception:
            # Ignore broken imports during index build; they’ll error on demand
            continue
    return sorted(modules)


@app.on_event("startup")
def on_startup() -> None:
    global COURT_MODULES, COURT_INDEX_BUILT_AT
    COURT_MODULES = _build_court_index()
    COURT_INDEX_BUILT_AT = datetime.utcnow().isoformat() + "Z"


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Tiny middleware for basic diagnostics."""
    start = datetime.utcnow()
    response = await call_next(request)
    response.headers["X-App-Version"] = APP_VERSION
    response.headers["X-Request-Start"] = start.isoformat() + "Z"
    return response


@app.get("/")
def root():
    """Landing info + a small sample of courts."""
    sample = COURT_MODULES[:25] if COURT_MODULES else []
    return {
        "message": "Welcome to the Juriscraper API!",
        "description": "Use /scrape?court=<court_path>&max_items=5&summary=true",
        "docs": "/docs",
        "version": APP_VERSION,
        "total_courts": len(COURT_MODULES),
        "index_built_at": COURT_INDEX_BUILT_AT,
        "sample_courts": sample,
    }


@app.get("/health")
def health():
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": APP_VERSION,
    }


@app.get("/courts")
def list_courts(
    prefix: Optional[str] = Query(
        None,
        description="Optional prefix filter, e.g. 'united_states.federal_appellate'",
    ),
    limit: int = Query(500, ge=1, le=5000, description="Max courts to return"),
):
    """
    Returns the list of available court module paths discovered in juriscraper.opinions.
    """
    if not COURT_MODULES:
        return {
            "message": "Court index is empty (juriscraper not installed or index failed).",
            "courts": [],
            "total": 0,
        }
    items = COURT_MODULES
    if prefix:
        items = [c for c in items if c.startswith(prefix)]
    return {
        "total": len(items),
        "limit": limit,
        "returned": min(len(items), limit),
        "courts": items[:limit],
        "prefix": prefix,
        "built_at": COURT_INDEX_BUILT_AT,
    }


def _safe_get(site, attr: str, idx: int):
    """Safely get list-like attribute at index; return None if missing."""
    try:
        return getattr(site, attr)[idx]
    except Exception:
        return None


def _build_case(site, i: int) -> Dict:
    """
    Build a full metadata dict for a single case index from a Juriscraper Site.
    Includes many common optional fields but tolerates their absence.
    """
    case = {
        "name": _safe_get(site, "case_names", i),
        "date": str(_safe_get(site, "case_dates", i)),
        "docket_number": _safe_get(site, "docket_numbers", i),
        "neutral_citation": _safe_get(site, "neutral_citations", i),
        "precedential_status": _safe_get(site, "precedential_statuses", i),
        "download_url": _safe_get(site, "download_urls", i),
        "summary": _safe_get(site, "summaries", i),
        "judge": _safe_get(site, "judges", i),
        # Optional, present on some scrapers:
        "party_names": _safe_get(site, "party_names", i),
        "attorneys": _safe_get(site, "attorneys", i),
        "disposition": _safe_get(site, "dispositions", i),
        "lower_court": _safe_get(site, "lower_courts", i),
        "nature_of_suit": _safe_get(site, "natures_of_suit", i),
        "citation_count": _safe_get(site, "citation_counts", i),
        "block_quote": _safe_get(site, "block_quotes", i),
    }
    # A quick completeness hint for clients
    key_min = ["name", "date", "docket_number", "download_url"]
    case["metadata_complete"] = all(case.get(k) not in (None, "", []) for k in key_min)
    case["status"] = "ok"
    return case


@app.get("/scrape")
def scrape(
    court: str = Query(
        ...,
        description="Court module path under 'juriscraper.opinions', e.g. 'united_states.federal_appellate.ca9_p'",
    ),
    max_items: int = Query(5, ge=1, le=50, description="Max number of items to return"),
    summary: bool = Query(
        False,
        description="If true, return short GPT-friendly summaries instead of full metadata",
    ),
):
    """
    Run a specific Juriscraper court scraper and return results.
    - Uses dynamic import: juriscraper.opinions.<court>.Site
    - Calls site.parse()
    - Returns either full metadata or short summaries (summary=true)
    """
    try:
        module_path = f"juriscraper.opinions.{court}"
        try:
            mod = importlib.import_module(module_path)
        except ModuleNotFoundError:
            # Helpful 404 with a near-match hint
            hint = None
            if COURT_MODULES:
                # nearest simple hint: same prefix group
                prefix = ".".join(court.split(".")[:-1])
                candidates = [c for c in COURT_MODULES if c.startswith(prefix)]
                hint = candidates[:5] if candidates else COURT_MODULES[:5]
            detail = {
                "message": "Court scraper not found.",
                "requested": court,
                "expected_module": module_path,
                "examples": hint,
            }
            raise HTTPException(status_code=404, detail=detail)

        if not hasattr(mod, "Site"):
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "Scraper module does not expose a 'Site' class.",
                    "module": module_path,
                },
            )

        site = mod.Site()
        # Juriscraper will respect environment variables like:
        # - JURISCRAPER_LOG
        # - WEBDRIVER_CONN
        # - SELENIUM_VISIBLE
        # No need to set them here unless you want defaults.

        site.parse()

        # Determine max items by the number of case_names available.
        total_available = len(getattr(site, "case_names", []))
        total = min(max_items, total_available)

        results: List[Dict] = []
        for i in range(total):
            case = _build_case(site, i)
            if summary:
                name = case.get("name") or "Unknown case"
                date = case.get("date") or "Unknown date"
                disp = case.get("disposition") or "No disposition available"
                url = case.get("download_url") or "No URL"
                results.append({"summary": f"{name} ({date}) — {disp}. Source: {url}"})
            else:
                results.append(case)

        return {
            "court": court,
            "status": "ok",
            "mode": "summary" if summary else "full",
            "count": len(results),
            "data": results,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    except HTTPException:
        raise
    except Exception as e:
        # Keep it concise but actionable
        return {
            "court": court,
            "status": "failed",
            "error": str(e),
            "traceback_tail": _short_tb(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
