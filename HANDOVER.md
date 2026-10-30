# Handover

What this is, what has to move with it, and what to do first.

`CLAUDE.md` holds the working knowledge — how each scraper gets its data and
the handful of things that have caused bugs. This file is only about moving
the thing between accounts.

## What exists

- A public GitHub repository holding two scrapers, two pages and two workflows
- GitHub Pages serving them at **https://www.ttfixtures.uk**
- A domain, `ttfixtures.uk`, with DNS pointing at GitHub
- Two repository secrets
- An ntfy topic that pushes alerts to phones
- A setup guide written for the other coaches

Nothing runs on anyone's computer. Everything happens in GitHub Actions, so
whoever owns the repository owns the system.

## Moving between Claude accounts: one thing to recreate

A Claude account and a GitHub account are unrelated, so the repository, the
secrets, the DNS and Pages all stay exactly as they are.

**The exception, since 30 Oct 2026: the hourly check starter.** GitHub's own
scheduler was skipping most runs, so two Claude Routines on Greg's Claude
account press "Run workflow" on a timer:

- `ttfixtures: start 7s check` — :23 past every hour, Wed/Thu/Fri (UK time)
- `ttfixtures: start futsal check` — :49 past every 4th hour, every day

Both fire into one helper session, "ttfixtures: hourly check starter", which
runs on Haiku, has this repository attached, and only runs
`gh workflow run <file> --repo gregmurphy-creator/futsal-fixture-scraper`.
A Routine that opens a fresh session each time does **not** work: a new
session has no access to the repository and fails with a 403.

These live on the Claude account, not in GitHub. If the Claude account
changes, recreate them, or the site falls back to GitHub's unreliable
schedule alone (still in the workflow files, so nothing breaks outright).
To pause them: claude.ai → Routines.

All a new Claude session needs is this repository and a prompt pointing it at
`CLAUDE.md`.

Claude now works in a **cloud session** (claude.ai/code), not a folder on the
Mac. Two things that session needs, neither of which touches GitHub's own
settings:

- **The repository attached with push access**, so it can push changes and
  read workflow run results. Without it the session can clone (the repo is
  public) but not push or see Actions.
- **`www.ttfixtures.uk` on the environment's network allow-list** (session
  title bar → environment → Edit → Network access → Allowed domains). The
  default policy blocks it, which means Claude cannot check the live page
  after a push. A DNS error from Claude's web fetcher on this domain means
  the same thing, not that the site is down.

The rest of this file applies only if the **GitHub** owner actually changes,
which is a separate decision and not required by anything above.

## If the GitHub owner does change

**Transfer the repository rather than copying it.** Settings → General →
Danger Zone → Transfer ownership. That keeps the history, the Actions, the
Pages setup and the issues. A fresh clone pushed to a new empty repo loses the
commit history, which is where the reasoning behind every decision lives.

Then, in order:

1. **Re-add the secrets.** They do not transfer. Settings → Secrets and
   variables → Actions:
   - `PITREAVIE_SHARE_URL` — the `https://1drv.ms/x/c/…` share link
   - `NTFY_TOPIC` — the ntfy topic name
2. **Check Pages is still on.** Settings → Pages, source = `main`, folder =
   root. The `CNAME` file in the repo pins the custom domain; it should be
   picked up automatically.
3. **Tick Enforce HTTPS** once the domain verifies, if it is not already.
4. **Run both workflows manually** from the Actions tab and confirm they go
   green. Neither should commit anything if nothing has changed.
5. **Check the live pages** at `/futsal` and `/football`.

DNS does not need touching — it points at GitHub's servers, not at an account.

## DNS, for reference

On `ttfixtures.uk` itself (the apex, usually entered as `@`):

```
A     185.199.108.153
A     185.199.109.153
A     185.199.110.153
A     185.199.111.153
AAAA  2606:50c0:8000::153
AAAA  2606:50c0:8001::153
AAAA  2606:50c0:8002::153
AAAA  2606:50c0:8003::153
```

Plus `CNAME  www  →  gregmurphy-creator.github.io.`

`www` is the canonical address, so the bare domain redirects to it, set by the
`CNAME` file in the repo.

The A and AAAA records point at GitHub itself and never change. The `www`
CNAME points at `gregmurphy-creator.github.io` — **that one, and only that
one, must be repointed if the repository ever moves to a different GitHub
username.** Miss it and the site goes dark.

## The ntfy topic

The topic name is the only thing protecting these alerts: anyone holding it
receives them and can send one. It lives in the `NTFY_TOPIC` secret and in the
coaches' setup guide.

To rotate it — if it leaks, or a coach leaves — pick a new unguessable name,
update the secret, update the guide, and have everyone resubscribe in the app.
Nothing else changes.

## What people are relying on

Parents and coaches have the site bookmarked or on their home screens, and
coaches get the phone alerts. If the repository goes private, **GitHub Pages
stops serving on a free plan and both pages go dark**. If it has to be
private, check the plan supports Pages first.

## Still open

- **Scores.** The 7s workbook carries `data-home_score` and `data-away_score`
  on every match, currently ignored. Capturing them would turn the "Last week"
  tab from a fixture list into results. The most useful thing left to do.
- **Node 20 warnings** on both workflows — `actions/checkout` and
  `setup-python` are being forced onto a newer runtime. Cosmetic for now;
  bumping the action versions clears it.
- **Heja vs Spond.** Fixtures are entered by hand into Heja, which has no
  import. Spond's Season Planner imports `.ics` or pasted rows, which the
  hub could generate. Parked pending a decision about switching apps.
