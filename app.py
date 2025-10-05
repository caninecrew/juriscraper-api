from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from juriscraper.OpinionSite import OpinionSite
import traceback
from datetime import datetime

app = FastAPI(
    title="Juriscraper API",
    description="Scrapes federal and state court opinions via Juriscraper, with metadata and summary mode.",
    version="2.2.0",
)

# Enable CORS for CustomGPT and web integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    """
    Root endpoint for info and example.
    """
    return {
        "message": "Welcome to the Juriscraper API!",
        "example_usage": "/scrape?court=united_states.federal_appellate.ca9_p&max_items=3&summary=true",
        "docs": "/docs",
        "description": "Use /scrape to fetch cases with metadata or summary mode. Pass ?summary=true for short summaries.",
    }


@app.get("/scrape")
def scrape(
    court: str = Query(..., description="Court scraper path (e.g. united_states.federal_appellate.ca9_p)"),
    max_items: int = Query(5, description="Maximum number of cases to return (default 5)"),
    summary: bool = Query(False, description="If true, returns short summaries instead of full metadata")
):
    """
    Runs a Juriscraper scraper for the given court and returns structured data.
    If `summary=true`, returns concise summaries for GPT integration.
    """
    try:
        site = OpinionSite(court)
        site.parse()

        def safe_get(attr, i):
            try:
                return getattr(site, attr)[i]
            except Exception:
                return None

        results = []
        total = min(max_items, len(site.case_names))

        for i in range(total):
            # Full metadata
            case_data = {
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

            if summary:
                # Short GPT-friendly summary
                case_name = case_data["name"] or "Unknown Case"
                date_str = case_data["date"] or "Unknown Date"
                disposition = case_data["disposition"] or "No disposition available"
                short = f"{case_name} ({date_str}) — {disposition}. See {case_data['download_url']} for details."
                results.append({"summary": short})
            else:
                results.append(case_data)

        return {
            "court": court,
            "status": "ok",
            "count": len(results),
            "mode": "summary" if summary else "full",
            "data": results,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    except Exception as e:
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "court": court,
            "status": "failed"
        }

