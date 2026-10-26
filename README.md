# ttfixtures.uk

Fixture hubs for Tiki Taka youth teams, so parents can see who plays when,
where, and on which pitch — without anyone typing fixtures in.

**https://www.ttfixtures.uk**

| Page | League | What it shows |
|---|---|---|
| [/futsal](https://www.ttfixtures.uk/futsal/) | Futsal Escocia Winter League | the full season, Liga 3 to Liga 7, by matchday |
| [/football](https://www.ttfixtures.uk/football/) | Pitreavie 7s, 2017s | this Saturday's games with pitch numbers, and last week |

Both read the leagues' own schedules and update themselves. Fixture changes
raise a push notification and are marked on the page until the game is played.

## How it is put together

| File | Role |
|---|---|
| `scraper.py` | reads Liga 3–7 from LeagueLobster into `fixtures_data.json` |
| `pitreavie_scraper.py` | reads the 7s workbook into `pitreavie_data.json` |
| `futsal/`, `football/`, `index.html` | the pages, rendering those two files |
| `.github/workflows/` | the scheduled checks that keep them current |

Both scrapers use only the Python standard library — no dependencies, no
browser. GitHub Actions runs them; GitHub Pages serves the result.

## Working on it

Read **`CLAUDE.md`** first. It covers how each scraper gets its data and the
non-obvious things that have each caused a bug — Sunday leagues, the Christmas
break, squads that share a name across leagues, and why dates are never
calculated.

**`HANDOVER.md`** covers moving the project between accounts: what transfers,
what has to be set up again, and the DNS records.

One rule worth repeating here: **the 7s workbook belongs to the league and is
never written to.** Every request is a GET.
