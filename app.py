from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import juriscraper
import importlib

app = FastAPI(title="Juriscraper API", version="1.0")

@app.get("/")
def home():
    return {"message": "Juriscraper API is running"}

@app.get("/scrape")
def scrape(court: str = Query(...), max_items: int = 5):
    try:
        # Build the import path automatically
        module_path = f"juriscraper.opinions.united_states.{court}"
        mod = importlib.import_module(module_path)

        site = mod.Site()
        site.build()

        results = []
        for opinion in site.opinions[:max_items]:
            results.append({
                "date": opinion.get("date"),
                "url": opinion.get("url"),
                "name": opinion.get("name"),
                "docket": opinion.get("docket"),
            })

        return {"count": len(results), "results": results}

    except ModuleNotFoundError as e:
        return JSONResponse(
            status_code=404,
            content={"error": f"Court not found: {court}", "details": str(e)},
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "details": str(e)},
        )
