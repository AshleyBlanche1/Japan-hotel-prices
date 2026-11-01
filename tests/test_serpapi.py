import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from serpapi_check import extract, same_hotel, HOTELS

def test_extract():
    detail = {"name": "Hilton Kyoto", "prices": [
        {"source": "Booking.com", "rate_per_night": {"extracted_lowest": 256}},
        {"source": "Agoda", "rate_per_night": {"extracted_lowest": 240}, "total_rate": {"extracted_lowest": 482}},
    ]}
    r = extract(detail, 2)
    assert r["price_gbp"] == 512 and r["nightly_gbp"] == 256
    assert r["cheapest_site"] == "Agoda" and r["cheapest_stay_gbp"] == 482
    assert extract({"prices": []}, 2)["status"] == "no prices"

def test_matching_and_rotation():
    assert same_hotel("Hilton Kyoto", "Hilton Kyoto")
    assert not same_hotel("Hilton Kyoto", "Kyoto Tower Hotel")
    groups = [[h for i, h in enumerate(HOTELS) if i % 3 == g] for g in range(3)]
    assert [len(g) for g in groups] == [7, 7, 7]

if __name__ == "__main__":
    test_extract(); test_matching_and_rotation(); print("serpapi tests passed")
