import json
import asyncio
import re
import datetime
import traceback
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

        round_heading = re.search(r'\b(?:Week|Round)\s*(\d+)\b', clean_text, re.I)
        if round_heading and not re.search(r'\d{1,2}:\d{2}', clean_text):
            current_round = int(round_heading.group(1))
            last_minutes = -1
            continue

        if re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text):
            t_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', clean_text, re.I)
            time_str = t_match.group(1).strip() if t_match else "9:00 AM"

            curr_min = time_to_minutes(time_str)
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

async def scrape_league(page, league_name, url):
    print(f"\n==========================================")
    print(f"Scraping {league_name}: {url}")
    print(f"==========================================")
    
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(2000)

    frame_locator = page.frame_locator("iframe").first

    # Target and click 'Reload full schedule'
    try:
        reload_btn = frame_locator.locator("button, a, div, span").filter(has_text="Reload full schedule").first
        if await reload_btn.count() > 0:
            print(f"[{league_name}] Found 'Reload full schedule' button. Clicking...")
            await reload_btn.scroll_into_view_if_needed()
            await reload_btn.click()
            await page.wait_for_timeout(5000)
        else:
            print(f"[{league_name}] 'Reload full schedule' button not found, checking full page...")
    except Exception as e:
        print(f"[{league_name}] Note on reload button: {e}")

    # Gather rows using frame_locator (immune to frame detachment)
    raw_texts = []
    try:
        raw_texts = await frame_locator.locator("caption, h2, h3, h4, th, tr, .match, .game-row").all_inner_texts()
    except Exception as e:
        print(f"[{league_name}] Could not extract from iframe: {e}")

    # Fallback to main page if iframe was empty
    if not raw_texts:
        raw_texts = await page.locator("caption, h2, h3, h4, th, tr, .match, .game-row").all_inner_texts()

    clean_texts = [" ".join(t.split()) for t in raw_texts if t.strip()]
    fixtures = parse_full_schedule(clean_texts, league_name)
    rounds_found = len(set(f["round"] for f in fixtures)) if fixtures else 0
    print(f"[{league_name}] Captured {len(fixtures)} fixtures across {rounds_found} round(s).")
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
                if data:
                    all_data.extend(data)
            except Exception as e:
                print(f"Error scraping {league_name}: {e}")
                traceback.print_exc()

        await browser.close()

        print(f"\n==========================================")
        print(f"Total fixtures captured across all leagues: {len(all_data)}")
        print(f"==========================================")

        if len(all_data) > 0:
            with open('fixtures_data.json', 'w') as f:
                json.dump(all_data, f, indent=2)
            print(f"Successfully wrote {len(all_data)} fixtures to fixtures_data.json!")
        else:
            print("Error: 0 fixtures collected. File left untouched.")

if __name__ == "__main__":
    asyncio.run(main())
