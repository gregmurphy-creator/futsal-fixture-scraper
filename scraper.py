import requests
from bs4 import BeautifulSoup
import json
import re

# Direct LeagueLobster embedded URLs for Futsal Escocia
league_urls = {
    "Liga 5": "https://scheduler.leaguelobster.com/o/527519/futsal-escocia/",
    "Liga 6": "https://scheduler.leaguelobster.com/o/527519/futsal-escocia/",
    "Liga 7": "https://scheduler.leaguelobster.com/o/527519/futsal-escocia/"
}

# Standard browser request headers
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

scraped_output = {}

for league_name, url in league_urls.items():
    print(f"Fetching data for {league_name}...")
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract text elements and links from schedule container
        page_text = soup.get_text(separator=' ', strip=True)
        
        # Capture raw structured data or embedded links found on schedule page
        scraped_output[league_name] = {
            "source_url": url,
            "status": "Success",
            "content_preview": page_text[:300] if page_text else "No content preview available"
        }
    except Exception as e:
        scraped_output[league_name] = {
            "source_url": url,
            "status": f"Error: {str(e)}"
        }

# Write results to fixtures_data.json
with open('fixtures_data.json', 'w') as f:
    json.dump(scraped_output, f, indent=2)

print("Scraping completed.")
