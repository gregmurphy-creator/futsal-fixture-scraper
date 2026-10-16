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
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str, re.I)
    if not m:
        return 0
    hr, mn, meridiem = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if meridiem == 'PM' and hr != 12:
        hr += 12
    elif meridiem == 'AM' and hr == 12:
        hr = 0
    return hr * 60 + mn

async def get_active_frame(page):
    await page.wait_for_selector("iframe", timeout=30000)
    for frame in page.frames:
        if "leaguelobster" in frame.url.lower():
            return frame
    iframe_el = await page.query_selector("iframe")
    if iframe_el:
        f = await iframe_el.content_frame()
        if f:
            return f
    return page

async def scrape_league(page, league_name, url):
    print(f"\n--- Loading {league_name}: {url} ---")
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    
    frame = await get_active_frame(page)
    await frame.wait_for_selector("table, tr, .match", timeout=25000)

    # Attempt to expand full schedule
    try:
        full_btn = await frame.query_selector("a:has-text('full schedule'), button:has-text('full schedule'), a:has-text('Reload full schedule')")
        if full_btn:
            print(f"[{league_name}] Triggering full schedule...")
            await full_btn.click()
            await page.wait_for_timeout(3000)
            frame = await get_active_frame(page)
    except Exception as e:
        print(f"[{league_name}] Notice: {e}")

    fixtures = []
    seen = set()

    # Loop through weeks using pagination arrows if present
    for week in range(1, 16):
        rows = await frame.query_selector_all("table tr, .match, .game-row")
        row_texts = [await r.inner_text() for r in rows if await r.inner_text()]

        new_in_week = 0
        for raw in row_texts:
            clean = " ".join(raw.split())
            if not clean or re.search(r'\b0\s+0\s+0\s+0\b', clean):
                continue

            if re.search(r'\bV(?:S)?\b', clean, re.I) and re.search(r'\d{1,2}:\d{2}', clean):
                t_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', clean, re.I)
                time_str = t_match.group(1).strip() if t_match else "9:00 AM"

                parts = clean.split(time_str, 1)
                venue_raw = parts[0].strip()
                teams_part = parts[1].strip() if len(parts) > 1 else ""

                venue = re.sub(r'^(?:Week|Round)\s*\d+[\s,\-]*', '', venue_raw, flags=re.I)
                venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue) or "TBD"

                teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
                home = teams[0].strip() if len(teams) > 0 else "TBD"
                away = teams[1].strip() if len(teams) > 1 else "TBD"
                away = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away).strip()

                key = (league_name, time_str, home, away)
                if key not in seen:
                    seen.add(key)
                    fixtures.append({
                        "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                        "league": league_name,
                        "round": week,
                        "date": format_round_date(week),
                        "venue": venue,
                        "time": time_str,
                        "homeTeam": home,
                        "awayTeam": away,
                        "raw_fixture": clean
                    })
                    new_in_week += 1

        print(f"[{league_name}] Week {week}: found {new_in_week} fixtures")

        # Try advancing with arrow button
        arrow_btn = await frame.query_selector("button:has(.fa-chevron-right), a:has(.fa-chevron-right), button:has-text('>'), a:has-text('>')")
        if arrow_btn and new_in_week > 0:
            try:
                await arrow_btn.click()
                await page.wait_for_timeout(1500)
                frame = await get_active_frame(page)
            except Exception:
                break
        else:
            break

    # If only 1 round was found via arrows (e.g. Liga 7 full single-page schedule),
    # apply kickoff reset tracking to assign subsequent rounds
    if len(fixtures) > 15 and all(f["round"] == 1 for f in fixtures):
        print(f"[{league_name}] Single-page full season detected. Recalculating rounds...")
        current_round = 1
        last_min = -1
        for f in fixtures:
            c_min = time_to_minutes(f["time"])
            if last_min != -1 and c_min < last_min and (last_min - c_min) > 60:
                current_round += 1
                last_min = c_min
            else:
                if c_min > last_min:
                    last_min = c_min
            f["round"] = current_round
            f["date"] = format_round_date(current_round)

    print(f"[{league_name}] Finished with {len(fixtures)} total fixtures.")
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
        
        print(f"\nFinal tally: {len(all_data)} fixtures across all leagues.")
        if len(all_data) > 0:
            with open('fixtures_data.json', 'w') as f:
                json.dump(all_data, f, indent=2)
            print("Successfully updated fixtures_data.json!")
        else:
            print("No fixtures captured. File untouched.")

if __name__ == "__main__":
    asyncio.run(main())
