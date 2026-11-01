import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from scraper import parse

def test_hilton_kyoto_sample():
    html = (pathlib.Path(__file__).parent / "hilton_kyoto_sample.html").read_text()
    r = parse(html)
    assert r["status"] == "ok"
    assert r["price_gbp"] == 512        # cheapest free-cancellation rate that fits 2 adults + 1 child
    assert r["price_any_gbp"] == 425    # cheapest rate that fits, any terms
    assert r["room"] == "Family Twin Room"

def test_blocked_page():
    assert parse("<html>px-captcha</html>")["status"] == "robot check"
    assert parse("<html><body>nothing</body></html>")["status"] == "no room table"

if __name__ == "__main__":
    test_hilton_kyoto_sample(); test_blocked_page(); print("all tests passed")
