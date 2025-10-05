from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from juriscraper.OpinionSite import OpinionSite
import traceback

app = FastAPI(
    title="Juriscraper API",
    description="Scrapes federal and state court opinions via Juriscraper, including full metadata.",
    version="2.1.0",
)

# Enable CORS for CustomGPT and external use
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    """
    Root endpoint for API info and available usage pattern.
    """
    return {
        "message": "Welcome to the Juriscraper API!",
        "example_usage": "/scrape?court=united_states.federal_appellate.ca9_p&max_items=3",
        "docs": "/docs",
        "description": "Use /scrape to fetch cases with metadata. Each court scraper can be found under united_states.*",
    }


@app.get("/scrape")
def scrape(
    court: str = Query(..., description="Court scraper path (e.g. united_states.federal_appellate.ca9_p)"),
    max_items: int = Query(5, description="Maximum number of cases to return (default 5)"),
):
    """
    Core endpoint: runs a Juriscraper scraper for the given court and returns structured data.
    """
    try:
        # Initialize the court scraper
        site = OpinionSite(court)
        site.parse()

        # Helper for safely accessing attributes
        def safe_get(attr, i):
            try:
                return getattr(site, attr)[i]
            except Exception:
                return None

        results = []
        total = min(max_items, len(site.case_names))

        for i in range(total):
            data = {
                "name": safe_get("case_names", i),
                "date": str(safe_get("case_dates", i)),
                "docket_number": safe_get("docket_numbers", i),
                "neutral_citation": safe_get("neutral_citations", i),
                "precedential_status": safe_get("precedential_statuses", i),
                "download_url": safe_get("download_urls", i),
                "summary": safe_get("summaries", i),
                "judge": safe_get("judges", i),
                "nature_of_suit": safe_get("natures_of_suit", i) if hasattr(site, "natures_of_suit") else None,
                "disposition": safe_get("dispositions", i) if hasattr(site, "dispositions") else None,
                "lower_court": safe_get("lower_courts", i) if hasattr(site, "lower_courts") else None,
                "citation_count": safe_get("citation_counts", i) if hasattr(site, "citation_counts") else None,
                "block_quote": safe_get("block_quotes", i) if hasattr(site, "block_quotes") else None,
                "attorneys": safe_get("attorneys", i) if hasattr(site, "attorneys") else None,
                "party_names": safe_get("party_names", i) if hasattr(site, "party_names") else None,
                "status": "ok"
            }
            results.append(data)

        return {
            "court": court,
            "status": "ok",
            "count": len(results),
            "data": results,
        }

    except Exception as e:
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
