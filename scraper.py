import json
import asyncio
import re
from playwright.async_api import async_playwright

urls = {
    "Liga 5": "https://futsalescocia.co.uk/fixtures/liga-5/",
    "Liga 6": "https://futsalescocia.co.uk/fixtures/liga-6/",
    "Liga 7": "https://futsalescocia.co.uk/fixtures/liga-7/"
}

date_regex = r'((?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?)'

def parse_fixture_text(text):
    # Match match time (e.g., 9:00 AM)
    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', text, re.I)
    time_str = time_match.group(1) if time_match else "TBD"
    
    if time_match:
        parts = text.split(time_match.group(1), 1)
        venue_raw = parts[0].strip()
        teams_part = parts[1].strip()
    else:
        venue_raw = "TBD"
        teams_part = text

    # Extract date if it appears in the venue portion
    d_match = re.search(date_regex, venue_raw, re.I)
    if d_match:
        date_str = d_match.group(1).strip()
        venue = venue_raw.replace(d_match.group(1), "").strip()
        venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue)
    else:
        date_str = "Upcoming"
        venue = venue_raw

    # Split teams by ' V ' or ' VS '
    teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
    home_team = teams[0].strip() if len(teams) > 0 else "TBD"
    away_team = teams[1].strip() if len(teams) > 1 else "TBD"

    # Clean away team if a trailing time or subsequent fixture text is appended
    away_team = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away_team).strip()

    return {
        "date": date_str or "Upcoming",
        "venue": venue or "TBD",
        "time": time_str,
        "homeTeam": home_team,
        "awayTeam": away_team
    }

async def scrape_league(page, league_name, url):
    print(f"\n--- Loading {league_name} ({url}) ---")
    fixtures = []
    
    # 1. Fast load without hanging on networkidle
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    
    # 2. Wait explicitly for the iframe embed
    print(f"Waiting for iframe on {league_name}...")
    iframe_element = await page.wait_for_selector("iframe", timeout=30000)
    target = page
    
    if iframe_element:
        frame = await iframe_element.content_frame()
        if frame:
            target = frame
            print(f"Connected to iframe content for {league_name}")

    # 3. Wait for the fixture schedule elements inside the iframe
    await target.wait_for_selector("table, tr, .match", timeout=25000)
    
    # 4. Use the proven row selector from the 938-line build
    elements = await target.query_selector_all("tr, .match, .game-row, div[class*='match']")
    print(f"Found {len(elements)} raw elements for {league_name}")

    for el in elements:
        text = await el.inner_text()
        clean_text = " ".join(text.split())
        
        # Filter out empty rows and league standings (0 0 0 0 0 0)
        if clean_text and not re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
            if re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text):
                parsed = parse_fixture_text(clean_text)
                fixtures.append({
                    "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                    "league": league_name,
                    "date": parsed["date"],
                    "venue": parsed["venue"],
                    "time": parsed["time"],
                    "homeTeam": parsed["homeTeam"],
                    "awayTeam": parsed["awayTeam"],
                    "raw_fixture": clean_text
                })

    print(f"Successfully extracted {len(fixtures)} valid matches for {league_name}")
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
                print(f"Exception while scraping {league_name}: {e}")
                
        await browser.close()
        
        print(f"\nTotal matches extracted across all leagues: {len(all_data)}")
        
        # Safety Guard: Never overwrite data with empty list
        if len(all_data) == 0:
            raise RuntimeError("Scraper caught 0 fixtures. Aborting to protect fixtures_data.json.")

        with open('fixtures_data.json', 'w') as f:
            json.dump(all_data, f, indent=2)
            
        print("Successfully saved fresh fixtures to fixtures_data.json.")

if __name__ == "__main__":
    asyncio.run(main())
