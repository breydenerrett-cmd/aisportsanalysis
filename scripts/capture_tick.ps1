<#
.SYNOPSIS
  Local clock for the capture and daily-loop workflows. GitHub Actions stays
  the worker; this only decides WHEN.

.WHY THIS EXISTS
  Measured on 2026-09-07: GitHub's own `schedule` event fired 4 times in a
  full day against a */15 cron that should have fired ~96 times, and the
  10:00Z daily loop did not fire until 15:20Z. Every other capture that day
  came from a human-in-the-loop watchdog. Freshness cannot depend on a cron
  that runs 4% of the time, nor on a Claude session being alive.

  This script is that watchdog, written down. It carries no model tokens, no
  API key, and no cleverness -- it asks GitHub what already ran and
  dispatches only when nothing recent did.

.WHAT IT WILL NOT DO
  - It never dispatches while a run is queued or in progress, so it cannot
    stack concurrent captures or double-spend odds credits.
  - It never dispatches a daily loop when one already exists for the UTC
    date (that loop is idempotent -- proven by run 34137806549 writing
    "settled 0 new (15 already settled)" -- but not dispatching is still
    cheaper than relying on that).
  - It holds no secret. `gh` uses its own stored credential; ODDS_API_KEY
    lives only in GitHub Actions secrets and is never read here.
  - It changes nothing about the workflows themselves, which stay dispatchable
    by hand exactly as they are now.

.PARAMETER StaleMinutes
  Dispatch capture only when the newest completed run is older than this.
  Default 45, matching the watchdog cadence used all through 2026-09-07.

.PARAMETER WhatIf
  Report the decision and dispatch nothing. Use this first.
#>

[CmdletBinding()]
param(
    # 40, not 45. The task ticks every 15 minutes, so worst-case staleness is
    # this plus 15. At 45 the tick that lands exactly on the boundary decides
    # nothing and the board sits another quarter hour, which is how captures
    # kept reaching 60 minutes old on 2026-09-07 -- observed in this script's
    # own log at 19:55:29Z ("newest run is 45 min old (threshold 45)").
    [int]$StaleMinutes = 40,
    [switch]$WhatIf,
    [string]$Repo = "breydenerrett-cmd/aisportsanalysis",
    [string]$CaptureRef = "claude/cowork-session-migration-tn3sx2",
    [string]$LogPath
)

$ErrorActionPreference = "Stop"

# $PSScriptRoot came back EMPTY under `powershell -File` here, which silently
# rooted the log at C:\data\logs -- outside the repo, exactly where a
# scheduler's only evidence goes to get lost. Resolve the script's own
# directory from $MyInvocation as well, and refuse to guess if neither works.
$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { throw "cannot resolve the script directory; pass -LogPath explicitly" }
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
if (-not $LogPath) { $LogPath = Join-Path $repoRoot "data\logs\capture_tick.log" }

$gh = "C:\Program Files\GitHub CLI\gh.exe"
if (-not (Test-Path $gh)) {
    $cmd = Get-Command gh -ErrorAction SilentlyContinue
    if ($cmd) { $gh = $cmd.Source } else { throw "GitHub CLI not found" }
}

$logDir = Split-Path -Parent $LogPath
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }

function Write-Tick([string]$Message) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $line = "$stamp  $Message"
    # Every decision is logged, including the decision to do nothing --
    # a silent scheduler is indistinguishable from a dead one.
    Add-Content -Path $LogPath -Value $line -Encoding utf8
    Write-Output $line
}

function Get-Runs([string]$Workflow, [int]$Limit = 3) {
    # One unbroken token: PowerShell splits `a, b, c` into three arguments,
    # which gh reads as a subcommand and fails with `unknown command "status"`.
    $raw = & $gh run list -R $Repo -w $Workflow -L $Limit `
        --json "databaseId,status,conclusion,createdAt" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
    return ($raw | ConvertFrom-Json)
}

function Get-Utc($value) {
    # Windows PowerShell 5.1's ConvertFrom-Json leaves timestamps as strings,
    # so `createdAt` has no .ToUniversalTime(). Parse explicitly as UTC.
    if ($value -is [datetime]) { return $value.ToUniversalTime() }
    return [datetime]::Parse([string]$value, $null,
        [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor
        [System.Globalization.DateTimeStyles]::AssumeUniversal)
}

function Invoke-Dispatch([string]$Workflow, [string]$Ref, [string]$Why) {
    if ($WhatIf) { Write-Tick "WOULD dispatch $Workflow ($Why)"; return }
    & $gh workflow run $Workflow -R $Repo --ref $Ref 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Tick "dispatched $Workflow ($Why)" }
    else { Write-Tick "ERROR dispatching $Workflow (gh exit $LASTEXITCODE)" }
}

$now = (Get-Date).ToUniversalTime()

# ---- forward-capture -------------------------------------------------------
try {
    $runs = Get-Runs "forward-capture"
    if ($null -eq $runs) {
        Write-Tick "skip capture: could not read run list (network or auth)"
    }
    elseif ($runs | Where-Object { $_.status -in @("in_progress", "queued") }) {
        Write-Tick "skip capture: a run is already in flight"
    }
    else {
        $newest = $runs | Sort-Object createdAt -Descending | Select-Object -First 1
        $age = [int]($now - (Get-Utc $newest.createdAt)).TotalMinutes
        # -ge, not -gt: a tick landing exactly on the threshold should act,
        # not wait another full interval.
        if ($age -ge $StaleMinutes) {
            Invoke-Dispatch "forward-capture.yml" $CaptureRef "newest run was $age min old"
        }
        else {
            Write-Tick "skip capture: newest run is $age min old (threshold $StaleMinutes)"
        }
    }
}
catch {
    # A scheduler that throws is a scheduler that stops. Log and carry on to
    # the daily loop rather than aborting the whole tick.
    Write-Tick "ERROR in capture check: $($_.Exception.Message)"
}

# ---- daily-loop ------------------------------------------------------------
# One per UTC date, and only once the day's games can actually be settled.
# 10:00Z is the workflow's own scheduled hour; this fires as a fallback after
# it, never before, so a healthy cron always wins the race.
try {
    if ($now.Hour -ge 10) {
        $runs = Get-Runs "daily-loop" 5
        if ($null -eq $runs) {
            Write-Tick "skip daily-loop: could not read run list"
        }
        elseif ($runs | Where-Object { $_.status -in @("in_progress", "queued") }) {
            Write-Tick "skip daily-loop: a run is already in flight"
        }
        else {
            $today = $now.Date
            $todayRun = $runs | Where-Object { (Get-Utc $_.createdAt).Date -eq $today }
            if ($todayRun) {
                Write-Tick "skip daily-loop: already ran today"
            }
            else {
                Invoke-Dispatch "daily-loop.yml" $CaptureRef "no run yet for $($today.ToString('yyyy-MM-dd'))"
            }
        }
    }
}
catch {
    Write-Tick "ERROR in daily-loop check: $($_.Exception.Message)"
}

# ---- afternoon-slate (F-1) ---------------------------------------------------
# The second slate pass at 21:10Z, so the sixteen genome systems -- which all
# require a posted lineup -- get to decide once lineups exist instead of
# refusing NO_LINEUP at the 10:00Z freeze. Added 2026-09-07 after that day's
# cron simply did not fire: by 23:12Z the only run was a 05:23Z manual test.
#
# Once per UTC date, and only a run created AT OR AFTER 21:10Z counts as
# "today's" -- a pre-window manual dispatch (like that 05:23Z test) must not
# satisfy this check, or the real pass never happens. Never before 21:10Z,
# so a healthy cron always wins the race. The workflow itself carries the
# first-pitch and board-staleness guards and spends no odds credits (proven
# on run 34086614213), so a late dispatch that finds nothing eligible is a
# logged refusal, not a cost.
try {
    $windowOpen = ($now.Hour -gt 21) -or ($now.Hour -eq 21 -and $now.Minute -ge 10)
    if ($windowOpen) {
        $runs = Get-Runs "afternoon-slate" 5
        if ($null -eq $runs) {
            Write-Tick "skip afternoon-slate: could not read run list"
        }
        elseif ($runs | Where-Object { $_.status -in @("in_progress", "queued") }) {
            Write-Tick "skip afternoon-slate: a run is already in flight"
        }
        else {
            $today = $now.Date
            $cronMoment = $today.AddHours(21).AddMinutes(10)
            $inWindow = $runs | Where-Object {
                $t = Get-Utc $_.createdAt
                $t.Date -eq $today -and $t -ge $cronMoment
            }
            if ($inWindow) {
                Write-Tick "skip afternoon-slate: already ran today after 21:10Z"
            }
            else {
                Invoke-Dispatch "afternoon-slate.yml" $CaptureRef "no run since 21:10Z for $($today.ToString('yyyy-MM-dd'))"
            }
        }
    }
}
catch {
    Write-Tick "ERROR in afternoon-slate check: $($_.Exception.Message)"
}
