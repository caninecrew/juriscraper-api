from fastapi import FastAPI, Query
from importlib import import_module
import traceback
import pkgutil
import json
from datetime import datetime

app = FastAPI(title="Juriscraper API", version="2.0.0")

# ---------- Utility: Safe dynamic import ---------- #
def safe_load_site(court: str):
    """
    Safely loads a Juriscraper Site object for the given court path.
    Always returns either a valid Site instance or an error dict.
    """
    try:
        module_path = f"juriscraper.opinions.{court}"
        module = import_module(module_path)
        if not hasattr(module, "Site"):
            return {"error": f"No 'Site' class found in {module_path}", "status": "unsupported"}
        site = module.Site()
        return site
    except Exception as e:
        return {
            "error": f"Failed to load scraper for {court}",
            "exception": str(e),
            "trace": traceback.format_exc(limit=2)
        }

# ---------- Utility: Safe scraper execution ---------- #
def safe_scrape(site, max_items: int = 3):
    """
    Executes a Juriscraper scraper safely.
    Returns parsed results or structured error info.
    """
    try:
        # Some Juriscraper scrapers don't require build_court_object()
        if hasattr(site, "build_court_object"):
            site.build_court_object()

        site.parse()

        # Collect data consistently
        data = []
        if hasattr(site, "opinions"):
            for item in site.opinions[:max_items]:
                data.append({
                    "date": str(item.get("date")),
                    "name": item.get("name"),
                    "url": item.get("url"),
                    "docket": item.get("docket"),
                })
        elif hasattr(site, "case_names"):
            data = [{"name": n} for n in site.case_names[:max_items]]

        return {"status": "ok", "count": len(data), "data": data}

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "trace": traceback.format_exc(limit=3)
        }

# ---------- Endpoint: Home (list courts) ---------- #
@app.get("/")
def index():
    """
    Root endpoint: lists all available Juriscraper courts.
    """
    try:
        import juriscraper.opinions.united_states as us
        court_paths = []

        # Recursively discover all modules
        def walk_packages(path, prefix):
            for _, name, ispkg in pkgutil.iter_modules(path):
                full_name = f"{prefix}.{name}"
                court_paths.append(full_name)
                if ispkg:
                    mod = import_module(full_name)
                    if hasattr(mod, "__path__"):
                        walk_packages(mod.__path__, full_name)

        walk_packages(us.__path__, "united_states")

        return {
            "message": "Welcome to the Juriscraper API!",
            "description": "Use /scrape?court=<court_path>&max_items=3 to fetch opinions.",
            "total_courts": len(court_paths),
            "available_courts": court_paths[:50],  # show first 50 for brevity
            "example_usage": "/scrape?court=united_states.federal_appellate.ca9_p&max_items=3",
            "docs": "/docs"
        }

    except Exception as e:
        return {"message": "Error loading courts", "error": str(e)}

# ---------- Endpoint: Scrape ---------- #
@app.get("/scrape")
def scrape(court: str = Query(..., description="Court module path (e.g. united_states.federal_appellate.ca9_p)"),
           max_items: int = Query(3, description="Number of opinions to fetch")):
    """
    Scrapes the requested court for opinions using Juriscraper.
    Handles all errors gracefully and never crashes.
    """
    site = safe_load_site(court)

    # If scraper failed to load
    if isinstance(site, dict) and "error" in site:
        return {
            "message": "Scraper unavailable or broken.",
            "court": court,
            **site
        }

    # Run safely
    result = safe_scrape(site, max_items=max_items)

    # Log any persistent failures for debugging
    if result.get("status") == "error":
        with open("broken_scrapers.log", "a") as f:
            f.write(f"{datetime.now()} - {court} - {result['error']}\n")

    return {"court": court, **result}
