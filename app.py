from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import importlib
import traceback
import pkgutil
import juriscraper.opinions as opinions_pkg

app = FastAPI(
    title="Juriscraper API",
    version="4.0",
    description="API wrapper for Juriscraper to fetch U.S. court opinions and metadata."
)

def discover_all_courts():
    """Recursively find all available Juriscraper opinion scrapers."""
    scrapers = []
    for loader, module_name, is_pkg in pkgutil.walk_packages(opinions_pkg.__path__, opinions_pkg.__name__ + "."):
        # Only include actual court scrapers under united_states.*
        if "juriscraper.opinions.united_states" in module_name and not module_name.endswith("__init__"):
            name = module_name.replace("juriscraper.opinions.", "")
            scrapers.append(name)
    return sorted(scrapers)

# Build once at startup
ALL_COURTS = discover_all_courts()

@app.get("/")
def index():
    """Root endpoint — list all available courts."""
    return {
        "message": "Welcome to the Juriscraper API!",
        "description": "Use /scrape?court=<court_path>&max_items=3 to fetch opinions.",
        "total_courts": len(ALL_COURTS),
        "available_courts": ALL_COURTS
    }

@app.get("/scrape")
def scrape(
    court: str = Query(..., description="Court path, e.g. united_states.federal_appellate.ca9_p"),
    max_items: int = Query(3, ge=1, le=50, description="Maximum number of results")
):
    """Scrape and return recent opinions for the given court."""
    try:
        court = court.strip().replace("juriscraper.", "").replace("..", ".")
        if court not in ALL_COURTS:
            raise HTTPException(status_code=404, detail=f"Court scraper not found: {court}")

        module = importlib.import_module(f"juriscraper.opinions.{court}")
        site = module.Site()
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

        return {"court": court, "result_count": len(results), "results": results}

    except ModuleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scraper not found: {court}")
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "traceback": traceback.format_exc()},
        )

