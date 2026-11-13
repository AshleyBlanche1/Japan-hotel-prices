"""Booking.com price check for the Japan 2027 trip, with no browser and no laptop.

Uses the JSON endpoint Booking.com's own search page calls (POST /dml/graphql, see
docs/booking-endpoints.md). It is a plain HTTPS request with an honest User-Agent: no
cookies (none are sent or kept, even within a run), no login, no challenge solving, no
proxies, no browser impersonation. If Booking.com answers with a challenge, the hotel and
every remaining one is recorded as "robot check", no further requests are made, and the
file is still written so the failure is visible.

Party: 2 adults + 1 child aged 10, 1 room, prices in GBP for the whole stay.

Usage
  python booking_check.py                   all 21 options, print results
  python booking_check.py --hotels 3        three test options only (Tokyo, Osaka, Kyoto)
  python booking_check.py --diagnose        also print the first 500 characters of every response
  python booking_check.py --write           write data/booking_latest.json (all 21 options only)
  python booking_check.py --out FILE        write results to FILE instead (any subset; for tests)

Every request is logged on one line: HTTP status, server/via/x-amzn-waf-action headers,
set-cookie names (never values), response length and whether the body was JSON.

Never estimates, converts or carries forward a price: a hotel with no readable price is
saved with null price fields and a status.
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from http.cookiejar import DefaultCookiePolicy
from zoneinfo import ZoneInfo

import requests

URL = "https://www.booking.com/dml/graphql?lang=en-gb&selected_currency=GBP"
SITE = "Booking.com"
SOURCE = "Booking.com check via {where} (2 adults, 1 child aged 10)"
USER_AGENT = "Japan-hotel-prices/1.0 (personal price tracker, 21 hotels once a day; +https://github.com/AshleyBlanche1/Japan-hotel-prices)"
IDS_FILE = "data/booking_hotel_ids.json"  # slug -> Booking.com hotel id (never changes, saves lookups)
LATEST = "data/booking_latest.json"
PARTY = {"nbAdults": 2, "nbChildren": 1, "childrenAges": [10], "nbRooms": 1}
PAUSE = (5, 10)  # seconds between requests
LONDON, TOKYO = ZoneInfo("Europe/London"), ZoneInfo("Asia/Tokyo")

# option_id, Booking.com slug, check-in, check-out
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
TEST_HOTELS = [HOTELS[1], HOTELS[7], HOTELS[14]]  # one each in Tokyo, Osaka, Kyoto

ID_QUERY = """query HotelId($input: RoomTableQueryInput!) {
  roomTable(input: $input) { ... on RoomTableQueryResult { hotelId propertyName } }
}"""

SEARCH_QUERY = """query HotelPrice($input: SearchQueryInput!) {
  searchQueries { search(input: $input) { ... on SearchQueryOutput { results {
    displayName { text }
    basicPropertyData { id pageName }
    policies { showFreeCancellation }
    soldOutInfo { isSoldOut }
    priceDisplayInfoIrene {
      chargesInfo { translation }
      displayPrice { amountPerStay { amountUnformatted currency } }
    }
    blocks { blockId { roomId occupancy } finalPrice { amount currency } freeCancellationUntil }
    matchingUnitConfigurations { unitConfigurations { name unitId } }
  } } } }
}"""
FREE_CANCELLATION = {"selectedFilters": "fc=2"}  # the website's "Free cancellation" filter (nflt=fc%3D2)

CHALLENGE_MARKERS = ("AwsWafIntegration", "challenge.js", "captcha", "challenge-platform", "px-captcha")
PRICED = ("ok", "non-refundable only")


class RobotCheck(Exception):
    pass


class Client:
    def __init__(self, diagnose=False):
        self.s = requests.Session()
        self.s.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))  # never store or send cookies
        self.s.headers.update({"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"})
        self.diagnose = diagnose
        self.calls = 0

    def _send(self, body, label):
        if self.calls:
            time.sleep(random.uniform(*PAUSE))
        self.calls += 1
        self.s.cookies.clear()  # belt and braces: never send a cookie
        try:
            r = self.s.post(URL, json=body, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as e:
            print(f"  [{label}] request {self.calls}: {type(e).__name__}: {str(e)[:150]}")
            raise
        log_response(label, r, self.calls, self.diagnose)
        return r

    def post(self, op, query, variables, label=None):
        """op must equal the operation name inside query; label is only for the log."""
        body = {"operationName": op, "query": query, "variables": variables}
        label = label or op
        try:
            r = self._send(body, label)
            retry = r.status_code >= 500 or r.status_code == 429
        except (requests.ConnectionError, requests.Timeout):
            retry = True
        if retry:  # one polite retry after a pause, then give up (a second failure raises)
            r = self._send(body, label + " retry")
        return classify(r)


def log_response(label, r, n, diagnose):
    """One line per request, as the rollout brief asks. Cookie values are never printed."""
    headers = {k: r.headers.get(k) for k in ("server", "via", "x-amzn-waf-action", "cf-mitigated", "x-amz-cf-pop")
               if r.headers.get(k)}
    cookies = sorted({c.name for c in r.cookies})
    text = r.text or ""
    print(f"  [{label}] request {n}: HTTP {r.status_code} length={len(r.content)} json={text.lstrip().startswith('{')} "
          f"headers={headers} set-cookie-names={cookies}")
    if diagnose:
        print(f"  [{label}] body[:500]={text[:500]!r}")


def classify(r):
    """Return the parsed JSON body, or raise RobotCheck / RuntimeError with what came back."""
    text = r.text or ""
    is_json = text.lstrip().startswith("{")
    if r.status_code == 202 or r.headers.get("x-amzn-waf-action") or (not is_json and any(m in text for m in CHALLENGE_MARKERS)):
        raise RobotCheck(f"HTTP {r.status_code}, {len(text)} bytes, waf={r.headers.get('x-amzn-waf-action')}")
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    if not is_json:
        raise RuntimeError(f"non-JSON body ({len(text)} bytes)")
    data = r.json()
    if data.get("errors"):
        raise RuntimeError("GraphQL: " + "; ".join(e.get("message", "")[:100] for e in data["errors"][:2]))
    return data


def hotel_id(client, slug, ci, co):
    data = client.post("HotelId", ID_QUERY, {"input": {
        "highlightedBlocks": [],
        "pagenameDetails": {"countryCode": "jp", "pagename": slug},
        "searchConfig": dict(PARTY, searchConfigDate={"checkin": ci, "checkout": co}),
    }})
    rt = (data.get("data") or {}).get("roomTable") or {}
    if not rt.get("hotelId"):
        raise RuntimeError(f"no hotel id for slug {slug}")
    return int(rt["hotelId"])


def search_input(hid, ci, co, filters=None):
    return dict(PARTY,
                location={"destType": "HOTEL", "destId": hid},
                dates={"checkin": ci, "checkout": co},
                pagination={"offset": 0, "rowsPerPage": 10},
                filters=filters or {},
                doAvailabilityCheck=False)


def last_free_cancellation_day(ts):
    """'2027-07-24T15:00:00Z' (= 25 Jul 00:00 in Japan; the website says 'before 25 July') -> '2027-07-24'."""
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (t.astimezone(TOKYO) - timedelta(seconds=1)).date().isoformat()
    except ValueError:
        return None


def offer(data, hid):
    """Booking's headline offer for our hotel (nearby hotels are listed after it).
    Returns (offer dict or None, status)."""
    results = (((data.get("data") or {}).get("searchQueries") or {}).get("search") or {}).get("results") or []
    me = next((x for x in results if (x.get("basicPropertyData") or {}).get("id") == hid), None)
    if me is None:
        return None, "error: hotel not in search results"
    if (me.get("soldOutInfo") or {}).get("isSoldOut"):
        return None, "sold out"
    pdi = me.get("priceDisplayInfoIrene") or {}
    stay = ((pdi.get("displayPrice") or {}).get("amountPerStay") or {})
    amount, currency = stay.get("amountUnformatted"), stay.get("currency")
    if not isinstance(amount, (int, float)) or amount <= 0:
        return None, "error: no rate for 2 adults + 1 child"
    if currency != "GBP":
        return None, f"error: price in {currency}, not GBP"
    charges = ((pdi.get("chargesInfo") or {}).get("translation") or "").lower()
    blocks = me.get("blocks") or []
    units = ((me.get("matchingUnitConfigurations") or {}).get("unitConfigurations") or [])
    names = {str(u.get("unitId")): u.get("name") for u in units if u.get("name")}
    room_ids = [str((b.get("blockId") or {}).get("roomId")) for b in blocks]
    room = next((names[r] for r in room_ids if r in names), None) or next(iter(names.values()), None)
    occupancy = [(b.get("blockId") or {}).get("occupancy") for b in blocks]
    return {
        "price": round(amount, 2),
        "refundable": bool((me.get("policies") or {}).get("showFreeCancellation")),
        # True only for "Includes taxes and charges"; False for "Additional charges may apply"
        "taxes_included": True if "includes taxes" in charges else (False if charges else None),
        "room": room,
        "free_cancellation_until": last_free_cancellation_day(
            next((b.get("freeCancellationUntil") for b in blocks if b.get("freeCancellationUntil")), None)),
        # blockId.occupancy is unreliable: JW Marriott's 2 adults + 1 child room shows 2, Hilton's
        # family room 3, Prince hotels 0 (not given). The search already matches rooms to the party
        # ("Recommended for your group"), so only reject a rate explicitly for one guest.
        "fits_party": False if any(o == 1 for o in occupancy) else True,
    }, "ok"


EMPTY = {"price_gbp": None, "price_any_gbp": None, "genius_gbp": None, "before_discount_gbp": None,
         "price_jpy": None, "room": None, "taxes_included": None, "refundable": False,
         "free_cancellation_until": None}


def combine(any_offer, any_status, fc_offer=None, fc_status=None):
    """Build the result fields from the unfiltered search and, if needed, the free-cancellation one."""
    if any_offer is None:
        return dict(EMPTY, status=any_status)
    if any_offer["fits_party"] is False:
        return dict(EMPTY, status="error: no rate for 2 adults + 1 child")
    out = dict(EMPTY, price_any_gbp=any_offer["price"], room=any_offer["room"],
               taxes_included=any_offer["taxes_included"])
    if any_offer["refundable"]:
        return dict(out, price_gbp=any_offer["price"], refundable=True,
                    free_cancellation_until=any_offer["free_cancellation_until"], status="ok")
    # The cheapest rate is non-refundable: use the free-cancellation search for price_gbp.
    if fc_offer is not None and fc_offer["refundable"] and fc_offer["fits_party"] is not False:
        return dict(out, price_gbp=fc_offer["price"], room=fc_offer["room"],
                    taxes_included=fc_offer["taxes_included"], refundable=True,
                    free_cancellation_until=fc_offer["free_cancellation_until"], status="ok")
    # fc_status "failed: ..." = the request itself failed. Any other outcome (no rate, or the hotel
    # dropped out of the filtered results) means Booking has no free-cancellation rate for the party.
    if fc_status and fc_status.startswith("failed: "):
        return dict(out, status=f"error: free-cancellation search failed ({fc_status[8:][:80]})")
    return dict(out, status="non-refundable only")


def check(client, slug, ci, co, ids):
    hid = ids.get(slug)
    if hid is None:
        hid = ids[slug] = hotel_id(client, slug, ci, co)
    any_offer, any_status = offer(client.post("HotelPrice", SEARCH_QUERY, {"input": search_input(hid, ci, co)}), hid)
    fc_offer = fc_status = None
    if any_offer is not None and not any_offer["refundable"]:
        try:
            fc_offer, fc_status = offer(client.post("HotelPrice", SEARCH_QUERY,
                                                    {"input": search_input(hid, ci, co, FREE_CANCELLATION)},
                                                    label="HotelPrice fc=2"), hid)
        except RobotCheck:
            raise
        except Exception as e:
            fc_status = f"failed: {type(e).__name__}: {str(e)[:100]}"
    return combine(any_offer, any_status, fc_offer, fc_status)


def row(today, oid, checked_at, fields, where):
    r = {"date": today, "option_id": oid, "site": SITE, "checked_at": checked_at}
    r.update({k: fields[k] for k in ("price_gbp", "price_any_gbp", "genius_gbp", "before_discount_gbp", "price_jpy",
                                     "room", "taxes_included", "refundable", "free_cancellation_until")})
    r["refundable"] = r["price_gbp"] is not None
    r["source"] = SOURCE.format(where=where)
    r["status"] = fields["status"]
    return r


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(hotels, out_path, diagnose=False):
    """Check the hotels, merge with today's file at out_path (if any) and return the document."""
    on_github = os.environ.get("GITHUB_ACTIONS") == "true"
    runner, where = ("github-actions", "GitHub") if on_github else ("mac", "Mac")
    today = datetime.now(LONDON).date().isoformat()

    previous = {}
    if out_path and os.path.exists(out_path):
        prev = json.load(open(out_path))
        if prev.get("date") == today:  # never carry yesterday's prices into a file dated today
            previous = {r["option_id"]: r for r in prev.get("results", [])}
    if any(r.get("status") == "robot check" for r in previous.values()):
        print("Booking.com showed a robot check earlier today; not asking again until tomorrow.")
        return None

    ids = json.load(open(IDS_FILE)) if os.path.exists(IDS_FILE) else {}
    client = Client(diagnose=diagnose)
    results, blocked = [], False
    for oid, slug, ci, co in hotels:
        kept = previous.get(oid)
        if kept and kept.get("status") in PRICED:
            print(f"{oid}: already priced today ({kept['checked_at']}), kept")
            results.append(kept)
            continue
        print(f"{oid} ({slug}, {ci} to {co})")
        if blocked:  # once challenged, stop asking: that is the answer
            fields = dict(EMPTY, status="robot check")
        else:
            try:
                fields = check(client, slug, ci, co, ids)
            except RobotCheck as e:
                blocked = True
                print(f"  robot check: {e}")
                fields = dict(EMPTY, status="robot check")
            except Exception as e:
                fields = dict(EMPTY, status=f"error: {type(e).__name__}: {str(e)[:100]}")
        r = row(today, oid, utc_now(), fields, where)
        results.append(r)
        print(f"  -> {r['status']}  price_gbp={r['price_gbp']}  price_any_gbp={r['price_any_gbp']}  "
              f"room={r['room']!r}  taxes_included={r['taxes_included']}  fc_until={r['free_cancellation_until']}")

    json.dump(ids, open(IDS_FILE, "w"), indent=1, sort_keys=True)
    priced = sum(1 for r in results if r["status"] in PRICED)
    print(f"{priced} of {len(results)} priced; {client.calls} requests; runner={runner}")
    return {"date": today, "checked_at": utc_now(), "runner": runner, "results": results}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hotels", type=int, choices=[1, 2, 3], help="check only this many test options")
    ap.add_argument("--diagnose", action="store_true")
    ap.add_argument("--write", action="store_true", help=f"write {LATEST} (all 21 options)")
    ap.add_argument("--out", help="write results to this file instead")
    a = ap.parse_args(argv)
    if a.write and a.hotels:
        ap.error(f"--write produces {LATEST}, which must hold all 21 options; use --out for a subset")

    hotels = TEST_HOTELS[: a.hotels] if a.hotels else HOTELS
    out_path = a.out or (LATEST if a.write else None)
    doc = run(hotels, out_path, a.diagnose)
    if doc is not None and out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(doc, f, indent=1)
            f.write("\n")
        print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
