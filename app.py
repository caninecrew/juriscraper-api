from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import importlib
import traceback

app = FastAPI(
    title="Juriscraper API",
    description="Simple REST API wrapper around the Juriscraper library for court opinions.",
    version="1.0.0"
)


@app.get("/")
def home():
    """Root route for health check and usage example."""
    return {
        "message": "Welcome to the Juriscraper API!",
        "example_usage": "/scrape?court=united_states.federal_appellate.ca9&max_items=3",
        "docs": "/docs"
    }


@app.get("/scrape")
def scrape(
    court: str = Query(..., description="Juriscraper court module path, e.g., united_states.federal_appellate.ca9"),
    max_items: int = Query(3, description="Maximum number of cases to return")
):
    """
    Dynamically load and execute a Juriscraper module to retrieve case data.
    Example: /scrape?court=united_states.federal_appellate.ca9
    """

    # Convert underscores to dots if the user used them in the query
    court_path = court.replace("_", ".")

    try:
        # Try to import the requested Juriscraper scraper module
        module = importlib.import_module(f"juriscraper.opinions.{court_path}")
    except ModuleNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Court scraper not found: juriscraper.opinions.{court_path}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import error: {str(e)}")

    try:
        # Initialize and run the scraper
        site = module.Site()
        site.build()

        cases = site.cases
        results = []
        for idx, case in enumerate(cases[:max_items]):
            results.append({
                "date": case.get("date_filed"),
                "title": case.get("name"),
                "docket": case.get("docket"),
                "url": case.get("url"),
                "status": case.get("status"),
            })

        return JSONResponse(
            content={
                "court": court,
                "count": len(results),
                "results": results
            }
        )

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Scraper error: {str(e)}")


@app.get("/courts")
def list_examples():
    """Helpful preset examples."""
    return {
        "examples": [
            "united_states.federal_appellate.ca9",
            "united_states.state.kan_p",
            "united_states.federal_appellate.ca2"
        ],
        "usage": "/scrape?court=united_states.federal_appellate.ca9"
    }
