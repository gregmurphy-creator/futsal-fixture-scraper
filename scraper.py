import json
import asyncio
import re
import datetime
from playwright.async_api import async_playwright

urls = {
    "Liga 5": "https://futsalescocia.co.uk/fixtures/liga-5/",
    "Liga 6": "https://futsalescocia.co.uk/fixtures/liga-6/",
    "Liga 7": "https://futsalescocia.co.uk/fixtures/liga-7/"
}

SEASON_START_DATE = datetime.date(2026, 11, 7)

def format_round_date(round_num):
    match_date = SEASON_START_DATE + datetime.timedelta(days=(round_num - 1) * 7)
    day = match_date.day
    if 11 <= (day % 100) <= 13:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"Sat {day}{suf} {match_date.strftime('%b %Y')}"

def time_to_minutes(time_str):
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', str(time_str), re.I)
    if not m:
        return 0
    hr, mn, mer = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if mer == 'PM' and hr != 12:
        hr += 12
    elif mer == 'AM' and hr == 12:
        hr = 0
    return hr * 60 + mn

def assign_rounds_by_kickoff_reset(fixtures):
    current_round = 1
    last_minutes = -1
    for f in fixtures:
        curr_min = time_to_minutes(f["time"])
        if last_minutes != -1 and curr_min < last_minutes and (last_minutes - curr_min) > 60:
            current_round += 1
            last_minutes = curr_min
        else:
            if curr_min > last_minutes:
                last_minutes = curr_min
        f["round"] = current_round
        f["date"] = format_round_date(current_round)
    return fixtures

def parse_fixture_text(clean_text, league_name, week_num, fixture_index):
    if not clean_text or re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
        return None

    if re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text):
        t_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', clean_text, re.I)
        time_str = t_match.group(1).strip() if t_match else "9:00 AM"

        parts = clean_text.split(time_str, 1)
        venue_raw = parts[0].strip()
        teams_part = parts[1].strip() if len(parts) > 1 else ""

        venue = re.sub(r'^(?:Week|Round)\s*\d+[\s,\-]*', '', venue_raw, flags=re.I)
        venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue) or "TBD"

        teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
        home = teams[0].strip() if len(teams) > 0 else "TBD"
        away = teams[1].strip() if len(teams) > 1 else "TBD"
        away = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away).strip()

        return {
            "id": f"{league_name.lower().replace(' ', '')}-{fixture_index + 1}",
            "league": league_name,
            "round": week_num,
            "date": format_round_date(week_num),
            "venue": venue,
            "time": time_str,
            "homeTeam": home,
            "awayTeam": away,
            "raw_fixture": clean_text
        }
    return None

async def find_schedule_frame(page):
    await page.wait_for_selector("iframe", timeout=30000)
    for frame in page.frames:
        if "leaguelobster" in frame.url.lower():
            return frame
    iframe_el = await page.query_selector("iframe")
    if iframe_el:
        content = await iframe_el.content_frame()
        if content:
            return content
    return page

async def scrape_league(page, league_name, url):
    print(f"\n==========================================")
    print(f"Scraping {league_name}: {url}")
    print(f"==========================================")
    
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    frame = await find_schedule_frame(page)
    await frame.wait_for_selector("table, tr, .match", timeout=25000)

    try:
        full_schedule_link = await frame.query_selector("a:has-text('full schedule'), button:has-text('full schedule')")
        if full_schedule_link:
            print(f"[{league_name}] Found 'Full Schedule' button. Clicking...")
            await full_schedule_link.click()
            await page.wait_for_timeout(3000)
            frame = await find_schedule_frame(page)
    except Exception as e:
        print(f"[{league_name}] Notice: {e}")

    fixtures = []
    seen = set()

    for week in range(1, 16):
        rows = await frame.query_selector_all("table tr, .match, .game-row")
        row_texts = []
        for r in rows:
            txt = await r.inner_text()
            if txt:
                row_texts.append(txt)

        new_in_week = 0
        for raw in row_texts:
            clean = " ".join(raw.split())
            parsed = parse_fixture_text(clean, league_name, week, len(fixtures))
            if parsed:
                key = (parsed["league"], parsed["time"], parsed["homeTeam"], parsed["awayTeam"])
                if key not in seen:
                    seen.add(key)
                    fixtures.append(parsed)
                    new_in_week += 1

        print(f"[{league_name}] Week {week}: captured {new_in_week} fixtures")

        if new_in_week == 0:
            break

        arrow = await frame.query_selector(
            "button:has(.fa-chevron-right), a:has(.fa-chevron-right), "
            "button:has(.fa-angle-right), a:has(.fa-angle-right), "
            "button:has-text('>'), a:has-text('>'), [aria-label*='next' i]"
        )

        if arrow:
            try:
                await arrow.click()
                await page.wait_for_timeout(1500)
                frame = await find_schedule_frame(page)
            except Exception:
                break
        else:
            break

    # If all fixtures were collected under round 1 (e.g. single-page view like Liga 7)
    if len(fixtures) > 15 and all(f.get("round") == 1 for f in fixtures):
        print(f"[{league_name}] Single-page full schedule detected ({len(fixtures)} matches). Recalculating rounds...")
        fixtures = assign_rounds_by_kickoff_reset(fixtures)

    print(f"[{league_name}] Extracted {len(fixtures)} fixtures across {len(set(f['round'] for f in fixtures))} round(s)")
    return fixtures

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        all_data = []
        for league_name, url in urls.items():
            try:
                data = await scrape_league(page, league_name, url)
                all_data.extend(data)
            except Exception as e:
                print(f"Error scraping {league_name}: {e}")

        await browser.close()

        print(f"\nTotal fixtures captured across all leagues: {len(all_data)}")
        if len(all_data) > 0:
            with open('fixtures_data.json', 'w') as f:
                json.dump(all_data, f, indent=2)
            print("Successfully updated fixtures_data.json!")
        else:
            print("Error: 0 fixtures collected. File left unchanged.")

if __name__ == "__main__":
    asyncio.run(main())
