import requests
from bs4 import BeautifulSoup
import json

urls = {
    "Liga 5": "https://futsalescocia.co.uk/fixtures/liga-5/",
    "Liga 6": "https://futsalescocia.co.uk/fixtures/liga-6/",
    "Liga 7": "https://futsalescocia.co.uk/fixtures/liga-7/"
}

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

results = {}

for league_name, url in urls.items():
    print(f"Scraping {league_name}...")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        iframe = soup.find('iframe')
        if iframe and 'src' in iframe.attrs:
            results[league_name] = iframe['src']
            print(f"Found iframe for {league_name}: {iframe['src']}")
        else:
            results[league_name] = "No iframe found"
    except Exception as e:
        results[league_name] = f"Error: {str(e)}"

# Save extracted URLs/data to a local JSON file inside the repository
with open('fixtures_data.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Scraping completed and saved to fixtures_data.json.")
