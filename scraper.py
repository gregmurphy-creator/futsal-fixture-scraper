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

def parse_full_schedule(raw_texts, league_name):
    fixtures = []
    current_round = 1
    last_minutes = -1
    seen = set()

    for clean_text in raw_texts:
        if not clean_text or re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
            continue

        # Detect round/week headers if present
        round_heading = re.search(r'\b(?:Week|Round)\s*(\d+)\b', clean_text, re.I)
        if round_heading and not re.search(r'\d{1,2}:\d{2}', clean_text):
            current_round = int(round_heading.group(1))
            last_minutes = -1
            continue

        if re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text):
            t_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', clean_text, re.I)
            time_str = t_match.group(1).strip() if t_match else "9:00 AM"

            curr_min = time_to_minutes(time_str)
            # Roll over to next week when kickoff times drop back to morning
            if last_minutes != -1 and curr_min < last_minutes and (last_minutes - curr_min) > 60:
                current_round += 1
                last_minutes = curr_min
            else:
                if curr_min > last_minutes:
                    last_minutes = curr_min

            parts = clean_text.split(time_str, 1)
            venue_raw = parts[0].strip()
            teams_part = parts[1].strip() if len(parts) > 1 else ""

            venue = re.sub(r'^(?:Week|Round)\s*\d+[\s,\-]*', '', venue_raw, flags=re.I)
            venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue) or "TBD"

            teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
            home = teams[0].strip() if len(teams) > 0 else "TBD"
            away = teams[1].strip() if len(teams) > 1 else "TBD"
            away = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away).strip()

            key = (current_round, time_str, home, away)
            if key not in seen:
                seen.add(key)
                fixtures.append({
                    "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                    "league": league_name,
                    "round": current_round,
                    "date": format_round_date(current_round),
                    "venue": venue,
                    "time": time_str,
                    "homeTeam": home,
                    "awayTeam": away,
                    "raw_fixture": clean_text
                })

    return fixtures

async def get_schedule_frame(page):
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
    frame = await get_schedule_frame(page)
    await frame.wait_for_selector("table, tr, .match", timeout=25000)

    # Click the exact "Reload full schedule" button
    clicked = False
    for scope in [frame, page]:
        for sel in [
            "button:has-text('Reload full schedule')",
            "a:has-text('Reload full schedule')",
            ":has-text('Reload full schedule')"
        ]:
            try:
                btn = await scope.query_selector(sel)
                if btn:
                    print(f"[{league_name}] Found 'Reload full schedule' button! Clicking to expand all weeks...")
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    clicked = True
                    break
            except Exception:
                continue
        if clicked:
            break

    if clicked:
        # Give LeagueLobster 4 seconds to pull and display all weeks
        await page.wait_for_timeout(4000)
        frame = await get_schedule_frame(page)

    # Scrape all rendered elements across the full expanded schedule
    elements = await frame.query_selector_all("caption, h2, h3, h4, th, tr, .match, .game-row")
    raw_texts = []
    for el in elements:
        txt = await el.inner_text()
        if txt:
            raw_texts.append(" ".join(txt.split()))

    fixtures = parse_full_schedule(raw_texts, league_name)
    rounds_found = len(set(f["round"] for f in fixtures)) if fixtures else 0
    print(f"[{league_name}] Captured {len(fixtures)} total fixtures across {rounds_found} round(s).")
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

        print(f"\n==========================================")
        print(f"Total fixtures captured across all leagues: {len(all_data)}")
        print(f"==========================================")
        if len(all_data) > 0:
            with open('fixtures_data.json', 'w') as f:
                json.dump(all_data, f, indent=2)
            print("Successfully updated fixtures_data.json!")
        else:
            print("Error: 0 fixtures collected. File left unchanged.")

if __name__ == "__main__":
    asyncio.run(main())
