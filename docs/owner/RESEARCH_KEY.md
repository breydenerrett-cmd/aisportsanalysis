# Research key

Lets your local Claude session read every hound's full bet history (house and member, all versions) without any password or login. Read-only.

## Turn it on (run once, from `C:\Users\KC\Desktop\wt_ship`)

```powershell
$t = python -c "import secrets;print(secrets.token_urlsafe(32))"; Add-Content -Path .env -Value "LINEHOUND_RESEARCH_TOKEN=$t" -Encoding ascii; fly secrets set RESEARCH_READ_TOKEN=$t -a linehound-prod
```

Nobody sees the key: it goes straight into `.env` (gitignored) and into Fly. Then pull the data any time with `python scripts/research_pull.py`. It lands in `data/research/bets_pull/<date>/` (also gitignored, it holds member data).

## Turn it off

```powershell
fly secrets unset RESEARCH_READ_TOKEN -a linehound-prod
```

With no key set, the routes answer 404 as if they did not exist.
