import json
import asyncio
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
        await page.goto(url, wait_until="networkidle", timeout=30000)
        
        # Check if page embeds an iframe
        iframe_element = await page.query_selector("iframe")
        target = page
        
        if iframe_element:
            frame = await iframe_element.content_frame()
            if frame:
                target = frame

        # Wait for schedule elements/tables to load
        await target.wait_for_selector("table, .game, .match, .fixture-row", timeout=15000)
        
        # Extract rows
        rows = await target.query_selector_all("tr, .game, .match")
        for idx, row in enumerate(rows):
            text = await row.inner_text()
            clean_text = " ".join(text.split())
            if len(clean_text) > 10 and ("vs" in clean_text.lower() or "v" in clean_text.lower() or ":" in clean_text):
                fixtures.append({
                    "id": f"{league_name.lower().replace(' ', '')}-{idx+1}",
                    "league": league_name,
                    "match_info": clean_text
                })
    except Exception as e:
        print(f"Note for {league_name}: {e}")
        
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
            
        print(f"Extraction complete. Saved {len(all_data)} fixtures to fixtures_data.json.")

if __name__ == "__main__":
    asyncio.run(main())
