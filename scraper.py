"""Daily Booking.com price scraper for the Japan 2027 trip (requests + BeautifulSoup).

Runs on GitHub Actions. For each hotel option it loads the Booking.com hotel page for
the exact stay and party (2 adults + 1 child aged 10, GBP), parses the room table with
BeautifulSoup, and records the cheapest free-cancellation price for a room that fits.
Results are appended to data/prices.jsonl and written to data/latest.json.
It never estimates: a hotel whose page is blocked or unreadable is saved with a status
and no price.
"""
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

HOTELS = [
    ("tokyo-1-1-hotel-tokyo", "1-tokyo", "2027-08-08", "2027-08-12"),
    ("tokyo-1-jw-marriott-hotel-tokyo", "jw-marriott-tokyo", "2027-08-08", "2027-08-12"),
    ("tokyo-1-hotel-toranomon-hills", "toranomon-hills-the-unbound-collection-by-hyatt", "2027-08-08", "2027-08-12"),
    ("tokyo-1-the-prince-sakura-tower-tokyo", "the-prince-sakura-tower-tokyo", "2027-08-08", "2027-08-12"),
    ("tokyo-1-ana-intercontinental-tokyo", "ana-intercontinental-tokyo", "2027-08-08", "2027-08-12"),
    ("tokyo-1-the-prince-park-tower-tokyo", "the-prince-park-tower-tokyo", "2027-08-08", "2027-08-12"),
    ("tokyo-1-grand-prince-hotel-shin-takanawa", "grand-prince-shin-takanawa", "2027-08-08", "2027-08-12"),
    ("osaka-the-osaka-station-hotel", "osaka-autograph-collection", "2027-08-12", "2027-08-17"),
    ("osaka-the-gate-hotel-osaka-by-hulic", "the-gate-osaka-by-hulic", "2027-08-12", "2027-08-17"),
    ("osaka-rihga-royal-hotel-osaka", "rihga-royal-osaka", "2027-08-12", "2027-08-17"),
    ("osaka-the-royal-park-hotel-iconic-osaka-midosuji", "the-royal-park-hotel-iconic-osaka-midosuji", "2027-08-12", "2027-08-17"),
    ("kyoto-dusit-thani-kyoto", "dusit-thani-kyoto", "2027-08-17", "2027-08-19"),
    ("kyoto-hotel-the-celestine-kyoto-gion", "the-celestine-kyoto-gion", "2027-08-17", "2027-08-19"),
    ("kyoto-the-thousand-kyoto", "the-thousand-kyoto", "2027-08-17", "2027-08-19"),
    ("kyoto-hilton-kyoto", "hilton-kyoto", "2027-08-17", "2027-08-19"),
    ("tokyo-2-jw-marriott-hotel-tokyo", "jw-marriott-tokyo", "2027-08-19", "2027-08-21"),
    ("tokyo-2-gajoen-tokyo", "gajoen-tokyo", "2027-08-19", "2027-08-21"),
    ("tokyo-2-the-prince-sakura-tower-tokyo", "the-prince-sakura-tower-tokyo", "2027-08-19", "2027-08-21"),
    ("tokyo-2-grand-prince-hotel-takanawa", "grand-prince-takanawa", "2027-08-19", "2027-08-21"),
    ("tokyo-2-intercontinental-tokyo-bay", "intercontinental-tokyo-bay", "2027-08-19", "2027-08-21"),
    ("tokyo-2-grand-prince-hotel-shin-takanawa", "grand-prince-shin-takanawa", "2027-08-19", "2027-08-21"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def sq(s):
    return re.sub(r"\s+", " ", s or "").strip()


def url_for(slug, ci, co):
    return (
        f"https://www.booking.com/hotel/jp/{slug}.en-gb.html?checkin={ci}&checkout={co}"
        "&group_adults=2&req_adults=2&no_rooms=1&group_children=1&req_children=1"
        "&age=10&req_age=10&selected_currency=GBP&lang=en-gb"
    )


def parse(html):
    """Return the result dict for one hotel page, or a status if it can't be read."""
    if re.search(r"captcha|challenge-platform|px-captcha", html, re.I) and "hprt-table" not in html:
        return {"status": "robot check"}
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("#hprt-table tbody tr")
    if not rows:
        return {"status": "no room table"}
    room, max_a, max_c, sleeps = "", None, 0, None
    offers = []
    for tr in rows:
        rt = tr.select_one(".hprt-table-cell-roomtype")
        if rt:
            link = rt.select_one(".hprt-roomtype-icon-link, a.hprt-roomtype-link") or rt
            room = re.sub(r"^Genius rewards.*?discount\s*", "", sq(link.get_text(" ")), flags=re.I)[:70]
            sleeps = re.search(r"Sleeps:\s*(\d+) adults?(?:\s*,\s*(\d+) child)?", sq(rt.get_text(" ")))
        oc = tr.select_one(".hprt-table-cell-occupancy")
        if oc:
            t = oc.get_text(" ")
            a = re.search(r"Max adults:\s*(\d+)", t)
            c = re.search(r"Max children:\s*(\d+)", t)
            p = re.search(r"Max(?:imum)?\s*(?:people|persons|guests|occupancy):\s*(\d+)", t, re.I)
            max_a = int(a.group(1)) if a else (int(p.group(1)) if p else None)
            max_c = int(c.group(1)) if c else 0
        cond = tr.select_one(".hprt-table-cell-conditions")
        pr = tr.select_one(".hprt-table-cell-price")
        if not cond or not pr:
            continue
        ct, pt = sq(cond.get_text(" ")), sq(pr.get_text(" "))
        m = re.search(r"£([\d,]+)", pt)
        if not m:
            continue
        g = re.search(r"Guests:\s*(\d+) adults?(?:\s*,\s*(\d+) child)?", ct)
        if g:
            fits = int(g.group(1)) == 2 and int(g.group(2) or 0) == 1
        elif max_a is not None:
            fits = (max_a >= 2 and max_c >= 1) or max_a >= 3
        elif sleeps:
            n_a, n_c = int(sleeps.group(1)), int(sleeps.group(2) or 0)
            fits = (n_a >= 2 and n_c >= 1) or n_a >= 3
        else:
            fits = False
        offers.append({
            "fits": fits,
            "price": int(m.group(1).replace(",", "")),
            "free": bool(re.search(r"Free cancellation", ct, re.I)),
            "taxes": bool(re.search(r"Includes taxes", pt, re.I)),
            "room": room,
        })
    ours = [o for o in offers if o["fits"]]
    free = [o for o in ours if o["free"]]
    best_any = min(ours, key=lambda o: o["price"]) if ours else None
    best_free = min(free, key=lambda o: o["price"]) if free else None
    best = best_free or best_any
    if not ours:
        status = "no rate for 2 adults + 1 child" if offers else "sold out"
    else:
        status = "ok" if best_free else "non-refundable only"
    return {
        "price_gbp": best_free["price"] if best_free else None,
        "price_any_gbp": best_any["price"] if best_any else None,
        "room": best["room"] if best else None,
        "taxes_included": best["taxes"] if best else None,
        "status": status,
    }


def fetch(url, session):
    proxy = os.environ.get("PROXY_URL")  # optional, e.g. a residential proxy later
    proxies = {"http": proxy, "https": proxy} if proxy else None
    r = session.get(url, headers=HEADERS, timeout=45, proxies=proxies)
    r.raise_for_status()
    return r.text


def main():
    today = datetime.now(ZoneInfo("Europe/London")).date().isoformat()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session = requests.Session()
    try:
        session.get("https://www.booking.com/index.en-gb.html", headers=HEADERS, timeout=30)
    except requests.RequestException:
        pass
    results = []
    for oid, slug, ci, co in HOTELS:
        res = {"status": "error"}
        for attempt in range(2):
            try:
                res = parse(fetch(url_for(slug, ci, co), session))
            except Exception as e:  # network error, HTTP error, timeout
                res = {"status": f"error: {type(e).__name__}"}
            if res.get("price_gbp") is not None or res.get("price_any_gbp") is not None or res["status"] == "robot check":
                break
            time.sleep(5)
        row = {"date": today, "option_id": oid, "site": "Booking.com (GitHub scraper)", "checked_at": now}
        row.update(res)
        results.append(row)
        print(oid, res["status"], res.get("price_gbp"))
        time.sleep(random.uniform(2, 5))
    os.makedirs("data", exist_ok=True)
    with open("data/latest.json", "w") as f:
        json.dump({"date": today, "checked_at": now, "results": results}, f, indent=1)
    with open("data/prices.jsonl", "a") as f:
        for r in results:
            if r.get("price_gbp") is not None or r.get("price_any_gbp") is not None:
                f.write(json.dumps(r) + "\n")
    ok = sum(1 for r in results if r.get("price_gbp") is not None or r.get("price_any_gbp") is not None)
    print(f"{ok} of {len(results)} hotels priced")


if __name__ == "__main__":
    main()
