from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import importlib
import traceback
import pkgutil
import juriscraper.opinions.united_states as us_opinions

app = FastAPI(title="Juriscraper API", version="3.0")

# Recursively discover all valid scrapers
VALID_SCRAPERS = [
    name.replace("juriscraper.opinions.", "")
    for _, name, _ in pkgutil.walk_packages(us_opinions.__path__, "united_states.")
    if not name.endswith("__init__")
]

@app.get("/")
def home():
    """Root endpoint listing usage and scraper count"""
    return {
        "message": "Welcome to the Juriscraper API!",
        "example_usage": "/scrape?court=united_states.federal_appellate.ca9_p&max_items=3",
        "docs": "/docs",
        "valid_example": VALID_SCRAPERS[:5],
        "count": len(VALID_SCRAPERS),
    }

@app.get("/scrape")
def scrape(
    court: str = Query(..., description="Court path, e.g. united_states.federal_appellate.ca9_p"),
    max_items: int = Query(3, ge=1, le=50, description="Maximum number of results")
):
    """Scrape opinions using Juriscraper"""
    try:
        court = court.strip().replace("juriscraper.", "").replace("..", ".")
        if court not in VALID_SCRAPERS:
            raise HTTPException(status_code=404, detail=f"Scraper not found: {court}")

        mod = importlib.import_module(f"juriscraper.opinions.{court}")
        site = mod.Site()
        site.build_court_object()

        results = []
        for i, opinion in enumerate(site):
            if i >= max_items:
                break
            results.append({
                "case_name": opinion.get("case_name"),
                "date_filed": str(opinion.get("date_filed")),
                "download_url": opinion.get("download_url"),
                "docket_number": opinion.get("docket_number"),
                "precedential_status": opinion.get("precedential_status"),
            })

        return {"court": court, "results": results}

    except ModuleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scraper not found: {court}")
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "traceback": traceback.format_exc()},
        )
