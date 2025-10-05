from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import traceback
import importlib

app = FastAPI(title="Juriscraper API", version="1.0")

def safe_scrape(site, max_items: int = 3):
    """
    Safely runs a Juriscraper site object.
    Prevents AttributeErrors like 'build_court_object' missing.
    """
    try:
        # Some scrapers need to be initialized
        if hasattr(site, "build_court_object") and callable(site.build_court_object):
            try:
                site.build_court_object()
            except Exception:
                pass  # not critical, continue silently

        # Run or parse depending on implementation
        if hasattr(site, "run") and callable(site.run):
            site.run()
        elif hasattr(site, "parse") and callable(site.parse):
            site.parse()

        # Collect results from available attributes
        results = []
        for attr in ["opinions", "cases", "items"]:
            if hasattr(site, attr):
                data = getattr(site, attr)
                if isinstance(data, list):
                    for item in data[:max_items]:
                        if isinstance(item, dict):
                            results.append(item)
                        else:
                            results.append({"text": str(item)})
                break

        if not results and hasattr(site, "case_names"):
            names = getattr(site, "case_names", [])
            results = [{"name": n} for n in names[:max_items]]

        return {"status": "ok", "count": len(results), "data": results}

    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc(limit=3)}


@app.get("/")
def home():
    return {
        "message": "Welcome to the Juriscraper API!",
        "description": "Use /scrape?court=<court_path>&max_items=3 to fetch opinions.",
        "example_usage": "/scrape?court=united_states.federal_appellate.ca9_p&max_items=3"
    }


@app.get("/scrape")
def scrape(
    court: str = Query(..., description="Juriscraper court module path"),
    max_items: int = Query(3, ge=1, le=20)
):
    try:
        # Import dynamically
        module_path = f"juriscraper.opinions.{court}"
        module = importlib.import_module(module_path)

        # Get Site class dynamically
        if hasattr(module, "Site"):
            site = module.Site()
        else:
            return JSONResponse(status_code=400, content={
                "error": f"No Site class in {module_path}"
            })

        result = safe_scrape(site, max_items=max_items)
        result["court"] = court
        return result

    except ModuleNotFoundError:
        return JSONResponse(status_code=404, content={
            "error": f"Court scraper not found: juriscraper.opinions.{court}"
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "traceback": traceback.format_exc(limit=3)
        })
