import json
import asyncio
import re
from playwright.async_api import async_playwright

urls = {
    "Liga 5": "https://futsalescocia.co.uk/fixtures/liga-5/",
    "Liga 6": "https://futsalescocia.co.uk/fixtures/liga-6/",
    "Liga 7": "https://futsalescocia.co.uk/fixtures/liga-7/"
}

async def scrape_league(page, league_name, url):
    print(f"Loading {league_name}...")
    fixtures = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=35000)
        
        # Target the embedded iframe
        iframe_element = await page.query_selector("iframe")
        target = page
        if iframe_element:
            frame = await iframe_element.content_frame()
            if frame:
                target = frame

        # Wait for schedule elements to render
        await target.wait_for_selector(".match, .game, table, tr", timeout=20000)
        
        # Grab all text elements inside the schedule container
        elements = await target.query_selector_all("tr, .match, .game-row, div[class*='match']")
        
        for idx, el in enumerate(elements):
            text = await el.inner_text()
            clean_text = " ".join(text.split())
            
            # Filter out Standings/Rankings (e.g., "0 0 0 0 0 0") and keep actual Match Fixtures
            if clean_text and not re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
                # Ensure it contains match indicators like 'vs', 'v', or time format '10:00'
                if re.search(r'\b(vs?|v)\b', clean_text, re.I) or re.search(r'\d{1,2}:\d{2}', clean_text):
                    fixtures.append({
                        "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                        "league": league_name,
                        "raw_fixture": clean_text
                    })
    except Exception as e:
        print(f"Notice for {league_name}: {e}")
        
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
            
        print(f"Scraping complete! Extracted {len(all_data)} fixture records.")

if __name__ == "__main__":
    asyncio.run(main())
