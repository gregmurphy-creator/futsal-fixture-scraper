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

## Moving it to another account

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

`www` is the canonical address, so the bare domain redirects to it. That is
set by the `CNAME` file in the repo, and the `www` CNAME record must then be
updated to point at the new account's `<username>.github.io`.

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
