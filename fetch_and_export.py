"""
Fetches property listings from the Real Estate 101 API (via RapidAPI) for Norcross, GA.
Exports results to public/listings.json for the static site.

Filters (applied via Zillow search URL):
  - Houses only
  - >= 3000 sqft
  - No HOA
  - ~10 mile radius around Norcross, GA
"""

import json
import os
import time
from datetime import datetime, timezone

import requests
from config import (
    RAPIDAPI_KEY, RAPIDAPI_HOST,
    ZILLOW_SEARCH_URL, MIN_SQFT,
    MODERN_KEYWORDS,
)


API_BASE = f"https://{RAPIDAPI_HOST}"
HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": RAPIDAPI_HOST,
    "Content-Type": "application/json",
}

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "public")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "listings.json")


def search_listings(page=1):
    url = f"{API_BASE}/api/search/byurl"
    params = {"url": ZILLOW_SEARCH_URL, "page": str(page)}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def compute_modern_score(description: str) -> int:
    if not description:
        return 0
    desc_lower = description.lower()
    return sum(1 for kw in MODERN_KEYWORDS if kw in desc_lower)


def process_result(prop: dict) -> dict | None:
    zpid = str(prop.get("id", ""))
    if not zpid:
        return None

    sqft = prop.get("livingArea") or prop.get("area") or 0
    if sqft < MIN_SQFT:
        return None

    addr = prop.get("address", {})
    coords = prop.get("latLong", {})
    description = prop.get("description") or ""

    return {
        "zpid": zpid,
        "address": addr.get("street", ""),
        "city": addr.get("city", ""),
        "state": addr.get("state", ""),
        "zipcode": addr.get("zipcode", ""),
        "price": prop.get("unformattedPrice") or 0,
        "sqft": sqft,
        "bedrooms": prop.get("beds") or 0,
        "bathrooms": prop.get("baths") or 0,
        "yearBuilt": prop.get("yearBuilt"),
        "homeType": prop.get("homeType", ""),
        "listingStatus": prop.get("homeStatus") or prop.get("statusText", ""),
        "imageUrl": prop.get("imgSrc", ""),
        "listingUrl": prop.get("detailUrl") or f"https://www.zillow.com/homedetails/{zpid}_zpid/",
        "latitude": coords.get("latitude"),
        "longitude": coords.get("longitude"),
        "daysOnMarket": prop.get("daysOnZillow") or 0,
        "modernScore": compute_modern_score(description),
        "zestimate": prop.get("zestimate"),
    }


def fetch_and_export():
    if not RAPIDAPI_KEY:
        print("ERROR: Set RAPIDAPI_KEY in .env file")
        return

    print("Fetching listings for Norcross, GA area...")
    print("  Filters: Houses, >= 3000 sqft, No HOA, ~10mi radius")

    all_listings = []
    seen_ids = set()

    for page in range(1, 20):
        print(f"  Page {page}...")
        try:
            data = search_listings(page)
        except requests.RequestException as e:
            print(f"  Error on page {page}: {e}")
            break

        results = data.get("results") or []
        if not results:
            break

        new_count = 0
        for prop in results:
            record = process_result(prop)
            if record and record["zpid"] not in seen_ids:
                seen_ids.add(record["zpid"])
                all_listings.append(record)
                new_count += 1

        if new_count == 0:
            break
        time.sleep(1)

    print(f"  Found {len(all_listings)} listings.")

    # Compute stats
    prices = [l["price"] for l in all_listings if l["price"]]
    sqfts = [l["sqft"] for l in all_listings if l["sqft"]]

    output = {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "count": len(all_listings),
        "stats": {
            "avgPrice": round(sum(prices) / len(prices)) if prices else 0,
            "minPrice": min(prices) if prices else 0,
            "maxPrice": max(prices) if prices else 0,
            "avgSqft": round(sum(sqfts) / len(sqfts)) if sqfts else 0,
        },
        "listings": all_listings,
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Exported to {OUTPUT_FILE}")


if __name__ == "__main__":
    fetch_and_export()
