"""Offline tests for booking_check.py (no network). Response shapes copied from what
Booking.com's /dml/graphql returned on 2026-11-13 (see docs/booking-endpoints.md)."""
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import booking_check as bc

JW, HILTON = 14630603, 12078874
FIELDS = ["date", "option_id", "site", "checked_at", "price_gbp", "price_any_gbp", "genius_gbp",
          "before_discount_gbp", "price_jpy", "room", "taxes_included", "refundable",
          "free_cancellation_until", "source", "status"]
STATUSES = ("ok", "non-refundable only", "sold out", "robot check")


def result(hid, amount, fc=True, charges="Includes taxes and charges", sold_out=False, currency="GBP",
           room="Family Twin Room", room_id=1207887415, occupancy=3, fc_until="2027-08-16T15:00:00Z"):
    return {"displayName": {"text": "x"}, "basicPropertyData": {"id": hid, "pageName": "x"},
            "policies": {"showFreeCancellation": fc}, "soldOutInfo": {"isSoldOut": sold_out},
            "priceDisplayInfoIrene": None if amount is None else {
                "chargesInfo": {"translation": charges},
                "displayPrice": {"amountPerStay": {"amountUnformatted": amount, "currency": currency}}},
            "blocks": [] if amount is None else [{"blockId": {"roomId": str(room_id), "occupancy": occupancy},
                                                  "finalPrice": {"amount": amount, "currency": currency},
                                                  "freeCancellationUntil": fc_until if fc else None}],
            "matchingUnitConfigurations": None if amount is None else
                {"unitConfigurations": [{"name": room, "unitId": room_id}]}}


def page(*results):
    return {"data": {"searchQueries": {"search": {"results": list(results)}}}}


def fields(any_page, hid, fc_page=None):
    a, s = bc.offer(any_page, hid)
    f, fs = bc.offer(fc_page, hid) if fc_page else (None, None)
    return bc.row("2026-11-14", "x", "t", bc.combine(a, s, f, fs), "GitHub")


class FakeResponse:
    def __init__(self, status, text, headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    def json(self):
        return json.loads(self.text)


def test_free_cancellation_cheapest():
    # Observed: JW Marriott 8-12 Aug, first result, nearby hotels after it
    r = fields(page(result(JW, 1804.24462787781, room="Urban Deluxe Twin", room_id=1463060301,
                           fc_until="2027-07-24T15:00:00Z"), result(1, 950.0)), JW)
    assert list(r) == FIELDS
    assert r["status"] == "ok" and r["price_gbp"] == r["price_any_gbp"] == 1804.24
    assert r["room"] == "Urban Deluxe Twin" and r["taxes_included"] is True and r["refundable"] is True
    assert r["free_cancellation_until"] == "2027-07-24"  # website: "Free cancellation before 25 July 2027"
    assert r["genius_gbp"] is None and r["before_discount_gbp"] is None and r["price_jpy"] is None
    assert r["source"] == "Booking.com check via GitHub (2 adults, 1 child aged 10)"
    # Our hotel not listed first: still picked by id
    assert fields(page(result(1, 500.0), result(JW, 1804.0)), JW)["price_any_gbp"] == 1804.0


def test_non_refundable_cheapest():
    # Observed: Hilton Kyoto 17-19 Aug, cheapest £423.21 non-refundable; with fc=2 filter £509.88
    cheap = page(result(HILTON, 423.21, fc=False, charges="Additional charges may apply", room="Twin Room", room_id=1))
    fc = page(result(HILTON, 509.88454016434866, charges="Additional charges may apply"))
    r = fields(cheap, HILTON, fc)
    assert r["status"] == "ok" and r["price_any_gbp"] == 423.21 and r["price_gbp"] == 509.88
    assert r["room"] == "Family Twin Room" and r["refundable"] is True and r["taxes_included"] is False
    assert r["free_cancellation_until"] == "2027-08-16"
    # No free-cancellation rate at all
    r = fields(cheap, HILTON, page(result(HILTON, None)))
    assert r["status"] == "non-refundable only" and r["price_gbp"] is None and r["price_any_gbp"] == 423.21
    assert r["refundable"] is False and r["free_cancellation_until"] is None
    # Hotel drops out of the free-cancellation results: also non-refundable only
    assert fields(cheap, HILTON, page(result(1, 300.0)))["status"] == "non-refundable only"
    # Free-cancellation request failed: say so, never guess
    a, s = bc.offer(cheap, HILTON)
    r = bc.row("d", "x", "t", bc.combine(a, s, None, "failed: ConnectionError: reset"), "Mac")
    assert r["price_gbp"] is None and r["refundable"] is False and r["status"].startswith("error: free-cancellation")


def test_no_price():
    assert fields(page(result(JW, None)), JW)["status"] == "error: no rate for 2 adults + 1 child"
    assert fields(page(result(JW, 0)), JW)["status"] == "error: no rate for 2 adults + 1 child"
    # occupancy is unreliable: 2 (JW Marriott) and 0 (Prince hotels) are valid party rates
    assert fields(page(result(JW, 900.0, occupancy=2)), JW)["status"] == "ok"
    assert fields(page(result(277479, 2103.58, occupancy=0, charges="Additional charges may apply")), 277479)["price_gbp"] == 2103.58
    assert fields(page(result(JW, 900.0, occupancy=1)), JW)["status"] == "error: no rate for 2 adults + 1 child"
    assert fields(page(result(JW, 900.0, sold_out=True)), JW)["status"] == "sold out"
    assert fields(page(result(1, 900.0)), JW)["status"] == "error: hotel not in search results"
    assert fields(page(result(JW, 900.0, currency="JPY")), JW)["status"].startswith("error")
    r = fields(page(result(JW, None)), JW)
    assert all(r[k] is None for k in ("price_gbp", "price_any_gbp", "room", "taxes_included")) and r["refundable"] is False


def test_classify():
    # Observed without cookies on the hotel page: HTTP 202 + AWS WAF challenge HTML
    challenge = '<html><head><script src="/__challenge_x/challenge.js"></script><script>AwsWafIntegration</script></head></html>'
    for resp in (FakeResponse(202, challenge), FakeResponse(200, challenge),
                 FakeResponse(405, "", {"x-amzn-waf-action": "captcha"})):
        try:
            bc.classify(resp)
            raise AssertionError("challenge not detected")
        except bc.RobotCheck:
            pass
    for resp in (FakeResponse(403, "Forbidden"), FakeResponse(200, "<html>maintenance</html>"),
                 FakeResponse(200, '{"errors":[{"message":"Unknown fragment"}]}')):
        try:
            bc.classify(resp)
            raise AssertionError("error not raised")
        except RuntimeError:
            pass
    assert bc.classify(FakeResponse(200, '{"data":{"__typename":"Query"}}'))["data"]


def test_operation_names_match_queries():
    # The server rejects an operationName that is not defined in the query text
    import inspect, re
    src = inspect.getsource(bc)
    defined = set(re.findall(r"query (\w+)\(", bc.ID_QUERY + bc.SEARCH_QUERY))
    used = set(re.findall(r'client\.post\("(\w+)"', src))
    assert used and used <= defined, (used, defined)


class FakeClient:
    calls = 0

    def __init__(self, diagnose=False):
        pass


def with_fake_check(outcomes, fn):
    """Run fn with bc.check replaced: outcomes maps slug -> fields dict or an exception to raise."""
    asked = []
    orig_check, orig_client, orig_ids = bc.check, bc.Client, bc.IDS_FILE

    def fake_check(client, slug, ci, co, ids):
        asked.append(slug)
        o = outcomes.get(slug, dict(bc.EMPTY, price_gbp=100.0, price_any_gbp=100.0, status="ok"))
        if isinstance(o, Exception):
            raise o
        return o

    with tempfile.TemporaryDirectory() as d:
        bc.check, bc.Client, bc.IDS_FILE = fake_check, FakeClient, os.path.join(d, "ids.json")
        try:
            return fn(d), asked
        finally:
            bc.check, bc.Client, bc.IDS_FILE = orig_check, orig_client, orig_ids


def test_file_format_and_robot_check():
    def go(d):
        return bc.run(bc.HOTELS, os.path.join(d, "latest.json"))
    # Challenge on the 4th option: it and every later option are "robot check", nothing more is asked
    doc, asked = with_fake_check({"the-prince-sakura-tower-tokyo": bc.RobotCheck("HTTP 202")}, go)
    assert list(doc) == ["date", "checked_at", "runner", "results"] and doc["runner"] in ("mac", "github-actions")
    assert [r["option_id"] for r in doc["results"]] == [h[0] for h in bc.HOTELS]  # exactly 21, in order
    assert all(list(r) == FIELDS and r["date"] == doc["date"] for r in doc["results"])
    assert [r["status"] for r in doc["results"]][3:] == ["robot check"] * 18 and len(asked) == 4
    assert all(r["status"] in STATUSES or r["status"].startswith("error: ") for r in doc["results"])
    # A dropped connection on one option is recorded and the rest carry on
    doc, asked = with_fake_check({"hilton-kyoto": ConnectionError("reset")}, go)
    assert doc["results"][14]["status"].startswith("error: ConnectionError") and len(asked) == 21
    assert doc["results"][14]["price_gbp"] is None and doc["results"][15]["status"] == "ok"


def test_same_day_rerun():
    today = bc.datetime.now(bc.LONDON).date().isoformat()

    def prev_doc(date, status_for):
        return {"date": date, "checked_at": "x", "runner": "github-actions", "results": [
            dict(bc.row(date, h[0], "earlier", dict(bc.EMPTY, price_gbp=1.0, price_any_gbp=1.0, status="ok"), "GitHub"),
                 status=status_for(i)) for i, h in enumerate(bc.HOTELS)]}

    def go_with(prev):
        def go(d):
            p = os.path.join(d, "latest.json")
            json.dump(prev, open(p, "w"))
            return bc.run(bc.HOTELS, p)
        return go

    # Same day: keep priced options, only ask about the unpriced ones
    doc, asked = with_fake_check({}, go_with(prev_doc(today, lambda i: "ok" if i != 5 else "error: HTTP 500")))
    assert asked == [bc.HOTELS[5][1]] and doc["results"][0]["checked_at"] == "earlier"
    assert doc["results"][5]["checked_at"] != "earlier" and len(doc["results"]) == 21
    # Yesterday's file: nothing is carried forward
    doc, asked = with_fake_check({}, go_with(prev_doc("2000-01-01", lambda i: "ok")))
    assert len(asked) == 21 and all(r["date"] == today and r["checked_at"] != "earlier" for r in doc["results"])
    # A robot check earlier today: make no requests at all
    doc, asked = with_fake_check({}, go_with(prev_doc(today, lambda i: "robot check" if i > 2 else "ok")))
    assert doc is None and asked == []


def test_hotels():
    assert len(bc.HOTELS) == 21 and len({h[0] for h in bc.HOTELS}) == 21
    assert [h[0].split("-")[0] for h in bc.TEST_HOTELS] == ["tokyo", "osaka", "kyoto"]
    inp = bc.search_input(JW, "2027-08-08", "2027-08-12")
    assert inp["location"] == {"destType": "HOTEL", "destId": JW} and inp["filters"] == {}
    assert inp["nbAdults"] == 2 and inp["nbChildren"] == 1 and inp["childrenAges"] == [10] and inp["nbRooms"] == 1
    assert bc.search_input(JW, "a", "b", bc.FREE_CANCELLATION)["filters"] == {"selectedFilters": "fc=2"}
    assert bc.PAUSE[0] >= 5
    assert bc.last_free_cancellation_day("2027-08-06T15:00:00Z") == "2027-08-06"
    assert bc.last_free_cancellation_day(None) is None
    # No cookies are stored or sent, even within a run
    c = bc.Client()
    assert tuple(c.s.cookies._policy.allowed_domains()) == ()  # no domain may set cookies
    req = c.s.prepare_request(bc.requests.Request("POST", bc.URL, json={}))
    assert "Cookie" not in req.headers


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("booking tests passed")
