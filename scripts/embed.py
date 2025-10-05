import json, orjson, math
from pathlib import Path
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from scripts.utils import slugify

RAW = Path("data")
IDX = Path("index")
IDX.mkdir(parents=True, exist_ok=True)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384
SHARD_SIZE = 800  # keep files small for GPT Actions to fetch

def load_records():
    for p in RAW.glob("*.jsonl"):
        with p.open("rb") as f:
            for line in f:
                yield orjson.loads(line), p.stem

def text_for_embedding(rec: dict) -> str:
    bits = [
        rec.get("case_name") or "",
        rec.get("docket") or "",
        rec.get("neutral_citation") or "",
        rec.get("precedential_status") or "",
        rec.get("summary") or "",
    ]
    return " | ".join([b for b in bits if b])

if __name__ == "__main__":
    model = SentenceTransformer(MODEL_NAME)
    items = []
    for rec, stem in load_records():
        items.append({
            "id": rec["id"],
            "court_path": rec["court_path"],
            "date_filed": rec.get("date_filed"),
            "case_name": rec.get("case_name"),
            "docket": rec.get("docket"),
            "neutral_citation": rec.get("neutral_citation"),
            "precedential_status": rec.get("precedential_status"),
            "download_url": rec.get("download_url"),
            "source_url": rec.get("source_url"),
            "summary": rec.get("summary"),
            "_embed_text": text_for_embedding(rec),
        })

    # Compute embeddings
    texts = [it["_embed_text"] for it in items]
    vecs = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

    # Shard
    shards = []
    for i in range(0, len(items), SHARD_SIZE):
        shard_id = f"shard_{i//SHARD_SIZE:04d}"
        part = items[i:i+SHARD_SIZE]
        embs = vecs[i:i+SHARD_SIZE]
        shard = {
            "shard_id": shard_id,
            "model": MODEL_NAME,
            "dim": DIM,
            "count": len(part),
            "items": [
                {
                    "id": it["id"],
                    "court_path": it["court_path"],
                    "date_filed": it["date_filed"],
                    "case_name": it["case_name"],
                    "docket": it["docket"],
                    "neutral_citation": it["neutral_citation"],
                    "precedential_status": it["precedential_status"],
                    "download_url": it["download_url"],
                    "source_url": it["source_url"],
                    "summary": it["summary"],
                    "embedding": emb.tolist(),
                }
                for it, emb in zip(part, embs)
            ],
        }
        with (IDX / f"{shard_id}.json").open("w") as f:
            json.dump(shard, f)
        shards.append(shard_id)

    manifest = {
        "model": MODEL_NAME,
        "dim": DIM,
        "total": len(items),
        "shards": shards,
    }
    with (IDX / "manifest.json").open("w") as f:
        json.dump(manifest, f)

    print(f"Indexed {len(items)} items into {len(shards)} shards.")
