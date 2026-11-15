# Booking.com check from GitHub Actions: test results

Can `booking_check.py` read Booking.com prices from GitHub's network, with the Mac closed?
Workflow: `.github/workflows/booking-test.yml` (manual only). Each run's full log and JSON are saved as an artifact
(`booking-test-<run>-<attempt>`), and a results table is on the run's summary page.

Same request as from the Mac: plain Python `requests`, honest User-Agent, no cookies,
sequential, 5–10 s apart. See `docs/booking-endpoints.md`.

## Status (13 Nov 2026): works from GitHub; daily workflow live

**Outcome so far: works from GitHub.** Both GitHub runs got HTTP 200 JSON for every request,
with no challenge, no 202/403/429, no `x-amzn-waf-action` header and no non-JSON body.
Ashley chose to go live after these runs rather than wait for two more test runs, so the
daily workflow is running; its first scheduled runs serve as the remaining evidence.

## Runs

| Run (UTC start) | Trigger | Options | Requests | Priced | Non-200 / challenge | CloudFront POP | Run |
|---|---|---|---|---|---|---|---|
| 2026-11-13 22:35 | manual | 3 test | 4 | 3 / 3 | none | PHX52 (Phoenix) | [43520554187](https://github.com/AshleyBlanche1/Japan-hotel-prices/actions/runs/43520554187) |
| 2026-11-13 22:36 | manual | 21 | 26 | **19 / 21** | none | SFO5 (San Francisco) | [43520706155](https://github.com/AshleyBlanche1/Japan-hotel-prices/actions/runs/43520706155) |

Every response had `server: istio-envoy`, `via: … cloudfront.net (CloudFront)` and the same
five set-cookie names as from the Mac (`bkng`, `bkng_sso_auth`, `pcm_consent`,
`persisted_currency`, `persisted_lang`). The script refuses all cookies, so none were sent back.

### Unpriced options in the 22:36 run

| Option | GitHub | Mac | Notes |
|---|---|---|---|
| tokyo-1-1-hotel-tokyo (8–12 Aug) | sold out | sold out | Genuine: the website says "We have no availability on our site for this property" for these dates. |
| tokyo-2-jw-marriott-hotel-tokyo (19–21 Aug) | sold out | **£932.00**, free cancellation (Mac, 22:41, a few minutes later) | GitHub's runners are in the US; Booking.com may offer a different inventory to US visitors, or this was a momentary gap. Watch the daily runs; if it repeats, a manual test run with "all" ticked logs the full response bodies. |

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

**Works from GitHub: daily workflow live** (Ashley's decision on 13 Nov, after the runs above,
instead of waiting for three 21-option test runs).

`.github/workflows/booking-daily.yml` runs at 05:30 UTC every day (and on demand), writes
`data/booking_latest.json` and commits it as `Booking.com prices YYYY-MM-DD`. The run is
marked **failed**, which makes GitHub send a failed-run notice, when:

- Booking.com still shows a robot check after that run's attempts (HTTP 202, `x-amzn-waf-action`, or a challenge page; see the retry rules below);
- any option has an `error: ...` status (for example a timeout after the one retry);
- fewer than 18 of 21 options are priced;
- the file is not dated today or does not have 21 results;
- the script crashes or the push is rejected.

`sold out` and `non-refundable only` are not errors. The file is committed before the check,
so a bad day is still visible in the data. Each run's summary page shows the 21-row table.

## 15 Nov 2026: first robot check from GitHub, and retries added

| Run (UTC) | Trigger | Requests | Result | Response |
|---|---|---|---|---|
| 2026-11-15 13:54 | manual, `booking-daily.yml` | 1 | **robot check**, 0 of 21 priced | HTTP 202, empty body, `server: CloudFront`, `x-amzn-waf-action: challenge`, POP IAD61 (Virginia) |
| 2026-11-15, shortly after | Mac, 1 option | 1 | priced (JW Marriott £1,806.90) | HTTP 200 JSON, `server: istio-envoy` |
| 2026-11-15 15:00 | manual, `booking-test.yml`, 3 options | 4 | 3 of 3 priced | HTTP 200 JSON, same POP IAD61 |

The challenge came from the CloudFront edge (AWS WAF), not Booking's own servers. The same
edge location let a different GitHub server through an hour later, and the Mac was never
challenged, so this looks like the reputation of that one runner's address (AWS WAF has
managed rules aimed at cloud-hosting addresses), not a new rule for everyone. Other projects
report the same 202 + `x-amzn-waf-action: challenge` from GitHub-hosted runners against other
AWS WAF-protected sites. GitHub runs so far: 5 of 6 succeeded.

Also observed: GitHub starts the scheduled runs very late. The SerpApi run set for 06:23 UTC
started between 13:21 and 16:41 UTC on each of 7–14 Nov; GitHub does not guarantee start times
for scheduled workflows.

**Retries (Ashley's decision, 15 Nov), at most three attempts a day:**

1. Morning run (05:30 UTC schedule).
2. If that is challenged: wait five minutes, then one second attempt on a fresh GitHub server,
   asking only about the options not yet priced (`--retry-robot-check`).
3. Evening run (17:30 UTC schedule, `--evening`): does nothing if today's file has no robot
   check or error; otherwise one more attempt for those options, or a full run if there is no
   file for today. No five-minute retry in the evening.

After that, nothing more is asked until the next day. Each run ends with one pass/fail result
(the `report` job), so each run sends one notification.
