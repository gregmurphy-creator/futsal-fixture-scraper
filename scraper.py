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

async def scrape_league(page, league_name, url):
    print(f"\n--- Scraping {league_name} ({url}) ---")
    fixtures = []
    
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    
    # Wait for the iframe
    iframe_element = await page.wait_for_selector("iframe", timeout=30000)
    target = page
    if iframe_element:
        frame = await iframe_element.content_frame()
        if frame:
            target = frame

    await target.wait_for_selector("table, tr, .match", timeout=25000)
    
    # Query headings, table rows, and match cells in visual order
    elements = await target.query_selector_all("caption, h2, h3, h4, h5, th, tr, .match, .game-row")
    
    current_date = "Upcoming"

    for el in elements:
        raw = await el.inner_text()
        clean_text = " ".join(raw.split())
        
        # Skip empty or standings rows (0 0 0 0 0 0)
        if not clean_text or re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
            continue

        # 1. Update running date whenever a date heading or date string appears
        d_found = re.search(date_regex, clean_text, re.I)
        if d_found:
            current_date = d_found.group(1).strip()
        elif re.search(r'\b(Week|Round)\s*\d+\b', clean_text, re.I) and not re.search(r'\d{1,2}:\d{2}', clean_text):
            current_date = clean_text

        # 2. Check if this row is a match fixture
        is_match = re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text)
        if is_match:
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', clean_text, re.I)
            time_str = time_match.group(1).strip() if time_match else "TBD"

            parts = clean_text.split(time_match.group(1), 1)
            venue_raw = parts[0].strip()
            teams_part = parts[1].strip()

            # Clean venue of any date prefix if it was in the same row
            if d_found:
                venue = venue_raw.replace(d_found.group(1), "").strip()
            else:
                venue = venue_raw
            venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue) or "TBD"

            teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
            home_team = teams[0].strip() if len(teams) > 0 else "TBD"
            away_team = teams[1].strip() if len(teams) > 1 else "TBD"

            away_team = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away_team).strip()

            fixtures.append({
                "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                "league": league_name,
                "date": current_date,  # Uses the inherited date for all matches of that day
                "venue": venue,
                "time": time_str,
                "homeTeam": home_team,
                "awayTeam": away_team,
                "raw_fixture": clean_text
            })

    print(f"Extracted {len(fixtures)} fixtures for {league_name}")
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
        
        print(f"\nTotal fixtures captured: {len(all_data)}")
        
        if len(all_data) == 0:
            raise RuntimeError("0 fixtures scraped. Aborting to protect fixtures_data.json.")

        with open('fixtures_data.json', 'w') as f:
            json.dump(all_data, f, indent=2)
            
        print("Successfully updated fixtures_data.json with inherited dates.")

if __name__ == "__main__":
    asyncio.run(main())
