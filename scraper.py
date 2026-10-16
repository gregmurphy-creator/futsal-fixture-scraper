import json
import asyncio
import re
import datetime
from playwright.async_api import async_playwright

urls = {
    "Liga 5": "https://futsalescocia.co.uk/fixtures/liga-5/",
    "Liga 6": "https://futsalescocia.co.uk/fixtures/liga-6/",
    "Liga 7": "https://futsalescocia.co.uk/fixtures/liga-7/"
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

def extract_matches_from_text(row_texts, league_name, week_num, starting_id):
    fixtures = []
    for raw in row_texts:
        clean_text = " ".join(raw.split())
        if not clean_text or re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
            continue

        is_match = re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text)
        if is_match:
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', clean_text, re.I)
            time_str = time_match.group(1).strip() if time_match else "9:00 AM"

            parts = clean_text.split(time_str, 1)
            venue_raw = parts[0].strip()
            teams_part = parts[1].strip() if len(parts) > 1 else ""

            venue = re.sub(r'^(?:Week|Round)\s*\d+[\s,\-]*', '', venue_raw, flags=re.I)
            venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue) or "TBD"

            teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
            home_team = teams[0].strip() if len(teams) > 0 else "TBD"
            away_team = teams[1].strip() if len(teams) > 1 else "TBD"
            away_team = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away_team).strip()

            date_str = format_round_date(week_num)

            fixtures.append({
                "id": f"{league_name.lower().replace(' ', '')}-{starting_id + len(fixtures) + 1}",
                "league": league_name,
                "round": week_num,
                "date": date_str,
                "venue": venue,
                "time": time_str,
                "homeTeam": home_team,
                "awayTeam": away_team,
                "raw_fixture": clean_text
            })
    return fixtures

async def scrape_league(page, league_name, url):
    print(f"\n==========================================")
    print(f"Scraping {league_name}: {url}")
    print(f"==========================================")
    fixtures = []
    seen_matches = set()
    
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    
    # Locate iframe
    iframe_element = await page.wait_for_selector("iframe", timeout=30000)
    target = page
    if iframe_element:
        frame = await iframe_element.content_frame()
        if frame:
            target = frame

    await target.wait_for_selector("table, tr, .match", timeout=25000)

    # 1. Attempt to trigger 'Refresh full schedule' if available
    try:
        full_btn = await target.query_selector("a:has-text('full schedule'), button:has-text('full schedule')")
        if full_btn:
            print(f"[{league_name}] Found 'Full Schedule' button. Clicking...")
            await full_btn.click()
            await page.wait_for_timeout(2500)
    except Exception:
        pass

    # 2. Check if the schedule is paginated by week
    pagination_info = await target.evaluate("""() => {
        const bodyText = document.body.innerText || "";
        const m = bodyText.match(/(?:Week|Round)\\s*(\\d+)\\s*of\\s*(\\d+)/i);
        if (m) {
            return { current: parseInt(m[1], 10), total: parseInt(m[2], 10) };
        }
        return null;
    }""")

    if pagination_info and pagination_info.get("total", 1) > 1:
        total_weeks = pagination_info["total"]
        start_week = pagination_info["current"]
        print(f"[{league_name}] Paginated mode detected: currently Week {start_week} of {total_weeks}")

        for week in range(start_week, total_weeks + 1):
            # Extract matches currently visible
            rows = await target.query_selector_all("table tr, .match, .game-row")
            row_texts = []
            for r in rows:
                txt = await r.inner_text()
                if txt:
                    row_texts.append(txt)

            matches = extract_matches_from_text(row_texts, league_name, week, len(fixtures))
            new_count = 0
            for m in matches:
                key = (m["league"], m["round"], m["time"], m["homeTeam"], m["awayTeam"])
                if key not in seen_matches:
                    seen_matches.add(key)
                    fixtures.append(m)
                    new_count += 1

            print(f"[{league_name}] Week {week}/{total_weeks}: captured {new_count} fixtures")

            if week < total_weeks:
                # Advance to next week: click arrow button or press ArrowRight
                advanced = False

                # Option A: Look for right-chevron or next button
                next_btn = await target.query_selector(
                    "button:has(.fa-chevron-right), a:has(.fa-chevron-right), "
                    "button:has(.fa-angle-right), a:has(.fa-angle-right), "
                    "button:has-text('>'), [aria-label*='next' i]"
                )
                if next_btn:
                    try:
                        await next_btn.click()
                        advanced = True
                    except Exception:
                        pass

                # Option B: Use LeagueLobster's native keyboard navigation (ArrowRight)
                if not advanced:
                    await page.keyboard.press("ArrowRight")
                    advanced = True

                await page.wait_for_timeout(1500)

        print(f"[{league_name}] Done! Total fixtures captured: {len(fixtures)}")
        return fixtures

    # 3. Non-paginated mode (Full season rendered at once, e.g. Liga 7)
    print(f"[{league_name}] Full season view detected. Parsing all rows...")
    elements = await target.query_selector_all("caption, h2, h3, h4, th, tr, .match, .game-row")
    current_round = 1
    last_minutes = -1

    for el in elements:
        raw = await el.inner_text()
        clean_text = " ".join(raw.split())
        
        if not clean_text or re.search(r'\b0\s+0\s+0\s+0\b', clean_text):
            continue

        round_heading = re.search(r'\b(?:Week|Round)\s*(\d+)\b', clean_text, re.I)
        if round_heading and not re.search(r'\d{1,2}:\d{2}', clean_text):
            current_round = int(round_heading.group(1))
            last_minutes = -1
            continue

        is_match = re.search(r'\bV(?:S)?\b', clean_text, re.I) and re.search(r'\d{1,2}:\d{2}', clean_text)
        if is_match:
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', clean_text, re.I)
            time_str = time_match.group(1).strip() if time_match else "9:00 AM"

            # Parse kickoff time
            m_time = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str, re.I)
            if m_time:
                hr, mn, mer = int(m_time.group(1)), int(m_time.group(2)), m_time.group(3).upper()
                curr_minutes = (hr % 12 + (12 if mer == 'PM' else 0)) * 60 + mn
            else:
                curr_minutes = 540

            if last_minutes != -1 and curr_minutes < last_minutes and (last_minutes - curr_minutes) > 60:
                current_round += 1
                last_minutes = curr_minutes
            else:
                if curr_minutes > last_minutes:
                    last_minutes = curr_minutes

            parts = clean_text.split(time_str, 1)
            venue_raw = parts[0].strip()
            teams_part = parts[1].strip() if len(parts) > 1 else ""

            venue = re.sub(r'^(?:Week|Round)\s*\d+[\s,\-]*', '', venue_raw, flags=re.I)
            venue = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', venue) or "TBD"

            teams = re.split(r'\s+V(?:S)?\s+', teams_part, flags=re.I)
            home_team = teams[0].strip() if len(teams) > 0 else "TBD"
            away_team = teams[1].strip() if len(teams) > 1 else "TBD"
            away_team = re.sub(r'\b\d{1,2}:\d{2}.*$', '', away_team).strip()

            date_str = format_round_date(current_round)

            fixtures.append({
                "id": f"{league_name.lower().replace(' ', '')}-{len(fixtures)+1}",
                "league": league_name,
                "round": current_round,
                "date": date_str,
                "venue": venue,
                "time": time_str,
                "homeTeam": home_team,
                "awayTeam": away_team,
                "raw_fixture": clean_text
            })

    print(f"[{league_name}] Done! Extracted {len(fixtures)} fixtures across {current_round} round(s)")
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
        
        print(f"\nTotal fixtures captured across all leagues: {len(all_data)}")
        if len(all_data) > 0:
            with open('fixtures_data.json', 'w') as f:
                json.dump(all_data, f, indent=2)
            print("Successfully updated fixtures_data.json.")
        else:
            print("Warning: 0 fixtures collected. File left unchanged.")

if __name__ == "__main__":
    asyncio.run(main())
