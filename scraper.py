#!/usr/bin/env python3
"""
Futsal Escocia Winter League 2026/27 fixture scraper.

Pulls the complete season schedule for Liga 3 to Liga 7 straight from
LeagueLobster's own schedule backend and writes it to fixtures_data.json.

Liga 3 and Liga 4 play on Sundays; Liga 5, 6 and 7 play on Saturdays. Nothing
here assumes a matchday weekday - dates are read from the feed.

Why there is no browser here
----------------------------
The public page (scheduler.leaguelobster.com/<id>/<slug>/<season>/?mode=full)
ships an *empty* schedule container plus an htmx loader, so anything that reads
the initial DOM - Playwright included - sees zero matches unless it waits for
and wins a race against client-side rendering. That race is what produced
"Captured 0 fixtures across 0 round(s)" in CI.

The loader calls a server-rendered fragment endpoint:

    /schedule/backend/weeks/<season_id>/False/

That one GET returns every week and every match for the season as HTML with the
data we need already in attributes (data-week, data-date, data-formatted-time,
data-teams, data-venue). So this scraper is plain urllib + re from the standard
library: no Playwright, no browser download, no headless flakiness, no
third-party packages.

Dates come from data-date, never from arithmetic. The season has a two-week
Christmas break (off-weeks commencing 2026-12-21 and 2026-12-28), so
"start date + (round - 1) * 7" drifts two weeks late from round 8 onwards.
"""

import datetime
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://scheduler.leaguelobster.com"

# season_id -> league label. The public URL is kept for traceability only.
LEAGUES = [
    ("Liga 3", "2837395", f"{BASE}/2837395/liga-3/winter-2026-27/?mode=full"),
    ("Liga 4", "2837392", f"{BASE}/2837392/liga-4/winter-2026-27/?mode=full"),
    ("Liga 5", "2837382", f"{BASE}/2837382/liga-5/winter-2026-27/?mode=full"),
    ("Liga 6", "2837371", f"{BASE}/2837371/liga-6/winter-2026-27/?mode=full"),
    ("Liga 7", "2837368", f"{BASE}/2837368/liga-7/winter-2026-27/?mode=full"),
]

WEEKS_ENDPOINT = "/schedule/backend/weeks/{season_id}/False/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "en-GB,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

OUTPUT_FILE = os.environ.get("FIXTURES_OUTPUT", "fixtures_data.json")

# Refuse to overwrite a good file with a partial scrape. The five leagues carry
# 975 fixtures; anything under this means the source changed or a request
# failed. The per-league floor is the stricter guard - it catches one league
# dropping out, which a total on its own would hide.
MIN_TOTAL_FIXTURES = 600
MIN_FIXTURES_PER_LEAGUE = 50

REQUEST_ATTEMPTS = 4
REQUEST_TIMEOUT = 90


# ---------------------------------------------------------------- http


def fetch(path):
    """GET a path off BASE with retries and exponential backoff."""
    url = BASE + path
    last_error = None
    for attempt in range(1, REQUEST_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    raise urllib.error.HTTPError(
                        url, response.status, "unexpected status", response.headers, None
                    )
                return response.read().decode("utf-8", errors="replace")
        except Exception as error:  # noqa: BLE001 - retry anything transport-ish
            last_error = error
            print(f"    attempt {attempt}/{REQUEST_ATTEMPTS} failed: "
                  f"{type(error).__name__}: {error}")
            if attempt < REQUEST_ATTEMPTS:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {REQUEST_ATTEMPTS} attempts: {last_error}")


# ---------------------------------------------------------------- parsing

WEEK_SPLIT = re.compile(r'(?=<div class="schedule-week row)')
MATCH_SPLIT = re.compile(r'(?=<div class="schedule-match row)')

WEEK_NUMBER = re.compile(r'data-week="(\d+)"')
VENUE_TEXT = re.compile(r'class="[^"]*venue-dropdown[^"]*">\s*([^<]*)')
TEAM_DISPLAY = re.compile(r'class="team-display">\s*([^<]*)')

ORDINAL_IRREGULAR = {1: "st", 2: "nd", 3: "rd"}


def attribute(blob, name):
    """Read a data attribute out of a tag blob."""
    found = re.search(rf'{re.escape(name)}="([^"]*)"', blob)
    return found.group(1).strip() if found else ""


def clean(text):
    """Unescape HTML entities and collapse whitespace."""
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def format_match_date(iso_date):
    """2026-11-07 -> 'Sat 7th Nov 2026'.

    The weekday comes from the date itself rather than being hardcoded to
    'Sat', so a rescheduled midweek match still renders honestly.
    """
    date = datetime.date.fromisoformat(iso_date)
    day = date.day
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = ORDINAL_IRREGULAR.get(day % 10, "th")
    return f"{date.strftime('%a')} {day}{suffix} {date.strftime('%b %Y')}"


def team_name_after(block, marker):
    """First .team-display text following `marker` inside a match block.

    Targeting the home/away team-wrapper means we read the semantic home and
    away sides, and never the team names that also appear in the match's
    forfeit menu (.forfeit-team-display).
    """
    start = block.find(marker)
    if start == -1:
        return ""
    found = TEAM_DISPLAY.search(block, start)
    return clean(found.group(1)) if found else ""


def parse_match(block, league, round_number):
    """Turn one .schedule-match block into a fixture dict, or None to skip."""
    tag = block[: block.find(">") + 1] if ">" in block else block[:600]

    # Placeholder/bye rows carry data-no-match="True".
    if attribute(tag, "data-no-match").lower() == "true":
        return None

    iso_date = attribute(tag, "data-date")
    if not iso_date:
        return None

    time_text = clean(attribute(tag, "data-formatted-time")) or clean(
        attribute(tag, "data-time")
    )

    home = team_name_after(block, "team-wrapper home-team")
    away = team_name_after(block, "team-wrapper away-team")
    if not home or not away:
        return None

    venue_match = VENUE_TEXT.search(block)
    venue = clean(venue_match.group(1)) if venue_match else ""

    return {
        "league": league,
        "round": round_number,
        "date": format_match_date(iso_date),
        "iso_date": iso_date,
        "venue": venue or "TBD",
        "time": time_text or "TBD",
        "homeTeam": home,
        "awayTeam": away,
        "match_id": attribute(tag, "data-match"),
        "raw_fixture": " ".join(
            part for part in [venue, time_text, f"{home} V {away}"] if part
        ),
    }


def parse_season(markup, league):
    """Extract every fixture for one league, in schedule order."""
    fixtures = []
    off_weeks = 0

    for week_block in WEEK_SPLIT.split(markup)[1:]:
        header = week_block[: week_block.find(">") + 1]

        # Off-weeks (e.g. the Christmas break) carry data-off-week and no
        # matches. They must not consume a round number.
        if "data-off-week" in header:
            off_weeks += 1
            continue

        week_number = WEEK_NUMBER.search(header)
        if not week_number:
            continue
        round_number = int(week_number.group(1))

        for match_block in MATCH_SPLIT.split(week_block)[1:]:
            fixture = parse_match(match_block, league, round_number)
            if fixture:
                fixtures.append(fixture)

    if off_weeks:
        print(f"    {off_weeks} off-week(s) skipped (no matches scheduled)")
    return fixtures


# ---------------------------------------------------------------- driver


def scrape_league(league, season_id, public_url):
    print(f"\n{'=' * 60}\n{league}  (season {season_id})\n{'=' * 60}")
    print(f"  source: {public_url}")
    path = WEEKS_ENDPOINT.format(season_id=season_id)
    print(f"  fetching: {BASE}{path}")

    markup = fetch(path)
    print(f"  received {len(markup):,} characters")

    fixtures = parse_season(markup, league)
    rounds = sorted({fixture["round"] for fixture in fixtures})
    print(f"  parsed {len(fixtures)} fixtures across {len(rounds)} round(s)")
    if fixtures:
        print(f"  rounds {rounds[0]}-{rounds[-1]} | "
              f"{fixtures[0]['date']} -> {fixtures[-1]['date']}")
    return fixtures


def main():
    all_fixtures = []
    per_league = {}
    failures = []

    for league, season_id, public_url in LEAGUES:
        try:
            fixtures = scrape_league(league, season_id, public_url)
        except Exception as error:  # noqa: BLE001 - one league must not kill the run
            print(f"  ERROR scraping {league}: {type(error).__name__}: {error}")
            failures.append(league)
            continue

        per_league[league] = len(fixtures)
        all_fixtures.extend(fixtures)

    # Stable ids, assigned per league in schedule order (liga5-1, liga5-2, ...).
    counters = {}
    for fixture in all_fixtures:
        slug = fixture["league"].lower().replace(" ", "")
        counters[slug] = counters.get(slug, 0) + 1
        fixture["id"] = f"{slug}-{counters[slug]}"

    print(f"\n{'=' * 60}\nSUMMARY\n{'=' * 60}")
    for league, _season_id, _url in LEAGUES:
        print(f"  {league}: {per_league.get(league, 0)} fixtures")
    print(f"  TOTAL: {len(all_fixtures)} fixtures")

    # Validate before touching the file, so a partial scrape can never truncate
    # a known-good fixtures_data.json the way earlier runs did.
    problems = []
    if failures:
        problems.append(f"league(s) failed to scrape: {', '.join(failures)}")
    if len(all_fixtures) < MIN_TOTAL_FIXTURES:
        problems.append(
            f"only {len(all_fixtures)} fixtures (expected at least {MIN_TOTAL_FIXTURES})"
        )
    for league, _season_id, _url in LEAGUES:
        count = per_league.get(league, 0)
        if count < MIN_FIXTURES_PER_LEAGUE:
            problems.append(
                f"{league} has {count} fixtures "
                f"(expected at least {MIN_FIXTURES_PER_LEAGUE})"
            )

    if problems:
        print("\nAborting without writing - sanity checks failed:")
        for problem in problems:
            print(f"  - {problem}")
        print(f"{OUTPUT_FILE} left untouched.")
        return 1

    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(all_fixtures, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"\nWrote {len(all_fixtures)} fixtures to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
