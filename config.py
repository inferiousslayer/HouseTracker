import os
import json
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "real-estate101.p.rapidapi.com"

# Search parameters
MIN_SQFT = 2500

# Norcross, GA coordinates
NORCROSS_LAT = 33.9412
NORCROSS_LNG = -84.2135

# Bounding box ~10 miles around Norcross
# 1 degree latitude ≈ 69 miles, 1 degree longitude ≈ 54.6 miles at this latitude
LAT_OFFSET = 10 / 69.0
LNG_OFFSET = 10 / 54.6

# Zillow search URL with filters baked in:
# - Houses only (no townhouses, condos, multi-family, land, apartments, manufactured)
# - Max 3000 sqft
# - No HOA
# - Norcross, GA region (regionId: 24062)
SEARCH_QUERY_STATE = {
    "isMapVisible": True,
    "mapBounds": {
        "north": NORCROSS_LAT + LAT_OFFSET,
        "south": NORCROSS_LAT - LAT_OFFSET,
        "east": NORCROSS_LNG + LNG_OFFSET,
        "west": NORCROSS_LNG - LNG_OFFSET,
    },
    "filterState": {
        "sort": {"value": "globalrelevanceex"},
        "ah": {"value": True},
        "sf": {"min": MIN_SQFT},
        "price": {"max": 550000},
        "tow": {"value": False},
        "mf": {"value": False},
        "con": {"value": False},
        "land": {"value": False},
        "apa": {"value": False},
        "manu": {"value": False},
        "nohoa": {"value": True},
    },
    "isListVisible": True,
    "usersSearchTerm": "Norcross, GA",
    "regionSelection": [{"regionId": 24062, "regionType": 6}],
}

ZILLOW_SEARCH_URL = (
    "https://www.zillow.com/norcross-ga/?searchQueryState="
    + urllib.parse.quote(json.dumps(SEARCH_QUERY_STATE))
)

# Keywords to identify "modern" style homes
MODERN_KEYWORDS = [
    "modern", "contemporary", "mid-century", "midcentury",
    "updated", "renovated", "remodeled", "new construction",
    "smart home", "open concept", "open floor plan",
    "minimalist", "sleek", "luxury", "upgraded",
]

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "listings.db")
