"""Daily accurate price check for the Japan 2027 trip using SerpApi's Google Hotels API.

Official API, no scraping. Runs on GitHub Actions with the key stored as the repository
secret SERPAPI_KEY (never written to any file). Checks all 21 hotel options together
every third day (about 210 searches a month, inside SerpApi's free 250), and every time
the workflow is started by hand from the Actions tab. Party: 2 adults + 1 child aged 10, prices in GBP.

Writes data/serpapi_latest.json (today's results) and appends priced rows to
data/serpapi_prices.jsonl. Never estimates: a hotel with no price is saved with a status.
"""
import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

API = "https://serpapi.com/search.json"
SITE = "Booking.com via Google Hotels"

# option_id, search name, check-in, check-out, nights
HOTELS = [
    ("tokyo-1-1-hotel-tokyo", "1 Hotel Tokyo", "2027-08-08", "2027-08-12", 4),
    ("tokyo-1-jw-marriott-hotel-tokyo", "JW Marriott Hotel Tokyo", "2027-08-08", "2027-08-12", 4),
    ("tokyo-1-hotel-toranomon-hills", "Hotel Toranomon Hills Tokyo", "2027-08-08", "2027-08-12", 4),
    ("tokyo-1-the-prince-sakura-tower-tokyo", "The Prince Sakura Tower Tokyo", "2027-08-08", "2027-08-12", 4),
    ("tokyo-1-ana-intercontinental-tokyo", "ANA InterContinental Tokyo", "2027-08-08", "2027-08-12", 4),
    ("tokyo-1-the-prince-park-tower-tokyo", "The Prince Park Tower Tokyo", "2027-08-08", "2027-08-12", 4),
    ("tokyo-1-grand-prince-hotel-shin-takanawa", "Grand Prince Hotel Shin Takanawa Tokyo", "2027-08-08", "2027-08-12", 4),
    ("osaka-the-osaka-station-hotel", "The Osaka Station Hotel Autograph Collection", "2027-08-12", "2027-08-17", 5),
    ("osaka-the-gate-hotel-osaka-by-hulic", "The Gate Hotel Osaka by Hulic", "2027-08-12", "2027-08-17", 5),
    ("osaka-rihga-royal-hotel-osaka", "RIHGA Royal Hotel Osaka", "2027-08-12", "2027-08-17", 5),
    ("osaka-the-royal-park-hotel-iconic-osaka-midosuji", "The Royal Park Hotel Iconic Osaka Midosuji", "2027-08-12", "2027-08-17", 5),
    ("kyoto-dusit-thani-kyoto", "Dusit Thani Kyoto", "2027-08-17", "2027-08-19", 2),
    ("kyoto-hotel-the-celestine-kyoto-gion", "Hotel The Celestine Kyoto Gion", "2027-08-17", "2027-08-19", 2),
    ("kyoto-the-thousand-kyoto", "The Thousand Kyoto", "2027-08-17", "2027-08-19", 2),
    ("kyoto-hilton-kyoto", "Hilton Kyoto", "2027-08-17", "2027-08-19", 2),
    ("tokyo-2-jw-marriott-hotel-tokyo", "JW Marriott Hotel Tokyo", "2027-08-19", "2027-08-21", 2),
    ("tokyo-2-gajoen-tokyo", "Hotel Gajoen Tokyo", "2027-08-19", "2027-08-21", 2),
    ("tokyo-2-the-prince-sakura-tower-tokyo", "The Prince Sakura Tower Tokyo", "2027-08-19", "2027-08-21", 2),
    ("tokyo-2-grand-prince-hotel-takanawa", "Grand Prince Hotel Takanawa Tokyo", "2027-08-19", "2027-08-21", 2),
    ("tokyo-2-intercontinental-tokyo-bay", "InterContinental Tokyo Bay", "2027-08-19", "2027-08-21", 2),
    ("tokyo-2-grand-prince-hotel-shin-takanawa", "Grand Prince Hotel Shin Takanawa Tokyo", "2027-08-19", "2027-08-21", 2),
]

TOKENS_FILE = "data/serpapi_tokens.json"  # remembers each hotel's Google property id, saving searches


def words(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower())) - {"hotel", "the", "tokyo", "osaka", "kyoto", "by", "collection"}


def same_hotel(wanted, found):
    w, f = words(wanted), words(found)
    return bool(w) and len(w & f) / len(w) >= 0.6


def num(v):
    return v if isinstance(v, (int, float)) else None


def extract(detail, nights):
    """Prices from one Google Hotels property: Booking.com's stay price and the cheapest site."""
    offers = []
    for item in (detail.get("featured_prices") or []) + (detail.get("prices") or []):
        nightly = num((item.get("rate_per_night") or {}).get("extracted_lowest"))
        total = num((item.get("total_rate") or {}).get("extracted_lowest"))
        if total is None and nightly is not None:
            total = round(nightly * nights, 2)
        if total is not None and item.get("source"):
            offers.append({"site": item["source"], "nightly": nightly, "total": total})
    booking = [o for o in offers if o["site"].strip().lower() == "booking.com"]
    b = min(booking, key=lambda o: o["total"]) if booking else None
    c = min(offers, key=lambda o: o["total"]) if offers else None
    return {
        "price_gbp": b["total"] if b else None,
        "nightly_gbp": b["nightly"] if b else None,
        "cheapest_site": c["site"] if c else None,
        "cheapest_stay_gbp": c["total"] if c else None,
        "status": "ok" if b else ("no Booking.com price" if offers else "no prices"),
    }


def search(params):
    r = requests.get(API, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data


def check(key, name, ci, co, nights, tokens):
    base = {"engine": "google_hotels", "check_in_date": ci, "check_out_date": co, "adults": 2, "children": 1,
            "children_ages": "10", "currency": "GBP", "gl": "uk", "hl": "en", "api_key": key}
    token = tokens.get(name)
    if token:
        detail = search(dict(base, property_token=token))
    else:
        data = search(dict(base, q=name))
        if data.get("prices") or data.get("featured_prices") or data.get("type") == "hotel":
            detail = data  # Google went straight to the hotel's own page
        else:
            match = next((p for p in data.get("properties", []) if same_hotel(name, p.get("name"))), None)
            if not match or not match.get("property_token"):
                return {"status": "hotel not found in Google Hotels"}
            tokens[name] = match["property_token"]
            detail = search(dict(base, property_token=match["property_token"]))
        if detail.get("property_token"):
            tokens[name] = detail["property_token"]
    if detail.get("name") and not same_hotel(name, detail["name"]):
        return {"status": f"different hotel returned: {detail['name'][:60]}"}
    return extract(detail, nights)


def main():
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        raise SystemExit("SERPAPI_KEY secret is missing")
    today = datetime.now(ZoneInfo("Europe/London")).date()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # All 21 hotels together. Scheduled runs check every third day (about 210 searches a
    # month, inside the free 250); a run started by hand from the Actions tab always checks.
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if not manual and today.toordinal() % 3 != 0:
        print("Not a check day (every third day); nothing to do. Next check in", 3 - today.toordinal() % 3, "day(s).")
        return
    todays = HOTELS
    if manual and os.path.exists("data/serpapi_latest.json"):
        prev = json.load(open("data/serpapi_latest.json"))
        if prev.get("date") == today.isoformat() and sum(1 for r in prev.get("results", []) if r.get("price_gbp") is not None) >= len(HOTELS):
            print("All hotels already checked today; skipping to save free searches.")
            return
    os.makedirs("data", exist_ok=True)
    tokens = json.load(open(TOKENS_FILE)) if os.path.exists(TOKENS_FILE) else {}
    results = []
    for oid, name, ci, co, nights in todays:
        try:
            res = check(key, name, ci, co, nights, tokens)
        except Exception as e:  # error text never includes the key
            res = {"status": f"error: {type(e).__name__}: {str(e).replace(key, '***')[:120]}"}
        row = {"date": today.isoformat(), "option_id": oid, "site": SITE, "checked_at": now}
        row.update(res)
        results.append(row)
        print(oid, row["status"], row.get("price_gbp"))
    json.dump(tokens, open(TOKENS_FILE, "w"), indent=1)
    json.dump({"date": today.isoformat(), "checked_at": now, "results": results}, open("data/serpapi_latest.json", "w"), indent=1)
    with open("data/serpapi_prices.jsonl", "a") as f:
        for r in results:
            if r.get("price_gbp") is not None:
                f.write(json.dumps(r) + "\n")
    print(sum(1 for r in results if r.get("price_gbp") is not None), "of", len(results), "priced")


if __name__ == "__main__":
    main()
