from __future__ import annotations

import csv
import importlib
import os
import pkgutil
import traceback
import requests
import subprocess
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

APP_VERSION = "2.5.0"

app = FastAPI(
    title="Juriscraper API",
    description=(
        "Scrapes federal & state court opinions via Juriscraper. "
        "Supports metadata, summaries, and automatic search logging."
    ),
    version=APP_VERSION,
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # optionally restrict later
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Globals ---
COURT_MODULES: List[str] = []
COURT_INDEX_BUILT_AT: Optional[str] = None


def _short_tb() -> List[str]:
    """Return tail of traceback for compact error payloads."""
    return traceback.format_exc().splitlines()[-8:]


def _build_court_index() -> List[str]:
    """Walk juriscraper.opinions for Site subclasses."""
    modules: List[str] = []
    try:
        import juriscraper.opinions as opinions_pkg
    except Exception:
        return modules

    prefix_pkg = opinions_pkg.__name__ + "."
    for mod in pkgutil.walk_packages(opinions_pkg.__path__, prefix=prefix_pkg):
        if mod.ispkg:
            continue
        try:
            m = importlib.import_module(mod.name)
            if hasattr(m, "Site"):
                modules.append(mod.name[len(prefix_pkg):])
        except Exception:
            continue
    return sorted(modules)


@app.on_event("startup")
def on_startup() -> None:
    global COURT_MODULES, COURT_INDEX_BUILT_AT
    COURT_MODULES = _build_court_index()
    COURT_INDEX_BUILT_AT = datetime.utcnow().isoformat() + "Z"


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = datetime.utcnow()
    response = await call_next(request)
    response.headers["X-App-Version"] = APP_VERSION
    response.headers["X-Request-Start"] = start.isoformat() + "Z"
    return response


# --- Logging helper ---
def _log_query(court: str, query_type: str, count: int, data: list[dict]) -> None:
    """
    Logs searches to logs/search_log.csv and optionally commits to GitHub.
    """
    os.makedirs("logs", exist_ok=True)
    log_file = "logs/search_log.csv"
    file_exists = os.path.exists(log_file)
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "court", "query_type", "count", "case_names"])
        writer.writerow([
            datetime.utcnow().isoformat(),
            court,
            query_type,
            count,
            "; ".join([str(d.get("name") or d.get("summary") or "?") for d in data]),
        ])

    # Optional auto-commit to GitHub
    token = os.getenv("GITHUB_TOKEN")
    repo_url = os.getenv("GITHUB_REPO_URL")
    if token and repo_url:
        subprocess.run(["git", "config", "--global", "user.name", "AutoLogger"], check=False)
        subprocess.run(["git", "config", "--global", "user.email", "autologger@example.com"], check=False)
        subprocess.run(["git", "add", log_file], check=False)
        subprocess.run(["git", "commit", "-m", f"Auto-log: {court} {datetime.utcnow().isoformat()}"], check=False)
        subprocess.run(
            ["git", "push", f"https://{token}@{repo_url}", "main"],
            check=False,
        )


# --- Routes ---
@app.get("/")
def root():
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
    prefix: Optional[str] = Query(None, description="Prefix filter, e.g. 'united_states.federal_appellate'"),
    limit: int = Query(500, ge=1, le=5000),
):
    if not COURT_MODULES:
        return {"message": "No courts found (index build failed).", "courts": []}
    items = [c for c in COURT_MODULES if not prefix or c.startswith(prefix)]
    return {
        "total": len(items),
        "limit": limit,
        "returned": min(len(items), limit),
        "courts": items[:limit],
        "prefix": prefix,
        "built_at": COURT_INDEX_BUILT_AT,
    }


def _safe_get(site, attr: str, idx: int):
    try:
        return getattr(site, attr)[idx]
    except Exception:
        return None


def _build_case(site, i: int) -> Dict:
    case = {
        "name": _safe_get(site, "case_names", i),
        "date": str(_safe_get(site, "case_dates", i)),
        "docket_number": _safe_get(site, "docket_numbers", i),
        "neutral_citation": _safe_get(site, "neutral_citations", i),
        "precedential_status": _safe_get(site, "precedential_statuses", i),
        "download_url": _safe_get(site, "download_urls", i),
        "summary": _safe_get(site, "summaries", i),
        "judge": _safe_get(site, "judges", i),
        "party_names": _safe_get(site, "party_names", i),
        "attorneys": _safe_get(site, "attorneys", i),
        "disposition": _safe_get(site, "dispositions", i),
        "lower_court": _safe_get(site, "lower_courts", i),
        "nature_of_suit": _safe_get(site, "natures_of_suit", i),
        "citation_count": _safe_get(site, "citation_counts", i),
        "block_quote": _safe_get(site, "block_quotes", i),
    }
    key_min = ["name", "date", "docket_number", "download_url"]
    case["metadata_complete"] = all(case.get(k) not in (None, "", []) for k in key_min)
    case["status"] = "ok"
    return case


@app.get("/scrape")
def scrape(
    court: str = Query(..., description="Court path, e.g. 'united_states.federal_appellate.ca9_p'"),
    max_items: int = Query(5, ge=1, le=50),
    summary: bool = Query(False, description="If true, return short summaries"),
):
    try:
        module_path = f"juriscraper.opinions.{court}"
        try:
            mod = importlib.import_module(module_path)
        except ModuleNotFoundError:
            hint = [c for c in COURT_MODULES if c.startswith(".".join(court.split(".")[:-1]))][:5]
            raise HTTPException(status_code=404, detail={
                "message": "Court scraper not found.",
                "requested": court,
                "expected_module": module_path,
                "examples": hint or COURT_MODULES[:5],
            })

        if not hasattr(mod, "Site"):
            raise HTTPException(status_code=500, detail={
                "message": "Module lacks 'Site' class.",
                "module": module_path,
            })

        site = mod.Site()
        site.parse()

        total = min(max_items, len(getattr(site, "case_names", [])))
        results = []

        for i in range(total):
            case = _build_case(site, i)
            if summary:
                name = case.get("name") or "Unknown case"
                date = case.get("date") or "Unknown date"
                disp = case.get("disposition") or "No disposition"
                url = case.get("download_url") or "No URL"
                results.append({"summary": f"{name} ({date}) — {disp}. Source: {url}"})
            else:
                results.append(case)

        _log_query(court, "scrape", len(results), results)

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
        return {
            "court": court,
            "status": "failed",
            "error": str(e),
            "traceback_tail": _short_tb(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

COURTLISTENER_BASE = "https://www.courtlistener.com/api/rest/v4"
CL_TOKEN = os.getenv("COURTLISTENER_TOKEN")  # set in environment variables

def cl_get(endpoint: str, params: dict = None):
    """Helper function to query the CourtListener API."""
    headers = {"Authorization": f"Token {CL_TOKEN}"}
    r = requests.get(f"{COURTLISTENER_BASE}/{endpoint.strip('/')}/", headers=headers, params=params or {})
    if r.status_code != 200:
        return {"status": "failed", "error": r.text, "code": r.status_code}
    return r.json()


@app.get("/courtlistener/cluster")
def get_cluster(
    q: str = Query(..., description="Search query, e.g., 'environmental regulation 2022'"),
    limit: int = Query(10, ge=1, le=50),
):
    """Search case clusters on CourtListener."""
    data = cl_get("clusters", {"q": q, "page_size": limit})
    return {"status": "ok", "type": "cluster", "query": q, "results": data}


@app.get("/courtlistener/opinion")
def get_opinion(
    q: str = Query(..., description="Search query, e.g., case name or citation"),
    limit: int = Query(10, ge=1, le=50),
):
    """Search full text opinions on CourtListener."""
    data = cl_get("opinions", {"q": q, "page_size": limit})
    return {"status": "ok", "type": "opinion", "query": q, "results": data}


@app.get("/courtlistener/court")
def get_court_info(
    court_id: Optional[str] = Query(None, description="Court ID (e.g., 'ca9' or 'scotus')"),
):
    """Get details for a specific court or all courts."""
    if court_id:
        data = cl_get(f"courts/{court_id}")
    else:
        data = cl_get("courts")
    return {"status": "ok", "type": "court", "data": data}

