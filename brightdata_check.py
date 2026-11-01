"""Daily accurate price check for the Japan 2027 trip using Bright Data's SERP API (Google Hotels).

Official paid-for API with a free monthly allowance; no scraping of Booking.com. Runs on
GitHub Actions with the key stored as the repository secret BRIGHTDATA_KEY (and the zone
name as BRIGHTDATA_ZONE, default "serp_api1"); neither is written to any file.

For every one of the 21 hotel options, every day, it asks Google Hotels for the exact stay
and party (2 adults + 1 child aged 10, GBP) twice: free-cancellation offers only, and all
offers. That is 42 requests a day (about 1,300 a month, inside the free 5,000).

It needs each hotel's Google id, which serpapi_check.py saves in data/serpapi_tokens.json.
Writes data/brightdata_latest.json (today's results) and data/brightdata_sample.json (one
trimmed response, so the parsing can be checked) and appends priced rows to
data/brightdata_prices.jsonl. Never estimates: a hotel with no price is saved with a status.
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

from serpapi_check import HOTELS, TOKENS_FILE

API = "https://api.brightdata.com/request"
SITE = "Booking.com via Google Hotels (Bright Data)"
NAME_KEYS = ("source", "name", "provider", "vendor", "seller", "title", "site")
PRICE_KEYS = ("total_price", "price_total", "total", "extracted_total_price", "price", "extracted_price", "rate", "price_per_night", "nightly_price")


def to_number(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"([\d,]+(?:\.\d+)?)", v.replace("\u00a0", " "))
        if m and ("£" in v or "GBP" in v or re.fullmatch(r"[\d,.\s]+", v.strip())):
            return float(m.group(1).replace(",", ""))
    return None


def offers_in(data):
    """Find every (site name, price fields) pair anywhere in the parsed Google Hotels JSON."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            name = next((o[k] for k in NAME_KEYS if isinstance(o.get(k), str) and o.get(k).strip()), None)
            prices = {k: to_number(o.get(k)) for k in PRICE_KEYS if to_number(o.get(k)) is not None}
            if name and prices:
                found.append({"site": name.strip(), "prices": prices, "keys": sorted(o.keys())[:25]})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return found


def stay_price(offer, nights):
    p = offer["prices"]
    for k in ("total_price", "price_total", "total", "extracted_total_price"):
        if k in p:
            return p[k], "total"
    for k in ("price_per_night", "nightly_price"):
        if k in p:
            return round(p[k] * nights, 2), "nightly x nights"
    for k in ("price", "extracted_price", "rate"):
        if k in p:
            return p[k], f"'{k}' (total or nightly not yet confirmed)"
    return None, None


def fetch(key, zone, name, token, ci, co, free_only):
    url = (f"https://www.google.com/travel/hotels/{quote(name)}/entity/{token}/prices"
           f"?brd_dates={ci}%2C{co}&brd_occupancy=2%2C10&brd_currency=GBP"
           f"&brd_free_cancellation={'true' if free_only else 'false'}&brd_json=1&gl=uk&hl=en")
    r = requests.post(API, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"zone": zone, "url": url, "format": "raw"}, timeout=120)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return {"_raw_text_start": r.text[:300]}


def best(offers, nights, booking_only):
    rows = []
    for o in offers:
        if booking_only and o["site"].strip().lower() != "booking.com":
            continue
        total, how = stay_price(o, nights)
        if total is not None:
            rows.append({"site": o["site"], "total": total, "how": how})
    return min(rows, key=lambda r: r["total"]) if rows else None


def main():
    key = os.environ.get("BRIGHTDATA_KEY")
    zone = os.environ.get("BRIGHTDATA_ZONE") or "serp_api1"
    if not key:
        raise SystemExit("BRIGHTDATA_KEY secret is missing")
    today = datetime.now(ZoneInfo("Europe/London")).date().isoformat()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tokens = json.load(open(TOKENS_FILE)) if os.path.exists(TOKENS_FILE) else {}
    results, sample = [], None
    for oid, name, ci, co, nights in HOTELS:
        row = {"date": today, "option_id": oid, "site": SITE, "checked_at": now}
        token = tokens.get(name)
        if not token:
            row["status"] = "waiting for Google hotel id (run the SerpApi check once by hand)"
            results.append(row)
            continue
        try:
            free_data = fetch(key, zone, name, token, ci, co, True)
            any_data = fetch(key, zone, name, token, ci, co, False)
            if sample is None:
                sample = {"hotel": name, "top_level_keys": sorted(free_data.keys())[:40] if isinstance(free_data, dict) else str(type(free_data)),
                          "offers_found": offers_in(free_data)[:8], "trimmed": json.dumps(free_data)[:6000]}
            free_offers, any_offers = offers_in(free_data), offers_in(any_data)
            b_free, b_any = best(free_offers, nights, True), best(any_offers, nights, True)
            c_free = best(free_offers, nights, False)
            row.update({
                "price_gbp": b_free["total"] if b_free else None,          # Booking.com, free cancellation
                "price_any_gbp": b_any["total"] if b_any else None,        # Booking.com, any terms
                "cheapest_site": c_free["site"] if c_free else None,       # any site, free cancellation
                "cheapest_stay_gbp": c_free["total"] if c_free else None,
                "price_basis": (b_free or b_any or c_free or {}).get("how"),
                "offers_seen": len(any_offers),
                "status": "ok" if b_free else ("Booking.com non-refundable only" if b_any else ("no Booking.com offer" if any_offers else "no offers found")),
            })
        except Exception as e:  # error text never includes the key
            row["status"] = f"error: {type(e).__name__}: {str(e).replace(key, '***')[:150]}"
        results.append(row)
        print(oid, row["status"], row.get("price_gbp"), row.get("price_any_gbp"))
        time.sleep(1)
    os.makedirs("data", exist_ok=True)
    json.dump({"date": today, "checked_at": now, "results": results}, open("data/brightdata_latest.json", "w"), indent=1)
    if sample:
        json.dump(sample, open("data/brightdata_sample.json", "w"), indent=1)
    with open("data/brightdata_prices.jsonl", "a") as f:
        for r in results:
            if r.get("price_gbp") is not None or r.get("price_any_gbp") is not None:
                f.write(json.dumps(r) + "\n")
    print(sum(1 for r in results if r.get("price_gbp") is not None), "of", len(results), "priced with free cancellation")


if __name__ == "__main__":
    main()
