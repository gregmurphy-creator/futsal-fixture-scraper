import json
import asyncio
import re
from playwright.async_api import async_playwright

urls = {
    "Liga 5": "https://futsalescocia.co.uk/fixtures/liga-5/",
    "Liga 6": "https://futsalescocia.co.uk/fixtures/liga-6/",
    "Liga 7": "https://futsalescocia.co.uk/fixtures/liga-7/"
}

def parse_cell(text, current_date="Upcoming"):
    clean = " ".join(text.split())
    if not clean or len(clean) < 6:
        return None
        
    # Ignore league standings rows (e.g., 0 0 0 0 0 0)
    if re.search(r'\b0\s+0\s+0\s+0\b', clean):
        return None
        
    # Must have a match indicator (V or VS)
    if not re.search(r'\b(vs?|v)\b', clean, re.I):
        return None

    # Must contain a match time (e.g. 9:00 AM, 10:30, 14:00)
    time_match = re.search(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM)?)\b', clean, re.I)
    if not time_match:
        return None

    time_str = time_match.group(1).strip()
    before_time = clean[:time_match.start()].strip()
    after_time = clean[time_match.end():].strip()

    # Detect date in the text prefix if present
    date_regex = r'((?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?)'
    date_found = re.search(date_regex, before_time, re.I)

    if date_found:
        date_val = date_found.group(1).strip()
        venue = before_time.replace(date_found.group(1), "").strip()
    else:
        date_val = current_date
        venue = before_time

    venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue) or "TBD"

    # Split home and away teams
    teams = re.split(r'\s+V(?:S)?\s+', after_time, flags=re.I)
    if len(teams) < 2:
        return None

    home = teams[0].strip()
    away = teams[1].strip()

    # Clean away team trailing text
    away = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away).strip()

    return {
        "date": date_val,
        "venue": venue,
        "time": time_str,
        "homeTeam": home,
        "awayTeam": away
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

        await target.wait_for_selector("table, tr, td, .match, .game", timeout=20000)

        # Query cells (td) and date headings (th, h2, h3, h4) in DOM order
        elements = await target.query_selector_all("th, td, h2, h3, h4, .date, .match, .game")
        
        # Fall back to tr if the page does not use standard td cells
        if not elements or len(elements) < 5:
            elements = await target.query_selector_all("tr, .match, .game-row")

        current_date = "Upcoming"

        for el in elements:
            raw = await el.inner_text()
            text = " ".join(raw.split())
            if not text:
                continue

            # Check if this heading element represents a date
            is_match = re.search(r'\b(vs?|v)\b', text, re.I) and re.search(r'\d{1,2}:\d{2}', text)
            if not is_match:
                if re.search(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Round|Week|\d{1,2}[/-]\d{1,2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', text, re.I):
                    current_date = text

            # Parse fixture cell
            parsed = parse_cell(text, current_date=current_date)
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
            
        print(f"Scraping complete! Extracted {len(all_data)} fixtures.")

if __name__ == "__main__":
    asyncio.run(main())
