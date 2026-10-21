#!/usr/bin/env python3
"""
Pitreavie 7s League fixture scraper.

The league publishes fixtures in a shared OneDrive workbook, adding a new tab
for each Saturday - usually on the Wednesday or Thursday before. This reads
that workbook and writes the newest week's fixtures to pitreavie_data.json.

READ ONLY. Every request here is a GET, and nothing is ever written back to
the workbook. It is the league's document, not ours. If this ever needs
credentials rather than an anonymous share link, they must grant Viewer
access only, so the permission model enforces that rather than this comment.

How the anonymous access works
------------------------------
Fetching the share link follows a redeem redirect chain that sets a FedAuth
cookie granting anonymous read access, and lands on a URL carrying the
document's id as ?sourcedoc={GUID}. Re-using that cookie against

    <site>/_layouts/15/download.aspx?UniqueId=<GUID>

returns the raw .xlsx. An .xlsx is a zip of XML, so it is read here with
zipfile and ElementTree - no third-party packages.

The share URL is read from PITREAVIE_SHARE_URL rather than hardcoded: it
grants view access to the league's workbook and does not belong in a public
repository. In Actions it comes from a repository secret.
"""

import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO

MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

OUTPUT_FILE = os.environ.get("PITREAVIE_OUTPUT", "pitreavie_data.json")
SHARE_URL = os.environ.get("PITREAVIE_SHARE_URL", "").strip()

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

OUR_CLUB = "tiki taka"

# Fixture rows: home in B, "v" in D, away in F, then kick-off, pitch and tier.
COL_HOME, COL_AWAY = "B", "F"
COL_KICKOFF, COL_PITCH, COL_TIER, COL_LAST_PLAYED = "G", "H", "I", "J"


# ------------------------------------------------------------------ download


def open_workbook():
    """Redeem the anonymous share link, then download the .xlsx behind it."""
    if not SHARE_URL:
        raise SystemExit(
            "PITREAVIE_SHARE_URL is not set. It holds the workbook's "
            "view-only share link, kept out of the repository."
        )

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", USER_AGENT), ("Accept", "text/html,*/*")]

    print("Redeeming share link...")
    with opener.open(SHARE_URL, timeout=90) as response:
        landed = response.geturl()
        response.read()

    document_id = re.search(r"sourcedoc=%7B([0-9a-fA-F-]+)%7D", landed) or \
        re.search(r"sourcedoc=\{?([0-9a-fA-F-]+)\}?", landed)
    if not document_id:
        raise SystemExit(f"No sourcedoc id in the landing URL: {landed[:160]}")

    site = landed.split("/_layouts/")[0]
    download = f"{site}/_layouts/15/download.aspx?UniqueId={document_id.group(1)}"
    print(f"Downloading workbook from {urllib.parse.urlparse(download).netloc}...")

    with opener.open(download, timeout=180) as response:
        payload = response.read()

    if payload[:2] != b"PK":
        raise SystemExit(
            "Expected an .xlsx but got "
            f"{len(payload)} bytes starting {payload[:16]!r}. The share link "
            "has probably expired or stopped being anonymous."
        )

    print(f"  {len(payload):,} bytes")
    return zipfile.ZipFile(BytesIO(payload))


# ------------------------------------------------------------------- parsing


def shared_strings(book):
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    table = ET.fromstring(book.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in entry.iter(f"{MAIN_NS}t"))
        for entry in table.findall(f"{MAIN_NS}si")
    ]


def sheet_index(book):
    """Tab name -> worksheet path, in workbook order (newest week first)."""
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    relationships = {
        node.get("Id"): node.get("Target")
        for node in ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    }

    sheets = []
    for sheet in workbook.findall(f".//{MAIN_NS}sheets/{MAIN_NS}sheet"):
        target = relationships.get(sheet.get(f"{REL_NS}id"), "")
        if target:
            sheets.append((sheet.get("name"), "xl/" + target.lstrip("/")))
    return sheets


def read_cells(book, path, strings):
    """Worksheet as {(row, column_letter): text}."""
    worksheet = ET.fromstring(book.read(path))
    cells = {}

    for cell in worksheet.iter(f"{MAIN_NS}c"):
        reference = cell.get("r") or ""
        kind = cell.get("t")
        value_node = cell.find(f"{MAIN_NS}v")
        inline = cell.find(f"{MAIN_NS}is")

        if kind == "s" and value_node is not None:
            try:
                value = strings[int(value_node.text)]
            except (ValueError, IndexError):
                continue
        elif kind == "inlineStr" and inline is not None:
            value = "".join(node.text or "" for node in inline.iter(f"{MAIN_NS}t"))
        elif value_node is not None:
            value = value_node.text
        else:
            continue

        value = re.sub(r"\s+", " ", (value or "")).strip()
        if not value:
            continue

        position = re.match(r"([A-Z]+)(\d+)", reference)
        if position:
            cells[(int(position.group(2)), position.group(1))] = value

    return cells


def is_fixture_tab(name):
    """Fixture tabs start with "Week". Everything else is admin.

    The numbering is not dependable - the workbook has "Week 23 5th September"
    with no dash, "Week  16" with two spaces, and "Week One" through
    "Week Three" spelled out - so tabs are found by prefix and ordered by their
    position in the workbook, where the newest is always first.
    """
    return bool(re.match(r"\s*week\b", name or "", re.I))


def excel_time(value):
    """Excel stores 9am as the fraction 0.375 of a day."""
    try:
        minutes = round(float(value) * 24 * 60)
    except (TypeError, ValueError):
        return str(value or "").strip()

    hour, minute = divmod(minutes % (24 * 60), 60)
    suffix = "AM" if hour < 12 else "PM"
    display = hour % 12 or 12
    return f"{display}:{minute:02d} {suffix}"


def parse_week(cells, tab_name):
    """Fixtures from one week's tab, in sheet order."""
    heading = ""
    for row in range(1, 12):
        text = cells.get((row, "B"), "")
        if re.search(r"week", text, re.I) and re.search(r"\d", text):
            heading = text
            break

    fixtures = []
    for row in sorted({row for row, _ in cells}):
        home = cells.get((row, COL_HOME), "")
        away = cells.get((row, COL_AWAY), "")
        if not home or not away:
            continue
        # Below the grid sit notes and the unavailable-teams list, which have
        # no kick-off time; a real fixture always carries one.
        if not cells.get((row, COL_KICKOFF)):
            continue

        fixtures.append({
            "id": f"{len(fixtures) + 1}",
            "time": excel_time(cells.get((row, COL_KICKOFF))),
            "pitch": cells.get((row, COL_PITCH), "TBC"),
            "tier": cells.get((row, COL_TIER), ""),
            "homeTeam": home,
            "awayTeam": away,
            "lastPlayed": cells.get((row, COL_LAST_PLAYED), ""),
            "isOurs": OUR_CLUB in home.lower() or OUR_CLUB in away.lower(),
        })

    return {"tab": tab_name, "heading": heading or tab_name, "fixtures": fixtures}


# -------------------------------------------------------------------- output


def emit_action_output(**values):
    """Hand results to the workflow step that decides whether to alert."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main():
    previous = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as handle:
                previous = json.load(handle)
        except (OSError, ValueError):
            previous = {}

    book = open_workbook()
    strings = shared_strings(book)
    sheets = sheet_index(book)

    tabs = [name for name, _ in sheets if is_fixture_tab(name)]
    if not tabs:
        raise SystemExit("No tabs starting with 'Week' - the workbook layout changed.")

    newest_tab, newest_path = next((n, p) for n, p in sheets if is_fixture_tab(n))
    week = parse_week(read_cells(book, newest_path, strings), newest_tab)

    if not week["fixtures"]:
        raise SystemExit(
            f"Parsed 0 fixtures from {newest_tab!r}. Refusing to overwrite "
            f"{OUTPUT_FILE}, which would wipe a good file."
        )

    ours = [f for f in week["fixtures"] if f["isOurs"]]
    print(f"\n{week['heading']}")
    print(f"  {len(week['fixtures'])} fixtures, {len(ours)} involving {OUR_CLUB.title()}")
    for fixture in ours:
        print(f"    {fixture['time']:>9}  Pitch {fixture['pitch']:<14} "
              f"{fixture['homeTeam']} v {fixture['awayTeam']}")

    is_new_week = bool(previous) and previous.get("week_tab") != newest_tab
    first_run = not previous

    payload = {
        "updated": datetime.datetime.now(datetime.timezone.utc)
                   .replace(microsecond=0).isoformat(),
        "week_tab": newest_tab,
        "heading": week["heading"],
        "known_tabs": tabs,
        "fixtures": week["fixtures"],
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"\nWrote {len(week['fixtures'])} fixtures to {OUTPUT_FILE}")
    if is_new_week:
        print(f"NEW WEEK: {previous.get('week_tab')!r} -> {newest_tab!r}")

    summary = " | ".join(
        f"{f['homeTeam']} v {f['awayTeam']} - {f['time']}, Pitch {f['pitch']}"
        for f in ours
    ) or "No Tiki Taka fixtures listed this week."

    emit_action_output(
        new_week="true" if is_new_week else "false",
        first_run="true" if first_run else "false",
        week_tab=newest_tab,
        heading=week["heading"],
        our_count=str(len(ours)),
        summary=summary,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
