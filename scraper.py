import json
import asyncio
import re
from playwright.async_api import async_playwright

urls = {
    "Liga 5": "https://futsalescocia.co.uk/fixtures/liga-5/",
    "Liga 6": "https://futsalescocia.co.uk/fixtures/liga-6/",
    "Liga 7": "https://futsalescocia.co.uk/fixtures/liga-7/"
}

# Matches UK format (7th Nov, Sat 7 Nov), US format (Nov 7), numeric (07/11/2026), or day names (Saturday)
date_patterns = [
    r'(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:\s*,?\s*\d{2,4})?',
    r'(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{2,4})?',
    r'(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b',
    r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b'
]
master_date_regex = re.compile('|'.join(date_patterns), re.I)

async def scrape_league(page, league_name, url):
    print(f"Scraping {league_name} from {url}...")
    fixtures = []
    
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    
    iframe_element = await page.wait_for_selector("iframe", timeout=30000)
    target = page
    if iframe_element:
        frame = await iframe_element.content_frame()
        if frame:
            target = frame

    await target.wait_for_selector("table, tr, .match", timeout=25000)
    
    # Check if a date is present in an active dropdown or round selector
    default_date = "Saturday"
    try:
        round_text = await target.eval_on_selector(
            "select option:checked, .round-name, .active-round, .date-heading",
            "el => el.innerText"
        )
        if round_text:
            m = master_date_regex.search(round_text)
            if m:
                default_date = m.group(0).strip()
    except Exception:
        pass

    # Query all potential heading and row elements
    elements = await target.query_selector_all("caption, h1, h2, h3, h4, h5, th, tr, .match, .game-row, option")
    
    current_date = default_date

    for el in elements:
        raw = await el.inner_text()
        clean_text = " ".join(raw.split())
        
        if not clean_text or re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
            continue

        # Look for date headers
        d_found = master_date_regex.search(clean_text)
        if d_found and not re.search(r'\d{1,2}:\d{2}', clean_text):
            current_date = d_found.group(0).strip()

        # Identify match rows
        is_match = re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text)
        if is_match:
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', clean_text, re.I)
            time_str = time_match.group(1).strip() if time_match else "TBD"

            parts = clean_text.split(time_str, 1)
            venue_raw = parts[0].strip()
            teams_part = parts[1].strip() if len(parts) > 1 else ""

            # Check if this row has its own specific date prefix
            row_date = current_date
            row_d_found = master_date_regex.search(venue_raw)
            if row_d_found:
                row_date = row_d_found.group(0).strip()
                venue_raw = venue_raw.replace(row_d_found.group(0), "").strip()

            venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue_raw) or "TBD"

            teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
            home_team = teams[0].strip() if len(teams) > 0 else "TBD"
            away_team = teams[1].strip() if len(teams) > 1 else "TBD"
            away_team = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away_team).strip()

            fixtures.append({
                "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                "league": league_name,
                "date": row_date,
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
                print(f"Error scraping {league_name}: {e}")
                
        await browser.close()
        
        print(f"Total fixtures captured: {len(all_data)}")
        if len(all_data) > 0:
            with open('fixtures_data.json', 'w') as f:
                json.dump(all_data, f, indent=2)
            print("Successfully updated fixtures_data.json.")

if __name__ == "__main__":
    asyncio.run(main())
