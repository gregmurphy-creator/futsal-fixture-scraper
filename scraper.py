import json
import asyncio
import re
from playwright.async_api import async_playwright

urls = {
    "Liga 5": "https://futsalescocia.co.uk/fixtures/liga-5/",
    "Liga 6": "https://futsalescocia.co.uk/fixtures/liga-6/",
    "Liga 7": "https://futsalescocia.co.uk/fixtures/liga-7/"
}

def parse_fixture_text(text):
    # Regex to extract Time (e.g., 9:00 AM or 10:30 PM)
    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', text, re.I)
    
    time_str = time_match.group(1) if time_match else "TBD"
    
    # Split text into Venue (before time) and Match Teams (after time)
    if time_match:
        parts = text.split(time_match.group(1), 1)
        venue = parts[0].strip()
        teams_part = parts[1].strip()
    else:
        venue = "TBD"
        teams_part = text

    # Split home and away teams by ' V ' or ' VS '
    teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
    home_team = teams[0].strip() if len(teams) > 0 else "TBD"
    away_team = teams[1].strip() if len(teams) > 1 else "TBD"

    return {
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

        await target.wait_for_selector(".match, .game, table, tr", timeout=20000)
        elements = await target.query_selector_all("tr, .match, .game-row, div[class*='match']")
        
        for el in elements:
            text = await el.inner_text()
            clean_text = " ".join(text.split())
            
            # Filter out Standings tables and retain valid matches
            if clean_text and not re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
                if re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text):
                    parsed = parse_fixture_text(clean_text)
                    fixtures.append({
                        "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                        "league": league_name,
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
            
        print(f"Extraction successful! Cleaned {len(all_data)} fixtures.")

if __name__ == "__main__":
    asyncio.run(main())
