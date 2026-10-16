import json
import asyncio
import re
from playwright.async_api import async_playwright

# Direct LeagueLobster URLs (bypasses WordPress iframe completely)
urls = {
    "Liga 5": "https://scheduler.leaguelobster.com/embedded/2376293/",
    "Liga 6": "https://scheduler.leaguelobster.com/embedded/2376309/",
    "Liga 7": "https://scheduler.leaguelobster.com/embedded/2376344/"
}

date_regex = r'((?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?)'

def parse_fixture(text, current_date="Upcoming"):
    clean = " ".join(text.split())
    if not clean or len(clean) < 6:
        return None
        
    # Skip standings table rows
    if re.search(r'\b0\s+0\s+0\s+0\b', clean):
        return None
        
    # Must contain a match indicator (V or VS)
    if not re.search(r'\b(vs?|v)\b', clean, re.I):
        return None

    # Must contain a match time
    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', clean, re.I)
    if not time_match:
        return None

    time_str = time_match.group(1).strip()
    before_time = clean[:time_match.start()].strip()
    after_time = clean[time_match.end():].strip()

    # Extract date if prepended to venue
    d_found = re.search(date_regex, before_time, re.I)
    if d_found:
        match_date = d_found.group(1).strip()
        venue = before_time.replace(d_found.group(1), "").strip()
    else:
        match_date = current_date
        venue = before_time

    venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue) or "TBD"

    # Split teams
    teams = re.split(r'\s+V(?:S)?\s+', after_time, flags=re.I)
    if len(teams) < 2:
        return None

    home = teams[0].strip()
    away = teams[1].strip()

    # Strip any trailing secondary time
    away = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away).strip()

    if not home or not away:
        return None

    return {
        "date": match_date,
        "venue": venue,
        "time": time_str,
        "homeTeam": home,
        "awayTeam": away
    }

async def scrape_league(page, league_name, url):
    print(f"Scraping {league_name} from {url}...")
    fixtures = []
    
    # Load direct page
    await page.goto(url, wait_until="domcontentloaded", timeout=40000)
    
    # Wait for schedule elements to appear
    await page.wait_for_selector("table, tr, .match, .game", timeout=25000)
    
    elements = await page.query_selector_all("h2, h3, h4, th, tr, .match, .game-row")
    current_date = "Upcoming"

    for el in elements:
        raw = await el.inner_text()
        text = " ".join(raw.split())
        if not text:
            continue

        # Check for date or round headings
        is_match = re.search(r'\b(vs?|v)\b', text, re.I) and re.search(r'\d{1,2}:\d{2}', text)
        if not is_match:
            if re.search(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Round|Week|\d{1,2}[/-]\d{1,2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', text, re.I):
                current_date = text
            continue

        # Parse match row
        parsed = parse_fixture(text, current_date=current_date)
        if parsed:
            fixtures.append({
                "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                "league": league_name,
                "date": parsed["date"],
                "venue": parsed["venue"],
                "time": parsed["time"],
                "homeTeam": parsed["homeTeam"],
                "awayTeam": parsed["awayTeam"],
                "raw_fixture": text
            })
            
    print(f"-> Extracted {len(fixtures)} fixtures for {league_name}")
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
        
        # Guard: Never overwrite data with empty list if scraping fails
        if len(all_data) == 0:
            print("WARNING: No fixtures extracted. Keeping existing data.")
            return

        with open('fixtures_data.json', 'w') as f:
            json.dump(all_data, f, indent=2)
            
        print(f"Done! Successfully wrote {len(all_data)} fixtures to fixtures_data.json.")

if __name__ == "__main__":
    asyncio.run(main())
