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

# Whose fixtures are worth being told about. Everything is scraped and shown;
# only these raise an alert, or every rescheduling in five leagues would.
OUR_CLUB = "tiki taka"

# Changes are not marked on the page until this close to a league's first game.
PRESEASON_QUIET_DAYS = 7


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


# ------------------------------------------------------------------ changes


def load_previous(path):
    """Last run's fixtures, keyed by LeagueLobster's own match id.

    The match id is the only identity that survives a rescheduling: keying on
    the teams or the round would read a changed fixture as one removed and
    another added.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            previous = json.load(handle)
    except (OSError, ValueError):
        return {}
    return {f["match_id"]: f for f in previous if f.get("match_id")}


def is_ours(fixture):
    return (OUR_CLUB in fixture["homeTeam"].lower()
            or OUR_CLUB in fixture["awayTeam"].lower())


def our_team_in(fixture):
    for side in ("homeTeam", "awayTeam"):
        if OUR_CLUB in fixture[side].lower():
            return fixture[side]
    return ""


def describe_changes(previous, fixtures):
    """What moved for our teams since the last run, as {match_id: detail}."""
    moved = {}
    for fixture in fixtures:
        if not is_ours(fixture):
            continue
        was = previous.get(fixture["match_id"])
        if not was:
            continue

        notes = []
        if was.get("iso_date") != fixture["iso_date"]:
            notes.append(f"{was.get('date')} -> {fixture['date']}")
        if was.get("time") != fixture["time"]:
            notes.append(f"{was.get('time')} -> {fixture['time']}")
        if was.get("venue") != fixture["venue"]:
            notes.append(f"{was.get('venue')} -> {fixture['venue']}")
        if (was.get("homeTeam"), was.get("awayTeam")) != \
                (fixture["homeTeam"], fixture["awayTeam"]):
            notes.append(f"now {fixture['homeTeam']} v {fixture['awayTeam']}")

        if notes:
            moved[fixture["match_id"]] = ", ".join(notes)
    return moved


def short_name(team):
    return team.replace("Tiki Taka ", "")


def our_teams_in(fixture):
    return [fixture[side] for side in ("homeTeam", "awayTeam")
            if OUR_CLUB in fixture[side].lower()]


def find_redrawn_leagues(previous, fixtures):
    """Leagues whose schedule was thrown away and published again.

    A redraw gives every match a new id, so describe_changes - which follows
    a fixture by its id - sees nothing at all. Most of a league's ids
    vanishing in one go is the tell. 26 Oct 2026 redrew Liga 5 and Liga 6
    this way and 101 of our fixtures changed without an alert or a badge.
    """
    current_ids = {f["match_id"] for f in fixtures}
    totals, kept = {}, {}
    for match_id, was in previous.items():
        league = was.get("league")
        totals[league] = totals.get(league, 0) + 1
        if match_id in current_ids:
            kept[league] = kept.get(league, 0) + 1
    return {league for league, total in totals.items()
            if total >= MIN_FIXTURES_PER_LEAGUE and kept.get(league, 0) * 2 < total}


def describe_replacements(previous, fixtures, redrawn):
    """Our fixtures that appeared or vanished, rather than moved.

    Returns ({match_id: badge detail}, [push lines]). An old fixture is paired
    with its replacement by squad and date - a squad is (team, league), and
    no squad plays twice on one day. Unpaired old ones were removed, unpaired
    new ones are new. Only future games count. Nothing is reported on the
    first run, when there is no previous file to compare with.
    """
    if not previous:
        return {}, []
    today = datetime.date.today().isoformat()
    current_ids = {f["match_id"] for f in fixtures}
    known_leagues = {was.get("league") for was in previous.values()}

    gone = {}
    for match_id, was in previous.items():
        if match_id in current_ids or was.get("iso_date", "") < today:
            continue
        for team in our_teams_in(was):
            gone[(team, was["league"], was["iso_date"])] = was

    badges, lines = {}, []
    for fixture in fixtures:
        if (fixture["match_id"] in previous or fixture["league"] not in known_leagues
                or fixture["iso_date"] < today or not is_ours(fixture)):
            continue
        teams = our_teams_in(fixture)
        keys = [(team, fixture["league"], fixture["iso_date"]) for team in teams]
        olds = [gone.pop(key, None) for key in keys]

        prefix = "League redrawn" if fixture["league"] in redrawn else "Rearranged"
        now = f"{fixture['homeTeam']} v {fixture['awayTeam']}, {fixture['time']}"
        describe = lambda was: (f"{was['homeTeam']} v {was['awayTeam']}, "
                                f"{was['time']}, {was['venue']}")
        if not any(olds):
            badges[fixture["match_id"]] = f"{prefix} - new fixture"
            line = f"new fixture {fixture['date']}: {now}, {fixture['venue']}"
        elif len(teams) > 1:
            # Two of our squads now meet, and each had its own game before -
            # the 26 Oct redraw turned Blanco v DACC Whites and Negra v Blue
            # Brazil into Blanco v Negra. Name both, or one squad's parents
            # read only the other squad's old game.
            then = "; ".join(
                f"{short_name(team)} was {describe(was)}" if was
                else f"{short_name(team)} had no game that day"
                for team, was in zip(teams, olds))
            badges[fixture["match_id"]] = f"{prefix} - {then}"
            line = f"{fixture['date']} now {now}, {fixture['venue']} ({then})"
        else:
            was = olds[0]
            if all(was.get(k) == fixture[k]
                   for k in ("homeTeam", "awayTeam", "time", "venue")):
                continue
            then = describe(was)
            badges[fixture["match_id"]] = f"{prefix} - was {then}"
            line = f"{fixture['date']} now {now}, {fixture['venue']} (was {then})"
        if fixture["league"] not in redrawn:
            lines.append(f"{short_name(teams[0])} ({fixture['league']}): {line}")

    removed = {}
    for (team, league, _date), was in gone.items():
        removed.setdefault(was["match_id"], (team, was))
    for team, was in sorted(removed.values(), key=lambda pair: pair[1]["iso_date"]):
        lines.append(f"{short_name(team)} ({was['league']}): REMOVED {was['date']} "
                     f"{was['homeTeam']} v {was['awayTeam']}, {was['time']}")
    return badges, lines


def redraw_summary(fixtures, redrawn):
    """One push line per squad in a redrawn league, naming its next game.

    Listing every fixture of a redraw would run past what a phone shows - the
    first one moved over a hundred of ours - so this says what happened and
    leaves the detail to the badged page.
    """
    today = datetime.date.today().isoformat()
    first = {}
    for fixture in fixtures:
        if fixture["league"] not in redrawn or fixture["iso_date"] < today:
            continue
        for team in our_teams_in(fixture):
            squad = (team, fixture["league"])
            if squad not in first or fixture["iso_date"] < first[squad]["iso_date"]:
                first[squad] = fixture

    lines = []
    for league in sorted(redrawn):
        lines.append(f"{league} has been redrawn - every fixture is new. Check your games.")
        for (team, squad_league), fixture in sorted(first.items()):
            if squad_league != league:
                continue
            opponent = (fixture["awayTeam"] if fixture["homeTeam"] == team
                        else fixture["homeTeam"])
            lines.append(f"{short_name(team)} ({league}) first game: {fixture['date']}, "
                         f"{fixture['time']} v {opponent}")
    return lines


def carry_flags(previous, fixtures, moved):
    """Mark changed fixtures, keeping earlier marks until the game is played.

    A later quiet run would otherwise clear the badge while the fixture is
    still the rearranged one. Once it has been played the mark is dropped, so
    old changes do not accumulate across a season.
    """
    today = datetime.date.today().isoformat()

    # Before a league's first game the draw is still being shuffled - it was
    # redrawn twice in the fortnight before 2026/27 began - and a page full of
    # notes about a draft nobody played is noise. Notes start a week out,
    # counted per league because Liga 3 and 4 open on a Sunday. Pushes are
    # not held back; only the page notes are.
    first_game = {}
    for fixture in fixtures:
        league, date = fixture["league"], fixture["iso_date"]
        if league not in first_game or date < first_game[league]:
            first_game[league] = date
    notes_from = {
        league: (datetime.date.fromisoformat(date)
                 - datetime.timedelta(days=PRESEASON_QUIET_DAYS)).isoformat()
        for league, date in first_game.items()
    }

    for fixture in fixtures:
        if today < notes_from[fixture["league"]]:
            continue
        detail = moved.get(fixture["match_id"])
        if not detail:
            was = previous.get(fixture["match_id"]) or {}
            detail = was.get("updated")
        if detail and fixture.get("iso_date", "") >= today:
            fixture["updated"] = detail


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


def emit_action_output(**values):
    """Hand results to the workflow step that decides whether to alert."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


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

    previous = load_previous(OUTPUT_FILE)
    moved = describe_changes(previous, all_fixtures) if previous else {}
    redrawn = find_redrawn_leagues(previous, all_fixtures)
    replaced, replacement_lines = describe_replacements(previous, all_fixtures, redrawn)
    carry_flags(previous, all_fixtures, {**replaced, **moved})

    lines = redraw_summary(all_fixtures, redrawn)
    for fixture in all_fixtures:
        if fixture["match_id"] in moved:
            team = short_name(our_team_in(fixture))
            lines.append(f"{team} ({fixture['league']}): {moved[fixture['match_id']]}")
    lines.extend(replacement_lines)

    if lines:
        print("\nChanged since the last run:")
        for line in lines:
            print(f"  {line}")
        # A redraw is a different kind of news from a moved kick-off, so it
        # gets its own headline on the phone.
        title = "FUTSAL LEAGUE REDRAWN" if redrawn else "FUTSAL FIXTURE CHANGE"
        emit_action_output(changed="true", title=title, changes=" | ".join(lines))
    else:
        emit_action_output(changed="false", title="", changes="")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(all_fixtures, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"\nWrote {len(all_fixtures)} fixtures to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
