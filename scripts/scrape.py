import importlib
import orjson
from datetime import datetime, timedelta
from pathlib import Path
from tqdm import tqdm
from scripts.utils import stable_id, slugify

# Pick a few reliable, non-Selenium courts first
DEFAULT_COURTS = [
    "united_states.federal_appellate.ca9_p",
    "united_states.federal_appellate.cafc",
    "united_states.federal_appellate.ca5",
    "united_states.federal_appellate.ca2_p",
    "united_states.federal_appellate.scotus_slip",
]

OUT = Path("data")
OUT.mkdir(parents=True, exist_ok=True)

def harvest_one(module_path: str, days_back: int = 7, limit: int = 200):
    """Fetch recent opinions with Juriscraper and write JSONL to data/."""
    mod = importlib.import_module(f"juriscraper.opinions.{module_path}")
    site = mod.Site()
    # Many scrapers accept a date filter via site.parameters; fall back to default iteration.
    cutoff = datetime.utcnow().date() - timedelta(days=days_back)
    records = []

    # Juriscraper exposes standardized fields after calling .parse()
    # We iterate the site; some use pages, some direct.
    site.parse()

    def col(name, idx):
        try:
            return site.__dict__[name][idx]
        except Exception:
            return None

    for i in range(len(site.case_names)):
        rec = {
            "id": stable_id(f"{module_path}|{col('case_names', i)}|{col('download_urls', i)}"),
            "court_path": module_path,
            "case_name": col("case_names", i),
            "docket": col("docket_numbers", i),
            "date_filed": col("case_dates", i),
            "precedential_status": col("precedential_statuses", i),
            "neutral_citation": col("neutral_citations", i),
            "summary": col("summaries", i),
            "download_url": col("download_urls", i),
            "source_url": col("case_names_urls", i) or col("urls", i),
        }
        # date filter (best-effort; skip if missing)
        try:
            if rec["date_filed"] and rec["date_filed"] < cutoff:
                continue
        except Exception:
            pass

        records.append(rec)
        if len(records) >= limit:
            break

    fname = OUT / f"{slugify(module_path)}.jsonl"
    with fname.open("wb") as f:
        for r in records:
            f.write(orjson.dumps(r) + b"\n")
    print(f"wrote {len(records)} -> {fname}")

if __name__ == "__main__":
    for court in DEFAULT_COURTS:
        harvest_one(court, days_back=7, limit=200)
