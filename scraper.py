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

def time_to_minutes(time_str):
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str, re.I)
    if not m:
        return 0
    hr, mn, meridiem = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if meridiem == 'PM' and hr != 12:
        hr += 12
    elif meridiem == 'AM' and hr == 12:
        hr = 0
    return hr * 60 + mn

def extract_matches_from_elements(elements_text, league_name, week_num, starting_id):
    fixtures = []
    for raw in elements_text:
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
    print(f"\nScraping {league_name} ({url})...")
    fixtures = []
    seen_matches = set()
    
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    
    iframe_element = await page.wait_for_selector("iframe", timeout=30000)
    target = page
    if iframe_element:
        frame = await iframe_element.content_frame()
        if frame:
            target = frame

    await target.wait_for_selector("table, tr, .match", timeout=25000)

    # 1. Check if the page is in paginated mode (e.g. "Week 1 of 7" with arrow buttons)
    week_info_el = await target.query_selector("text=/Week\\s+\\d+\\s+of\\s+\\d+/i, text=/Round\\s+\\d+\\s+of\\s+\\d+/i")
    
    if week_info_el:
        txt = await week_info_el.inner_text()
        m = re.search(r'(?:Week|Round)\s*(\d+)\s*of\s*(\d+)', txt, re.I)
        if m:
            start_week = int(m.group(1))
            total_weeks = int(m.group(2))
            print(f"[{league_name}] Detected paginated arrows: currently on Week {start_week} of {total_weeks}")

            curr_week = start_week
            while curr_week <= total_weeks:
                rows = await target.query_selector_all("table tr, .match, .game-row")
                row_texts = [await r.inner_text() for r in rows]
                week_matches = extract_matches_from_elements(row_texts, league_name, curr_week, len(fixtures))
                
                added = 0
                for match in week_matches:
                    key = (match["league"], match["round"], match["time"], match["homeTeam"], match["awayTeam"])
                    if key not in seen_matches:
                        seen_matches.add(key)
                        fixtures.append(match)
                        added += 1

                print(f"[{league_name}] Week {curr_week}/{total_weeks}: captured {added} matches")

                if curr_week >= total_weeks:
                    break

                # Click next arrow button (>)
                clicked = False
                container = await week_info_el.evaluate_handle("el => el.parentElement")
                buttons = await container.query_selector_all("button, a")
                if buttons and len(buttons) > 1:
                    await buttons[-1].click()
                    clicked = True
                    
                if not clicked:
                    next_btn = await target.query_selector("button:has(.fa-chevron-right), a:has(.fa-chevron-right), button:has(.fa-angle-right), a:has(.fa-angle-right), button:has-text('>'), a:has-text('>')")
                    if next_btn:
                        await next_btn.click()
                        clicked = True

                if not clicked:
                    print(f"[{league_name}] No next arrow found after week {curr_week}. Stopping.")
                    break

                curr_week += 1
                try:
                    await target.wait_for_selector(f"text=/Week\\s+{curr_week}\\s+of/i, text=/Round\\s+{curr_week}\\s+of/i", timeout=5000)
                except Exception:
                    await page.wait_for_timeout(1500)

            print(f"[{league_name}] Total captured across all {total_weeks} weeks: {len(fixtures)}")
            return fixtures

    # 2. If NOT paginated (e.g. Liga 7 which renders full season view on one page)
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

            curr_minutes = time_to_minutes(time_str)
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

    print(f"[{league_name}] Extracted {len(fixtures)} fixtures across {current_round} round(s)")
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

if __name__ == "__main__":
    asyncio.run(main())
