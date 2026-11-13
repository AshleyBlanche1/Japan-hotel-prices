# Booking.com check from GitHub Actions: test results

Can `booking_check.py` read Booking.com prices from GitHub's network, with the Mac closed?
Workflow: `.github/workflows/booking-test.yml` (manual, plus a temporary schedule at
06:37 and 13:07 UTC). Each run's full log and JSON are saved as an artifact
(`booking-test-<run>-<attempt>`), and a results table is on the run's summary page.

Same request as from the Mac: plain Python `requests`, honest User-Agent, no cookies,
sequential, 5–10 s apart. See `docs/booking-endpoints.md`.

## Status (13 Nov 2026, 22:45 UTC): first runs succeed, decision pending

**Outcome so far: works from GitHub.** Both GitHub runs got HTTP 200 JSON for every request,
with no challenge, no 202/403/429, no `x-amzn-waf-action` header and no non-JSON body.
The brief needs at least three 21-option runs at different times of day (including
06:30–07:00 UTC) before deciding; one is done, two are scheduled.

## Runs

| Run (UTC start) | Trigger | Options | Requests | Priced | Non-200 / challenge | CloudFront POP | Run |
|---|---|---|---|---|---|---|---|
| 2026-11-13 22:35 | manual | 3 test | 4 | 3 / 3 | none | PHX52 (Phoenix) | [43520554187](https://github.com/AshleyBlanche1/Japan-hotel-prices/actions/runs/43520554187) |
| 2026-11-13 22:36 | manual | 21 | 26 | **19 / 21** | none | SFO5 (San Francisco) | [43520706155](https://github.com/AshleyBlanche1/Japan-hotel-prices/actions/runs/43520706155) |
| 2026-11-14 06:37 | schedule | 21 | | | | | pending |
| 2026-11-14 13:07 | schedule | 21 | | | | | pending |

Every response had `server: istio-envoy`, `via: … cloudfront.net (CloudFront)` and the same
five set-cookie names as from the Mac (`bkng`, `bkng_sso_auth`, `pcm_consent`,
`persisted_currency`, `persisted_lang`). The script refuses all cookies, so none were sent back.

### Unpriced options in the 22:36 run

| Option | GitHub | Mac | Notes |
|---|---|---|---|
| tokyo-1-1-hotel-tokyo (8–12 Aug) | sold out | sold out | Genuine: the website says "We have no availability on our site for this property" for these dates. |
| tokyo-2-jw-marriott-hotel-tokyo (19–21 Aug) | sold out | **£932.00**, free cancellation (Mac, 22:41, a few minutes later) | GitHub's runners are in the US; Booking.com may offer a different inventory to US visitors, or this was a momentary gap. Watch the scheduled runs. From now on the 21-option test also logs response bodies, so a repeat will show what Booking returned. |

## Same-hour comparison with the Mac

GitHub run 22:35–22:36 UTC; Mac run 22:37 UTC (same script, `--hotels 3`).

| Option | GitHub price_gbp / price_any_gbp | Mac price_gbp / price_any_gbp | Room (both) | Match |
|---|---|---|---|---|
| tokyo-1-jw-marriott-hotel-tokyo | £1,804.24 / £1,804.24 | £1,804.24 / £1,804.24 | Urban Deluxe Twin | exact |
| osaka-the-osaka-station-hotel | £1,391.77 / £1,391.77 | £1,391.77 / £1,391.77 | Scenic Allure King Room | exact |
| kyoto-hilton-kyoto | £509.88 / £423.21 | £509.88 / £423.21 | Family Twin Room | exact |

The 21-option GitHub run (22:36) against the Mac's last full run (21:56, 40 minutes earlier,
so not the same hour):

- **Prices identical for 15 of the 19 options GitHub priced.** Two of those (RIHGA Royal
  Osaka, Dusit Thani Kyoto) named a different room at the same price.
- **4 prices differed**, and 3 of them equal a price the Mac itself returned in an earlier
  run that day: Grand Prince Shin Takanawa 8–12 Aug £937.67 (Mac runs: £937.67 and £887.87),
  The Thousand Kyoto £437.53 (Mac: £437.53 and £490.03/£458.35), Grand Prince Takanawa
  £611.29 (Mac: £611.29 and £578.99). Celestine Kyoto Gion £531.76 had not been seen on the
  Mac (£492.37 in every Mac run).
- Prices moved between Mac runs in the same way, so these look like Booking.com's offer
  changing over time rather than a GitHub/Mac difference; the same-hour comparison above
  shows no difference at all.

## Decision (Task 3)

Pending the two scheduled 21-option runs. Rule from the brief: build the daily workflow if
at least two of three 21-option runs price 18 or more options with no challenge; stop and
report "blocked from GitHub Actions" on any 202/403/429, challenge page, `x-amzn-waf-action`
header or non-JSON body.
