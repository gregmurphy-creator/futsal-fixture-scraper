import json
import asyncio
import re
import datetime
import traceback
from playwright.async_api import async_playwright

urls = {
    "Liga 5": "https://scheduler.leaguelobster.com/2837382/liga-5/winter-2026-27/?mode=full",
    "Liga 6": "https://scheduler.leaguelobster.com/2837371/liga-6/winter-2026-27/?mode=full",
    "Liga 7": "https://scheduler.leaguelobster.com/2837368/liga-7/winter-2026-27/?mode=full"
}

SEASON_START_DATE = datetime.date(2026, 11, 7)

def format_round_date(round_num):
    match_date = SEASON_START_DATE + datetime.timedelta(days=(round_num - 1) * 7)
    day = match_date.day
    if 11 <= (day % 100) <= 13:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"Sat {day}{suf} {match_date.strftime('%b %Y')}"

def time_to_minutes(time_str):
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', str(time_str), re.I)
    if not m:
        return 0
    hr, mn, mer = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if mer == 'PM' and hr != 12:
        hr += 12
    elif mer == 'AM' and hr == 12:
        hr = 0
    return hr * 60 + mn

def parse_full_schedule(raw_texts, league_name):
    fixtures = []
    current_round = 1
    last_minutes = -1
    seen = set()

    for clean_text in raw_texts:
        if not clean_text or re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
            continue

        round_heading = re.search(r'\b(?:Week|Round)\s*(\d+)\b', clean_text, re.I)
        if round_heading and not re.search(r'\d{1,2}:\d{2}', clean_text):
            current_round = int(round_heading.group(1))
            last_minutes = -1
            continue

        if re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text):
            t_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', clean_text, re.I)
            time_str = t_match.group(1).strip() if t_match else "9:00 AM"

            curr_min = time_to_minutes(time_str)
            if last_minutes != -1 and curr_min < last_minutes and (last_minutes - curr_min) > 60:
                current_round += 1
                last_minutes = curr_min
            else:
                if curr_min > last_minutes:
                    last_minutes = curr_min

            parts = clean_text.split(time_str, 1)
            venue_raw = parts[0].strip()
            teams_part = parts[1].strip() if len(parts) > 1 else ""

            venue = re.sub(r'^(?:Week|Round)\s*\d+[\s,\-]*', '', venue_raw, flags=re.I)
            venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue) or "TBD"

            teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
            home = teams[0].strip() if len(teams) > 0 else "TBD"
            away = teams[1].strip() if len(teams) > 1 else "TBD"
            away = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away).strip()

            key = (current_round, time_str, home, away)
            if key not in seen:
                seen.add(key)
                fixtures.append({
                    "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                    "league": league_name,
                    "round": current_round,
                    "date": format_round_date(current_round),
                    "venue": venue,
                    "time": time_str,
                    "homeTeam": home,
                    "awayTeam": away,
                    "raw_fixture": clean_text
                })

    return fixtures

async def scrape_league(page, league_name, url):
    print(f"\n==========================================")
    print(f"Scraping {league_name}: {url}")
    print(f"==========================================")
    
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        print(f"[{league_name}] Page load notice: {e}")

    # Give client-side JS 5 seconds to populate match elements
    await page.wait_for_timeout(5000)

    title = await page.title()
    body_len = await page.evaluate("() => document.body ? document.body.innerText.length : 0")
    print(f"[{league_name}] Page title: '{title}' | Body characters: {body_len}")

    # Extract all single-match containers (div, tr, li, p)
    extracted_texts = await page.evaluate("""() => {
        const results = [];
        const elements = document.querySelectorAll('tr, .game, .match, .fixture, [class*="game"], [class*="match"], [class*="row"], li, div');
        for (const el of elements) {
            const text = el.innerText ? el.innerText.trim() : '';
            if (text && /\\bV(?:S)?\\b/i.test(text) && /\\d{1,2}:\\d{2}/.test(text)) {
                const vCount = (text.match(/\\bV(?:S)?\\b/gi) || []).length;
                if (vCount === 1) {
                    results.push(text.replace(/\\s+/g, ' '));
                }
            }
        }
        if (document.body && document.body.innerText) {
            for (const line of document.body.innerText.split('\\n')) {
                const trimmed = line.trim();
                if (trimmed && /\\bV(?:S)?\\b/i.test(trimmed) && /\\d{1,2}:\\d{2}/.test(trimmed)) {
                    results.push(trimmed.replace(/\\s+/g, ' '));
                }
            }
        }
        return Array.from(new Set(results));
    }""")

    print(f"[{league_name}] Found {len(extracted_texts)} match text candidates.")

    fixtures = parse_full_schedule(extracted_texts, league_name)
    rounds_found = len(set(f["round"] for f in fixtures)) if fixtures else 0
    print(f"[{league_name}] Successfully parsed {len(fixtures)} fixtures across {rounds_found} round(s).")
    return fixtures

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        all_data = []
        for league_name, url in urls.items():
            try:
                data = await scrape_league(page, league_name, url)
                if data:
                    all_data.extend(data)
            except Exception as e:
                print(f"Error scraping {league_name}: {e}")
                traceback.print_exc()

        await browser.close()

        print(f"\n==========================================")
        print(f"Total fixtures captured across all leagues: {len(all_data)}")
        print(f"==========================================")

        if len(all_data) > 0:
            with open('fixtures_data.json', 'w') as f:
                json.dump(all_data, f, indent=2)
            print(f"Successfully wrote {len(all_data)} fixtures to fixtures_data.json!")
        else:
            print("Error: 0 fixtures collected. File left untouched.")

if __name__ == "__main__":
    asyncio.run(main())
