import json
import asyncio
import re
from playwright.async_api import async_playwright

urls = {
    "Liga 5": "https://futsalescocia.co.uk/fixtures/liga-5/",
    "Liga 6": "https://futsalescocia.co.uk/fixtures/liga-6/",
    "Liga 7": "https://futsalescocia.co.uk/fixtures/liga-7/"
}

def parse_fixture(text, fallback_date="Upcoming"):
    # Guard: if this text contains multiple games concatenated together, skip it
    vs_count = len(re.findall(r'\bV(?:S)?\b', text, re.I))
    time_matches = list(re.finditer(r'\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b', text, re.I))
    
    if vs_count > 1 or len(time_matches) > 1:
        return None
    if not time_matches or vs_count == 0:
        return None

    time_match = time_matches[0]
    time_str = time_match.group(0).strip()
    
    before_time = text[:time_match.start()].strip()
    after_time = text[time_match.end():].strip()

    # Extract date if it is prepended to the venue (e.g. "Saturday, November 14 Balwearie High School")
    date_regex = r'((?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?)'
    date_found = re.search(date_regex, before_time, re.I)

    if date_found:
        extracted_date = date_found.group(1).strip()
        venue = before_time.replace(date_found.group(1), "").strip()
    else:
        extracted_date = fallback_date
        venue = before_time

    # Clean up venue text
    venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue) or "TBD"

    # Extract Home & Away teams
    teams = re.split(r'\s+V(?:S)?\s+', after_time, flags=re.I)
    if len(teams) < 2:
        return None

    home_team = teams[0].strip()
    away_team = teams[1].strip()

    # Ensure no leftover times leaked into team names
    away_team = re.sub(r'\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b.*$', '', away_team).strip()

    return {
        "date": extracted_date,
        "venue": venue,
        "time": time_str,
        "homeTeam": home_team,
        "awayTeam": away_team
    }

async def scrape_league(page, league_name, url):
    print(f"Scraping {league_name}...")
    fixtures = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=35000)
        
        iframe_element = await page.query_selector("iframe")
        target = page
        if iframe_element:
            frame = await iframe_element.content_frame()
            if frame:
                target = frame

        await target.wait_for_selector("tr, .match, .game", timeout=20000)
        
        # Select individual match rows only (no round/container divs)
        elements = await target.query_selector_all("tr, .match, .game-row")
        
        for el in elements:
            text = await el.inner_text()
            clean_text = " ".join(text.split())
            
            # Skip standings and blank lines
            if not clean_text or re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
                continue

            parsed = parse_fixture(clean_text)
            if parsed:
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
    except Exception as e:
        print(f"Error on {league_name}: {e}")
        
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
            data = await scrape_league(page, league_name, url)
            all_data.extend(data)
            
        await browser.close()
        
        with open('fixtures_data.json', 'w') as f:
            json.dump(all_data, f, indent=2)
            
        print(f"Scraping complete! Extracted {len(all_data)} clean individual fixtures.")

if __name__ == "__main__":
    asyncio.run(main())
