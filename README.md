# tiki-taka

Parent-facing fixture hub for Tiki Taka youth futsal squads in the Futsal
Escocia Winter League 2026/27 (Fife).

- `scraper.py` pulls the full season for Liga 5, 6 and 7 from LeagueLobster
  into `fixtures_data.json` (standard library only, no browser).
- `index.html` renders it, and is published with GitHub Pages.
- `.github/workflows/scraper.yml` refreshes the data on a schedule.
