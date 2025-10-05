from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import importlib
import traceback
import pkgutil
import juriscraper.opinions

app = FastAPI(title="Juriscraper API", version="2.0")

# Automatically generate valid scraper paths
VALID_SCRAPERS = [
    name for _, name, _ in pkgutil.walk_packages(juriscraper.opinions.__path__, "united_states.")
]

@app.get("/")
def home():
    return {
        "message": "Welcome to the Juriscraper API!",
        "example_usage": "/scrape?court=united_states.federal_appellate.ca9&max_items=3",
        "docs": "/docs",
        "valid_example": VALID_SCRAPERS[:5]  # show the first 5
    }


@app.get("/scrape")
def scrape(
    court: str = Query(..., description="Example: united_states.federal_appellate.ca9"),
    max_items: int = 3
):
    try:
        # sanitize user input
        court = court.strip().replace("juriscraper.", "").replace("..", ".")
        
        if court not in VALID_SCRAPERS:
            raise HTTPException(status_code=404, detail=f"Court not recognized: {court}")

        # dynamic import
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
                "precedential_status": opinion.get("precedential_status")
            })

        return {"court": court, "results": results}

    except ModuleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scraper not found for {court}")
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "traceback": traceback.format_exc()},
        )
