# Booking.com hotel page: what it calls and what each call needs

Investigated 2026-11-13 in desktop Chrome (Claude in Chrome), on one hotel:

```
https://www.booking.com/hotel/jp/jw-marriott-tokyo.en-gb.html?checkin=2027-08-08&checkout=2027-08-12&group_adults=2&req_adults=2&no_rooms=1&group_children=1&req_children=1&age=10&req_age=10&selected_currency=GBP&lang=en-gb
```

No cookie values, CSRF tokens or session IDs are recorded here. Only cookie *names* are recorded.

## Summary

| Question | Answer |
|---|---|
| Is there a JSON/GraphQL endpoint that returns prices without the challenge? | **Yes, the search one (section 4).** `POST /dml/graphql` with a `searchQueries.search` query and `location: {destType: "HOTEL", destId: <hotel id>}` returned JW Marriott at **£1,804, free cancellation, taxes included**. There was no cookie and no challenge. That matches the hotel page's cheapest free-cancellation row. The hotel page's own room data, in contrast, is only in its HTML (sections 1–2). |
| Are prices in the first HTML response? | **Yes**, if the request carries a valid `aws-waf-token` cookie. The HTML is 2.5 MB and holds `#hprt-table` (23 rows) plus an inline JSON block `b_rooms_available_and_soldout`. |
| What happens without cookies? | **HTTP 202**, 4,760-byte **AWS WAF JavaScript challenge** page with no prices. This happened even from real Chrome on a home connection. |
| What does `/dml/graphql` give? | It answers without cookies (HTTP 200), but the room query (`RoomTableQuery`) returns `roomCards: []` on the desktop site. The other operations cover reviews, FAQ, search box, breadcrumbs and similar, not prices. |
| Expected result from GitHub Actions | The HTML page will very likely get the same 202 challenge. Getting past it means running AWS's challenge JavaScript, which the brief rules out. The search GraphQL call (section 4) works from a home connection with plain Python `requests` and minimal input (section 5). The remaining unknown is whether GitHub's network gets the same treatment; Step 3 still needs to run to confirm this. |

## 1. The hotel page HTML (where the prices are)

**Request:** `GET` the URL above.

| Test (from inside the page, same browser) | Status | Body | `#hprt-table` |
|---|---|---|---|
| `fetch(url, {credentials:'include'})`: browser cookies sent | 200 | 2,512,760 chars | yes, 23 rows |
| `fetch(url, {credentials:'omit'})`: no cookies | **202** | 4,760 chars | **no** |

Response headers in both cases: `server: istio-envoy`. There was no `x-amzn-waf-action` header and no `cf-mitigated` header.

**The 202 page:**
- No `<title>`, 4 inline scripts, plus a script from `www.booking.com/__challenge_<id>/d8c14d4960ca/a18a4859af9c/…`
- Contains `challenge.js` and `AwsWafIntegration`
- `<noscript>`: "JavaScript is disabled. In order to continue, we need to verify that you're not a robot. This requires JavaScript…"
- Detection rule for scripts: `status == 202` or the body contains `AwsWafIntegration` or `challenge.js`, **and** there is no `hprt-table`. Add this to the existing `captcha|challenge-platform|px-captcha` regex, which **does not match** this page.

**What makes the 200 work:** the `aws-waf-token` cookie. The AWS WAF SDK sets it after running the challenge in the browser, via calls to `https://d8c14d4960ca.edge.sdk.awswaf.com/d8c14d4960ca/a18a4859af9c/{inputs,telemetry,mp_verify}`. The SDK keeps sending telemetry while the page is open. Other cookies present: `OptanonConsent`, `pcm_pac`, `cors_js`, `g_state`, `bk_nav_search`. None of these appeared to be required.

### Price data in the HTML

**a) Room table `#hprt-table`.** Column headers are "Room type | Number of guests | **Price for 4 nights** | Your choices | Select rooms". Prices are for the whole stay. Sample rows (JW Marriott, 8–12 Aug 2027, 2 adults + 1 child aged 10):

| Room | Occupancy cell | Conditions (trimmed) | Price cell |
|---|---|---|---|
| Urban Deluxe King | Max adults: 2, Max children: 1 | Breakfast £31 (optional) · Free cancellation before 25 July 2027 · No prepayment needed | £1,804, Includes taxes and charges |
| Urban Deluxe King | Max adults: 2, Max children: 1 | Breakfast included · Free cancellation before 25 July 2027 | £2,043, Includes taxes and charges |
| Urban Deluxe King | Max adults: 3 | Breakfast £31 (optional) · Free cancellation… | £2,163, Includes taxes and charges |
| Urban Deluxe King | Max adults: 1, Max children: 1 (Only for 1 guest) | Breakfast included · Free cancellation… | £1,920, Includes taxes and charges |

All of the brief's fields can be read from the table:
- free cancellation is in `.hprt-table-cell-conditions`
- occupancy is in `.hprt-table-cell-occupancy`
- the GBP whole-stay price and "Includes taxes and charges" are in `.hprt-table-cell-price`

The room name is only on the first row of each room group. Carry it forward to the rows below it, as the laptop script does. Rows such as "Max adults: 1, Max children: 1" must be excluded because they don't fit the party.

**b) Inline JSON `b_rooms_available_and_soldout`.** This is structured data in the same HTML and is easier to parse than the table:

```
b_rooms_available_and_soldout: [{"b_blocks":[{"b_is_cfar":0,"b_book_now_pay_later":1,"b_cancellation_type":"free_cancell…
```

Keys seen include `b_blocks`, `b_cancellation_type`, `b_book_now_pay_later`, `b_price_breakdown_simplified`, `b_raw_value`, `b_raw_value_user_currency`, `b_value_user_currency_rounded`, `b_total_price`, `b_original_price`, `b_is_all_included`, `b_included_charges`, `b_excluded_charges_amount`. It sits in the same protected HTML, so it doesn't avoid the challenge.

## 2. `POST https://www.booking.com/dml/graphql`

There were 10 calls on page load and 1 more after scrolling. The query string repeats the page's search parameters (`checkin, checkout, group_adults, …, selected_currency, lang`).

**Headers the page sends:**
- `content-type: application/json`, `accept`
- `apollographql-client-name`, `apollographql-client-version`, `x-apollo-operation-name`
- `x-booking-csrf-token`, which comes from `b_csrf_token:` in the inline JS of the HTML
- `x-booking-context-action`, `x-booking-context-action-name`, `x-booking-context-aid`, `x-booking-pageview-id`
- `x-booking-site-type-id` (desktop = `1`), `x-booking-et-serialized-state`, `x-booking-topic`

**Cookie-less test from the page:** a minimal `query Probe { __typename }` with `credentials:'omit'` and only `content-type` returned **HTTP 200** `{"data":{"__typename":"Query"}}`. No CSRF token or WAF token was needed and there was no challenge. This was from Chrome. Whether a GitHub Actions request gets the same treatment is untested.

**Operation that relates to rooms: `RoomTableQuery`.** It's defined in `bea60ab5.…chunk.js` and is 4,037 characters long. It needs two fragments, `PriceDisplayInfoHP` and `PriceXRayHP`, that aren't in the same string.

```json
{
  "operationName": "RoomTableQuery",
  "query": "query RoomTableQuery($input: RoomTableQueryInput!, $isPriceXRay: Boolean = false) { roomTable(input: $input) { ... on RoomTableQueryResult { hotelId propertyName isSoldOut eligibleForCaplaMicrofunnel roomCards { … } … } } }",
  "variables": {
    "input": {
      "highlightedBlocks": [],
      "pagenameDetails": { "countryCode": "jp", "pagename": "jw-marriott-tokyo" },
      "searchConfig": {
        "nbAdults": 2, "nbChildren": 1, "childrenAges": [10], "nbRooms": 1,
        "searchConfigDate": { "checkin": "2027-08-08", "checkout": "2027-08-12" }
      }
    }
  }
}
```

Response, the same with and without cookies, with the two fragment spreads removed:

```json
{"data":{"roomTable":{"__typename":"RoomTableQueryResult","hotelId":14630603,
 "propertyName":"JW Marriott Hotel Tokyo","isSoldOut":false,
 "eligibleForCaplaMicrofunnel":false,"roomCards":[], "…": "…"}}}
```

`roomCards` is empty. The server-rendered Apollo cache in the HTML shows the same: `RoomTableQueryResult` with `roomCards: []`. On the desktop site this query doesn't carry rooms, prices or cancellation terms. It may be populated for the mobile/"Capla microfunnel" experience (`x-booking-site-type-id` other than 1), but that was not tested.

**Other operation names in the page bundles** (none returned price data during this visit): `HotelPageByPageName`, `PropertyPage`, `PropertyDetails`, `PropertyFaq`, `Facilities`, `ReviewList`, `ReviewScoreFilter`, `SearchBoxConfig`, `AutoComplete`, `SeoBreadcrumbs`, `ProductShell`, `UserSearches`, `viewedQuestions`, `RoomPageDesktopRDS`, `FullSearch`, `CreateBasketV3` (a booking mutation, never to be called) and others. The server-rendered Apollo cache keys were `hotelPageByPageName`, `roomTable`, `roomDetail`, `reviewScores`, `reviewsFrontend`, `rankedItems`, `merchComponents`, `searchBoxContent`, `breadcrumbs` and `landingContent`.

## 3. Other requests (not price data)

| Endpoint | Purpose |
|---|---|
| `*.edge.sdk.awswaf.com/…/{inputs,telemetry,mp_verify}` | AWS WAF bot-control SDK, which issues `aws-waf-token` |
| `www.booking.com/<long random path>` (about 20 `fetch` calls) | Obfuscated paths, probably bot-detection or telemetry beacons |
| `sink.gw.booking.com/v1/sink`, `c360.booking.com/v1/c360/multitrack`, `otel-gw.booking.com/v1/traces`, `js_tracking`, `js_errors`, `navigation_times`, `squeak`, `log_rt_blocks_order` | Analytics and telemetry |
| `accommodations.booking.com/orca/chunk-metadata`, `fragment.en-gb.json`, `acid_carousel` | Front-end assets and widgets |
| `cdn.cookielaw.org`, `geolocation.onetrust.com`, `accounts.google.com/gsi/status` | Cookie consent and Google sign-in |

## 4. Search GraphQL: prices without the HTML page

The search results page (`/searchresults.en-gb.html`) uses the operation `FullSearch`, defined in `ab5efd39.…chunk.js`, and the same `/dml/graphql` endpoint. `FullSearch` needs a large fragment (`FullSearchFragment`). A small hand-written query against the same field works on its own.

**Request** (tested from the page with `credentials:'omit'`; the only header was `content-type: application/json`; no CSRF token, no cookies):

```
POST https://www.booking.com/dml/graphql?lang=en-gb&selected_currency=GBP
```

```json
{
  "operationName": "Probe",
  "query": "query Probe($input: SearchQueryInput!) { searchQueries { search(input: $input) { ... on SearchQueryOutput { results { displayName { text } basicPropertyData { id pageName } policies { showFreeCancellation } soldOutInfo { isSoldOut } priceDisplayInfoIrene { chargesInfo { translation } displayPrice { amountPerStay { amountUnformatted currency } } } } } } } }",
  "variables": { "input": {
    "location": { "destType": "HOTEL", "destId": 14630603 },
    "dates": { "checkin": "2027-08-08", "checkout": "2027-08-12" },
    "nbAdults": 2, "nbChildren": 1, "childrenAges": [10], "nbRooms": 1,
    "pagination": { "offset": 0, "rowsPerPage": 20 },
    "doAvailabilityCheck": false,
    "…": "other SearchQueryInput fields copied from the page's server-rendered input (filters: {}, sorters, flexibleDatesConfig, etc.); trim to the minimum in Step 2"
  } }
}
```

**Response (trimmed):** HTTP 200 JSON, no challenge. It was identical with and without cookies.

```json
{"data":{"searchQueries":{"search":{"results":[
  {"displayName":{"text":"JW Marriott Hotel Tokyo"},
   "basicPropertyData":{"id":14630603,"pageName":"jw-marriott-tokyo"},
   "policies":{"showFreeCancellation":true},
   "soldOutInfo":{"isSoldOut":false},
   "priceDisplayInfoIrene":{"chargesInfo":{"translation":"Includes taxes and charges"},
     "displayPrice":{"amountPerStay":{"amountUnformatted":1804.2446,"currency":"GBP"}}}},
  {"…": "19 nearby hotels follow, e.g. the-prince-park-tower-tokyo £950"}
]}}}}
```

**Findings:**
- **Search by hotel ID, not by name.** A free-text search (`destType: "NO_DEST_TYPE", searchString: "JW Marriott Hotel Tokyo"`) returned JW Marriott with **no price**, and the web page said "unavailable on our site for your dates". Searching with `destType: "HOTEL", destId: 14630603` returned the price. `doAvailabilityCheck` true or false made no difference.
- The result is a **single headline price**: Booking's cheapest option for the party, for the whole stay, in GBP. It comes with `showFreeCancellation` (whether that rate is free-cancellation) and the taxes wording. Here it was £1,804, free cancellation, taxes included, matching the hotel page's cheapest fitting free-cancellation row (Urban Deluxe King).
- **Not yet available from this query:** the room name, and separate `price_gbp` (cheapest free-cancellation) and `price_any_gbp` (cheapest of any rate). Candidates to try in Step 2: the `blocks` / `matchingUnitConfigurations` fields for the room name, and the search filter for free cancellation (on the website this is `nflt=fc%3D2`) to get the free-cancellation price separately.
- **Hotel IDs** are needed for all 21 options. A one-off lookup gives them: `basicPropertyData.id`, or `b_hotel_id` in the hotel page HTML. They don't change, so they can be stored in config.
- **Caveats:** this endpoint is undocumented and can change without notice, and Booking.com's terms don't permit automated scraping. Keep to the brief's gentle limits (21 requests a day, several seconds apart). Responses with `taxes: "Additional charges may apply"` mean the price excludes some taxes; record `taxes_included: false` for those.

## 5. Script test from this Mac (plain Python requests, 2026-11-13)

`booking_check.py` implements section 4. It was run from this Mac on a home connection.

**Setup:**
- Python `requests` 2.32.3, one `requests.Session`. No cookies are sent at the start, no login, no browser impersonation.
- Honest User-Agent: `Japan-hotel-prices/1.0 (personal price tracker, 21 hotels once a day; +https://github.com/AshleyBlanche1/Japan-hotel-prices)`. Other headers: `Content-Type: application/json`, `Accept: application/json`.
- Requests are sequential, with a random 5–10 s pause between them.
- Endpoint: `POST https://www.booking.com/dml/graphql?lang=en-gb&selected_currency=GBP`.
- Calls per hotel:
  1. `HotelId` (first run only): a `roomTable` query (`pagenameDetails: {countryCode: "jp", pagename: <slug>}` + party + dates) that returns `hotelId` for the slug. The result is cached in `data/booking_hotel_ids.json`, so each slug is looked up only once (18 distinct slugs).
  2. `HotelPrice`: the section 4 search with `location: {destType: "HOTEL", destId: <hotel id>}`. The script picks the result whose `basicPropertyData.id` equals the hotel id, because nearby hotels are listed after it.
  3. `HotelPrice` again with `filters: {"selectedFilters": "fc=2"}` (the website's "Free cancellation" filter, URL `nflt=fc%3D2`). This call is made **only when the cheapest rate is non-refundable**. It gives `price_gbp`.
- Fields read per hotel: `priceDisplayInfoIrene.displayPrice.amountPerStay` (GBP whole-stay price), `policies.showFreeCancellation`, `priceDisplayInfoIrene.chargesInfo.translation` (taxes), `soldOutInfo.isSoldOut`, `blocks[].{blockId.roomId, freeCancellationUntil}`, and `matchingUnitConfigurations.unitConfigurations[].{name, unitId}` (room name, linked to the block by `roomId` = `unitId`).
- One polite retry on HTTP 5xx/429 **or a dropped connection/timeout**, then the request is given up. A 202, an `x-amzn-waf-action` header or a non-JSON body containing a challenge marker is recorded as "robot check", and after that the script stops making requests.
- **Requests per daily run: 21–26** once the IDs are cached (21 searches + one free-cancellation search per hotel whose cheapest rate is non-refundable). The very first run adds 18 ID lookups.

**Single-hotel diagnostic (`--diagnose`):**
- Both calls returned HTTP 200 JSON. There was no challenge.
- Response headers: `server: istio-envoy`. Served via CloudFront (`via: … cloudfront.net`, POP `LHR86`). There was no `x-amzn-waf-action` header.
- Set-cookie names on the first call: `bkng`, `bkng_sso_auth`, `pcm_consent`, `persisted_currency`, `persisted_lang`. Only the names are recorded here. Since 13 Nov 22:20 UTC the script refuses all cookies (an empty cookie policy, and the jar is cleared before every request), so nothing is ever sent back; a run made that way priced JW Marriott at the same £1,804.24, so cookies are not needed.
- **Minimal search input is accepted.** The full server-rendered input from the page is NOT needed. This is all the script sends:

```json
{
  "location": { "destType": "HOTEL", "destId": 14630603 },
  "dates": { "checkin": "2027-08-08", "checkout": "2027-08-12" },
  "nbAdults": 2, "nbChildren": 1, "childrenAges": [10], "nbRooms": 1,
  "pagination": { "offset": 0, "rowsPerPage": 10 },
  "filters": {},
  "doAvailabilityCheck": false
}
```

**Final results, all 21 hotels** (`data/booking_latest.json`, `checked_at` 2026-11-13T21:56:51Z, 27 requests, no errors, no challenges). Prices are GBP for the whole stay, 2 adults + 1 child aged 10, 1 room. `price_gbp` = cheapest free-cancellation rate; `price_any_gbp` = cheapest rate of any kind.

| option_id | status | price_gbp | price_any_gbp | room | taxes incl. | free cancel until |
|---|---|---|---|---|---|---|
| tokyo-1-1-hotel-tokyo | sold out | null | null | — | null | — |
| tokyo-1-jw-marriott-hotel-tokyo | ok | 1,804.24 | 1,804.24 | Urban Deluxe Twin | true | 2027-07-24 |
| tokyo-1-hotel-toranomon-hills | ok | 1,624.95 | 1,341.08 | Deluxe King Room with One King Bed and Sofa Bed | true | 2027-08-06 |
| tokyo-1-the-prince-sakura-tower-tokyo | ok | 2,103.58 | 2,103.58 | Deluxe Twin Room with Extra Bed (Non-Smoking)+ Sauna Access | false | 2027-08-06 |
| tokyo-1-ana-intercontinental-tokyo | ok | 1,158.42 | 1,124.01 | Premium Twin Room | true | 2027-07-08 |
| tokyo-1-the-prince-park-tower-tokyo | ok | 950.25 | 950.25 | Deluxe Twin Room - Non Smoking (Extra bed added for 3rd adult person) | false | 2027-08-06 |
| tokyo-1-grand-prince-hotel-shin-takanawa | ok | 887.87 | 887.87 | Superior Corner Twin Room - Non-Smoking | false | 2027-08-06 |
| osaka-the-osaka-station-hotel | ok | 1,391.77 | 1,391.77 | Scenic Allure King Room | true | 2027-08-11 |
| osaka-the-gate-hotel-osaka-by-hulic | ok | 1,656.14 | 1,656.14 | Deluxe Triple Room - Non-Smoking | false | 2027-08-10 |
| osaka-rihga-royal-hotel-osaka | ok | 786.61 | 763.02 | Standard King Room | false | 2027-07-12 |
| osaka-the-royal-park-hotel-iconic-osaka-midosuji | ok | 702.42 | 702.42 | Standard Twin Room (Max 3 Persons) - Non-Smoking | false | 2027-08-08 |
| kyoto-dusit-thani-kyoto | ok | 420.44 | 420.44 | Deluxe King Room | false | 2027-08-14 |
| kyoto-hotel-the-celestine-kyoto-gion | ok | 492.37 | 492.37 | Deluxe Twin Room with Sofa Bed - Non-Smoking | false | 2027-08-13 |
| kyoto-the-thousand-kyoto | ok | 490.03 | 458.35 | Twin Room with Extra Bed | false | 2027-07-26 |
| kyoto-hilton-kyoto | ok | 509.88 | 423.21 | Family Twin Room | false | 2027-08-16 |
| tokyo-2-jw-marriott-hotel-tokyo | ok | 932.00 | 932.00 | Urban Deluxe Twin | true | 2027-08-04 |
| tokyo-2-gajoen-tokyo | ok | 1,179.98 | 1,003.04 | Premium Twin Room with Garden View | true | 2027-08-18 |
| tokyo-2-the-prince-sakura-tower-tokyo | ok | 1,051.79 | 1,051.79 | Deluxe Twin Room with Extra Bed (Non-Smoking)+ Sauna Access | false | 2027-08-17 |
| tokyo-2-grand-prince-hotel-takanawa | ok | 578.99 | 578.99 | Deluxe Triple Room | false | 2027-08-17 |
| tokyo-2-intercontinental-tokyo-bay | ok | 599.05 | 599.05 | Classic Twin Room with Bay View | false | 2027-07-19 |
| tokyo-2-grand-prince-hotel-shin-takanawa | ok | 480.26 | 480.26 | Superior Corner Twin Room - Non-Smoking | false | 2027-08-17 |

### Test runs on 2026-11-13 (all from this Mac, plain `requests`, no cookies)

| Run | Requests | Priced | What went wrong | Fix |
|---|---|---|---|---|
| 1 | 39 (18 ID lookups + 21 searches) | 19/21 | Dusit Thani: `ConnectionError` ("Remote end closed connection without response"), not retried. 5 hotels had a non-refundable cheapest rate, so `price_gbp` was empty. No room names. | Retry once on dropped connections. Added the `fc=2` free-cancellation search and the `blocks` / `matchingUnitConfigurations` fields. |
| 2 | 26 | 8/21 | Two bugs of mine. (a) The free-cancellation call used an operation name not defined in the query, so the server replied `Unknown operation named …`. (b) A party-fit rule required `blockId.occupancy >= 3` and rejected 12 valid rates (JW Marriott's 2 adults + 1 child room reports 2). | Use the query's own operation name (now covered by a unit test). Relaxed the rule. |
| 3 | 26 | 15/21 | Party-fit rule still rejected 5 Prince-group stays: those hotels report `occupancy: 0` (not given). | Trust Booking's own party matching ("Recommended for your group"); reject a rate only if `occupancy == 1`. Re-checked the 5 (5 requests): all priced. |
| 4 (final) | 27 (21 searches + 6 free-cancellation searches) | **20/21** | None. 1 Hotel Tokyo is genuinely unavailable. | — |

Across all runs: about 100 requests, every one HTTP 200 JSON, **no challenge, no 403/429**.

### Checks against the website (Chrome)

| Check | Website | Script | Result |
|---|---|---|---|
| JW Marriott 8–12 Aug, cheapest free-cancellation fitting rate | £1,804 (hotel page room table) | £1,804.24 | match |
| Hilton Kyoto 17–19 Aug with "Free cancellation" filter | £509.88, Family Twin Room (search page, `nflt=fc%3D2`) | £509.88, Family Twin Room | match |
| 1 Hotel Tokyo 8–12 Aug | "We have no availability on our site for this property between Sun 8 Aug 2027 and Thu 12 Aug 2027" | sold out | match |
| Prince Park Tower 8–12 Aug, taxes | Card shows £950 and "Additional charges may apply"; the excluded charge is listed as `chargeMode: INCALCULABLE` (likely the local per-person accommodation tax) | £950.25, `taxes_included: false` | match |

### Things to know

- **Prices move between runs.** Within an hour, Grand Prince Shin Takanawa (8–12 Aug) came back at £937.67 and £887.87, Grand Prince Takanawa (19–21 Aug) at £611.29 and £578.99, and The Thousand Kyoto changed from £437.53 (free cancellation) to £458.35 (non-refundable) / £490.03 (free cancellation). These look like real rate or inventory changes, or different rooms being recommended, not script errors. Daily figures should be read as "Booking.com's offer at that moment".
- **`taxes_included: false` is normal for Japan.** Most hotels here add a local accommodation tax that Booking can't calculate in advance, so the website says "Additional charges may apply". The script records exactly what the website says.
- **The room shown is Booking's recommendation for the party** (the cheapest rate that fits 2 adults + 1 child aged 10), not every room the hotel has. `blockId.occupancy` turned out to be unreliable (2, 3 or 0 for valid family rates), so the script relies on Booking's matching and rejects only rates marked for one guest.
- The endpoint is undocumented and Booking.com's terms don't permit automated scraping. The script keeps to the brief's limits: 21–27 requests a day, sequential, 5–10 s apart, honest User-Agent, no cookies kept between runs.

## Implications for Steps 2–3

1. **Step 2 is done.** `booking_check.py` works from a home connection with plain `requests`: 20 of 21 hotels priced, with every field in the brief filled (`price_gbp`, `price_any_gbp`, `room`, `taxes_included`, `refundable`, `status`) plus `free_cancellation_until`. Offline unit tests: `tests/test_booking.py`.
2. The hotel-page HTML returns **202 + AWS WAF challenge** without cookies. Getting the `aws-waf-token` means executing AWS's challenge JavaScript, which is outside the brief's boundaries. Not used.
3. `RoomTableQuery` returns no rooms on desktop. It is used only to turn a slug into a hotel id.
4. **The remaining unknown is GitHub's network.** Step 3: run `.github/workflows/booking-test.yml` (manual, three test hotels, `--diagnose`) at least three times at different times of day, then record the results in `docs/github-actions-test.md`. Only if it works there, add the daily scheduled workflow that writes `data/booking_latest.json`.
