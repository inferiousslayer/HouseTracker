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


def search_listings(page=1, max_retries=5):
    url = f"{API_BASE}/api/search/byurl"
    params = {"url": ZILLOW_SEARCH_URL, "page": str(page)}
    for attempt in range(max_retries):
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if resp.status_code == 429:
            wait = 2 ** attempt * 5  # 5s, 10s, 20s, 40s, 80s
            print(f"    Rate limited, waiting {wait}s (attempt {attempt+1}/{max_retries})...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()  # Raise if all retries exhausted


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

    price = prop.get("unformattedPrice") or 0
    if price > 550000:
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


###############################################################################
# AIRBNB INVESTMENT SCORING ALGORITHM
#
# Scores each listing 0-100 on short-term rental investment potential.
# Weighted factors (total = 100 points):
#
#   1. PRICE SWEET SPOT (25 pts)
#      Target: $300-500k. Peak score at $350-450k (best cash-on-cash).
#      Penalizes below 300k (likely condition issues) and above 500k (thin margins).
#
#   2. BEDROOM COUNT / GUEST CAPACITY (25 pts)
#      More bedrooms = more guests = higher nightly rate.
#      4 bd = good, 5 bd = great, 6+ bd = max. 3 bd = baseline.
#      Airbnb revenue scales ~$30-50/night per additional bedroom in metro ATL.
#
#   3. PRICE PER SQFT (15 pts)
#      Lower $/sqft = more space for the money = better value.
#      Scored relative to the cohort: best value in the dataset gets max points.
#
#   4. BATHROOM RATIO (10 pts)
#      Guests expect ~1 bath per 2 bedrooms minimum.
#      Ratio >= 0.75 bath/bed is ideal. Penalize low ratios (guest complaints).
#
#   5. SQUARE FOOTAGE BONUS (10 pts)
#      Larger homes support more amenities (game room, office, etc.).
#      Sweet spot: 3500-5000 sqft. Diminishing returns above 5000.
#
#   6. DAYS ON MARKET / NEGOTIATION LEVERAGE (10 pts)
#      Longer DOM = more seller motivation = better deal potential.
#      30+ days = good, 60+ = great, 90+ = max leverage.
#
#   7. MODERN / UPDATED SCORE (5 pts)
#      Modern/renovated homes photograph better, command higher nightly rates,
#      and require less upfront rehab before listing on Airbnb.
#
# ESTIMATED REVENUE MODEL (for context, shown on cards):
#   - Base nightly rate: $150 + ($25 * bedrooms beyond 3)
#   - Occupancy assumption: 65% (Atlanta metro avg for STR)
#   - Monthly gross = nightly_rate * 30 * 0.65
#   - Annual gross = monthly * 12
#   - Cash-on-cash proxy = annual_gross / price * 100
###############################################################################

AIRBNB_TARGET_MIN = 300000
AIRBNB_TARGET_MAX = 500000
AIRBNB_SWEET_MIN = 350000
AIRBNB_SWEET_MAX = 450000


def score_price_sweet_spot(price):
    """25 pts - Peak at 350-450k, taper outside 300-500k."""
    if not price:
        return 0
    if AIRBNB_SWEET_MIN <= price <= AIRBNB_SWEET_MAX:
        return 25
    if AIRBNB_TARGET_MIN <= price < AIRBNB_SWEET_MIN:
        return 15 + 10 * (price - AIRBNB_TARGET_MIN) / (AIRBNB_SWEET_MIN - AIRBNB_TARGET_MIN)
    if AIRBNB_SWEET_MAX < price <= AIRBNB_TARGET_MAX:
        return 15 + 10 * (AIRBNB_TARGET_MAX - price) / (AIRBNB_TARGET_MAX - AIRBNB_SWEET_MAX)
    if 250000 <= price < AIRBNB_TARGET_MIN:
        return 5
    if AIRBNB_TARGET_MAX < price <= 600000:
        return 5
    return 0


def score_bedrooms(beds):
    """25 pts - More bedrooms = more guests = more revenue."""
    scores = {3: 10, 4: 17, 5: 22, 6: 25}
    if beds >= 7:
        return 25
    return scores.get(int(beds), 5)


def score_price_per_sqft(ppsf, all_ppsf):
    """15 pts - Lower price/sqft = better value, scored relative to cohort."""
    if not ppsf or not all_ppsf:
        return 0
    best = min(all_ppsf)
    worst = max(all_ppsf)
    if best == worst:
        return 8
    # Invert: lower ppsf = higher score
    return round(15 * (worst - ppsf) / (worst - best), 1)


def score_bath_ratio(beds, baths):
    """10 pts - Ideal ratio >= 0.75 baths per bedroom."""
    if not beds:
        return 0
    ratio = baths / beds
    if ratio >= 1.0:
        return 10
    if ratio >= 0.75:
        return 8
    if ratio >= 0.5:
        return 5
    return 2


def score_sqft_bonus(sqft):
    """10 pts - Sweet spot 3500-5000 sqft."""
    if not sqft:
        return 0
    if 3500 <= sqft <= 5000:
        return 10
    if 3000 <= sqft < 3500:
        return 7
    if 5000 < sqft <= 6000:
        return 7
    return 4


def score_days_on_market(dom):
    """10 pts - Higher DOM = more negotiation leverage."""
    if dom is None or dom < 0:
        return 5  # Unknown, neutral
    if dom >= 90:
        return 10
    if dom >= 60:
        return 8
    if dom >= 30:
        return 6
    if dom >= 14:
        return 4
    return 2  # Fresh listing, less leverage


def score_modern(modern_score):
    """5 pts - Modern homes photograph better, higher nightly rate."""
    if modern_score >= 3:
        return 5
    if modern_score >= 1:
        return 3
    return 0


def estimate_airbnb_revenue(beds, price):
    """Estimate annual gross revenue and cash-on-cash return."""
    nightly = 150 + 25 * max(0, beds - 3)
    occupancy = 0.65
    monthly_gross = nightly * 30 * occupancy
    annual_gross = monthly_gross * 12
    cash_on_cash = (annual_gross / price * 100) if price else 0
    return {
        "nightlyRate": round(nightly),
        "monthlyGross": round(monthly_gross),
        "annualGross": round(annual_gross),
        "cashOnCash": round(cash_on_cash, 1),
    }


def compute_investment_scores(listings):
    """Score all listings and attach investmentScore + revenue estimates."""
    # Pre-compute price-per-sqft for the cohort
    ppsf_values = []
    for l in listings:
        if l["price"] and l["sqft"]:
            ppsf_values.append(l["price"] / l["sqft"])

    for l in listings:
        price = l["price"] or 0
        beds = l["bedrooms"] or 0
        baths = l["bathrooms"] or 0
        sqft = l["sqft"] or 0
        dom = l["daysOnMarket"]
        modern = l["modernScore"] or 0
        ppsf = (price / sqft) if sqft else 0

        s1 = score_price_sweet_spot(price)
        s2 = score_bedrooms(beds)
        s3 = score_price_per_sqft(ppsf, ppsf_values)
        s4 = score_bath_ratio(beds, baths)
        s5 = score_sqft_bonus(sqft)
        s6 = score_days_on_market(dom)
        s7 = score_modern(modern)

        total = round(s1 + s2 + s3 + s4 + s5 + s6 + s7, 1)

        l["investmentScore"] = total
        l["scoreBreakdown"] = {
            "priceSweet": round(s1, 1),
            "bedrooms": round(s2, 1),
            "valuePpSqft": round(s3, 1),
            "bathRatio": round(s4, 1),
            "sqftBonus": round(s5, 1),
            "domLeverage": round(s6, 1),
            "modern": round(s7, 1),
        }
        l["pricePerSqft"] = round(ppsf) if ppsf else None
        l["revenueEstimate"] = estimate_airbnb_revenue(beds, price) if price else None

    return listings


def fetch_and_export():
    if not RAPIDAPI_KEY:
        print("ERROR: Set RAPIDAPI_KEY in .env file")
        return

    print("Fetching listings for Norcross, GA area...")
    print("  Filters: Houses, >= 2500 sqft, <= $550k, No HOA, ~10mi radius")

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

    # Score all listings for Airbnb investment potential
    all_listings = compute_investment_scores(all_listings)

    # Compute stats
    prices = [l["price"] for l in all_listings if l["price"]]
    sqfts = [l["sqft"] for l in all_listings if l["sqft"]]

    # Airbnb picks: top listings in the 300-500k range
    airbnb_picks = [l for l in all_listings
                    if l["price"] and AIRBNB_TARGET_MIN <= l["price"] <= AIRBNB_TARGET_MAX]
    airbnb_picks.sort(key=lambda x: x["investmentScore"], reverse=True)

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
        "airbnbPicks": airbnb_picks[:20],
        "airbnbPickCount": len(airbnb_picks),
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Exported to {OUTPUT_FILE}")


if __name__ == "__main__":
    fetch_and_export()
