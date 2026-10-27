# ttfixtures.uk — working notes

Two fixture hubs for Tiki Taka youth teams, published from this one repository
with GitHub Pages at **https://www.ttfixtures.uk**.

| Path | League | Source | Checked |
|---|---|---|---|
| `/futsal/` | Futsal Escocia Winter League, Liga 3–7 | LeagueLobster | every 4 hours |
| `/football/` | Pitreavie 7s, 2017s | a shared OneDrive workbook | hourly, Wed/Thu/Fri |
| `/` | chooser between the two | both JSON feeds | — |

Greg is not a developer. Explain changes in plain terms, describe buttons
rather than internals, and never hand over a step that needs a command line
unless there is no alternative.

## Hard rule: the 7s workbook is read-only

The OneDrive workbook belongs to the league, not to us. **Never write to it**
— not a cell, not a tab, not a rename. Every request in `pitreavie_scraper.py`
is a GET. If it ever needs credentials rather than an anonymous share link,
ask for **Viewer** access only, so the permission model enforces this rather
than the code being correct.

## How each side works

Both scrapers are **standard library only** — no pip install, no browser, no
Playwright. That is deliberate, not an accident of history.

**Futsal (`scraper.py`).** The public LeagueLobster page ships an empty
schedule container and fills it over htmx, so anything reading the initial DOM
sees nothing — that is what made the original Playwright version report
"0 fixtures" in CI. Instead it calls the fragment endpoint the page's own
loader uses:

```
/schedule/backend/weeks/<season_id>/False/
```

One GET per league returns every week and match as HTML with the data already
in attributes. Season ids are in `LEAGUES`.

**7s (`pitreavie_scraper.py`).** Fetching the share link follows a redeem
chain that sets an anonymous `FedAuth` cookie and lands on a URL carrying the
document id as `?sourcedoc={GUID}`. Reusing that cookie against
`<site>/_layouts/15/download.aspx?UniqueId=<GUID>` returns the raw `.xlsx`,
which is a zip of XML, read with `zipfile` + `ElementTree`.

## Things that are not obvious and have each caused a bug

**Dates come from the feed, never arithmetic.** The futsal season breaks for
two weeks at Christmas, so `start + (round-1)*7` runs two weeks late from
round 8 on. Round 15 is 27 Feb 2027, not 13 Feb.

**Liga 3 and Liga 4 play Sundays**; Liga 5, 6 and 7 play Saturdays. Nothing
may assume a matchday weekday. The quick-view filters work in *weekends*
rather than single days, or a Sunday-only child sees an empty list every time
the soonest fixture is a Saturday.

**A squad is `(team, league)`, never a team name.** "Tiki Taka Blanco" fields
four separate squads across Liga 4, 5, 6 and 7, each with its own season.
Matching on the name alone mixes different sets of children together.

**7s tab names are inconsistent** — `Week 23 5th September` with no dash,
`Week  16` with two spaces, `Week One`–`Week Three` spelled out. Find tabs by
the `Week` prefix and take the newest by *position* (the league always inserts
it first), never by parsing the number.

**The 7s heading sits below notices that also mention weeks.** One read
"Rota for last 5 weeks will be 1,2,3…" and was taken as the heading. The
matcher now needs `Week` immediately followed by its number, on a short line.

**The availability tab abbreviates months** (`Week 30 24th Oct`) where fixture
tabs spell them out (`17th October`). Month names are matched on prefix.

**The availability tab is filled in before fixtures are drawn**, so it already
knows which of our teams play next Saturday. That is what powers the "This
Saturday" placeholders while the league has published nothing.

**A futsal league can be redrawn, not just rearranged.** On 26 Oct 2026
LeagueLobster replaced Liga 5 and 6 wholesale: every match got a new id, so
following fixtures by id saw nothing and 101 of ours changed with no push and
no badge. Now a league losing most of its ids at once is treated as redrawn
(its own `FUTSAL LEAGUE REDRAWN` push, one line per squad), and any of our
fixtures that appears or vanishes is paired by squad and date, badged, and
pushed — including a match simply removed.

**Excel stores 9am as `0.375`.** Kick-offs are day fractions. Pitches are not
always numbers — some read `1 - New Astro`.

## Alerting

**GitHub's own notifications do not reach Greg.** A bot-raised issue produced
no email, and assigning it to him directly produced none either. Do not build
alerting on issues, watching or mentions. Workflow-*failure* emails do arrive,
so they work as a safety net for genuine errors. The 7s workflow used to raise
a weekly issue as well; it was removed, and the workflow no longer has
`issues: write`.

Alerts go by **ntfy** push instead, to the topic in the `NTFY_TOPIC` secret.
Two kinds, deliberately distinguishable: a new week (normal priority), and a
fixture change (warning tag, high priority). Only our own teams raise a push —
every rescheduling across five leagues would be noise.

## Rules the scrapers follow

**Never overwrite a good file with a partial scrape.** Both abort without
writing if the sanity checks fail. This is why a broken run leaves the site
on yesterday's data rather than wiping it.

**Only write when the content actually changed.** The 7s payload carries an
`updated` stamp; comparing *with* it would rewrite the file every run and
commit roughly 500 times a month for nothing. Compare ignoring that field.

**Retry transient failures, never a verdict.** Four attempts with backoff for
a reset connection; no retry for a missing share link or a response that is
not a workbook, which will not improve on a second go.

**Changed fixtures stay badged until played.** The flag is carried forward on
later quiet runs, or the next check clears the badge minutes after it appears.
A new week starts clean.

**No futsal badges until a week before each league's first game.** Before
2026/27 began the draw was redrawn and reshuffled repeatedly, and Greg had the
resulting 130 notes cleared as noise. Badges start 7 days before a league's
earliest fixture (Liga 3/4 open a day after 5–7); pushes are not held back.

## Secrets and configuration

| Secret | What it is |
|---|---|
| `PITREAVIE_SHARE_URL` | the workbook's view-only share link — grants read access, so it is kept out of the repo |
| `NTFY_TOPIC` | the ntfy topic; anyone holding it receives these alerts and can send one |
| `GITHUB_TOKEN` | provided by Actions, nothing to set |

`CNAME` holds `www.ttfixtures.uk`. DNS is four A records and four AAAA on the
apex plus a `www` CNAME — see `HANDOVER.md`.

## Verifying a change

There is no test suite. What has actually caught bugs:

1. Run the scraper locally with `PITREAVIE_SHARE_URL` set and read its output.
2. Simulate the case — edit the stored JSON to claim a fixture moved, re-run,
   and check the change is described and flagged.
3. Serve the repo (`python3 -m http.server`) and open the page; check the
   console is clean and the layout holds at 375px wide.
4. After pushing, give Pages a few minutes, then confirm the live page, not
   just the commit. From a cloud session this needs `www.ttfixtures.uk` on
   the network allow-list (see `HANDOVER.md`); until then, the "pages build
   and deployment" run in Actions shows the publish went through, and Greg
   checks the page on a phone.

A green workflow run is not proof an alert works: when nothing changed, the
push step is **skipped**, and that is the correct result.
