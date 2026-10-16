import json
import asyncio
import re
from playwright.async_api import async_playwright

# Verified working URLs from earlier
urls = {
    "Liga 5": "https://futsalescocia.co.uk/fixtures/liga-5/",
    "Liga 6": "https://futsalescocia.co.uk/fixtures/liga-6/",
    "Liga 7": "https://futsalescocia.co.uk/fixtures/liga-7/"
}

date_regex = r'((?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?)'

def parse_fixture_text(text):
    # Match time format (e.g. 9:00 AM)
    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', text, re.I)
    time_str = time_match.group(1) if time_match else "TBD"
    
    if time_match:
        parts = text.split(time_match.group(1), 1)
        venue_raw = parts[0].strip()
        teams_part = parts[1].strip()
    else:
        venue_raw = "TBD"
        teams_part = text

    # Extract date if prepended to venue
    date_match = re.search(date_regex, venue_raw, re.I)
    if date_match:
        date_str = date_match.group(1).strip()
        venue = venue_raw.replace(date_match.group(1), "").strip()
        venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue)
    else:
        date_str = "Upcoming"
        venue = venue_raw

    # Split home and away teams by ' V ' or ' VS '
    teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
    home_team = teams[0].strip() if len(teams) > 0 else "TBD"
    away_team = teams[1].strip() if len(teams) > 1 else "TBD"

    # Clean away team if a trailing time or text sneaked in
    away_team = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away_team).strip()

    return {
        "date": date_str,
        "venue": venue or "TBD",
        "time": time_str,
        "homeTeam": home_team,
        "awayTeam": away_team
    }

async def scrape_league(page, league_name, url):
    print(f"Scraping {league_name} from {url}...")
    fixtures = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=45000)
        
        # Access embedded iframe
        iframe_element = await page.query_selector("iframe")
        target = page
        if iframe_element:
            frame = await iframe_element.content_frame()
            if frame:
                target = frame

        await target.wait_for_selector(".match, .game, table, tr", timeout=25000)
        
        # Query individual rows and date headings only
        elements = await target.query_selector_all("h2, h3, h4, th, tr, .match, .game-row")

        current_date = "Upcoming"

        for el in elements:
            text = await el.inner_text()
            clean_text = " ".join(text.split())
            
            # Skip empty or standings rows (e.g. 0 0 0 0 0 0)
            if not clean_text or re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
                continue

            # Identify if it's a match fixture
            if re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text):
                parsed = parse_fixture_text(clean_text)
                match_date = parsed["date"] if parsed["date"] != "Upcoming" else current_date
                
                fixtures.append({
                    "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                    "league": league_name,
                    "date": match_date,
                    "venue": parsed["venue"],
                    "time": parsed["time"],
                    "homeTeam": parsed["homeTeam"],
                    "awayTeam": parsed["awayTeam"],
                    "raw_fixture": clean_text
                })
            else:
                # Capture date or round if found on a heading line
                if re.search(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Round|Week|\d{1,2}[/-]\d{1,2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', clean_text, re.I):
                    current_date = clean_text

        print(f"Successfully scraped {len(fixtures)} fixtures for {league_name}")

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
        for league_name, url in
