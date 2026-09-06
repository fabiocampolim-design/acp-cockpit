# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
<#
.SYNOPSIS  Register (or -Remove) a DAILY Windows Task Scheduler job that runs
           scripts/watch_upstream.py --daily, and verify it ran.
.DESCRIPTION
  This is a live product on a fast-moving adapter: it is watched once a day.
  The task action goes through cmd so stdout and stderr land in
  <state>\logs\task-output.log -- a task action discards output, and a
  script that only logs on success once hid four days of failures. With -q
  that file stays empty on success; the per-run audit trail is
  <state>\logs\watch-<stamp>.log, written by the script itself on success
  AND on failure (with the traceback). After
  registering, the task is started once and Get-ScheduledTaskInfo is read:
  a LastTaskResult of 0 and today's report on disk are what "registered"
  means here.
.PARAMETER Python   interpreter that runs the suite (default: the `python` on PATH)
.PARAMETER At       time of the daily trigger, HH:mm (default 08:00)
.PARAMETER StateDir snapshot + logs (default %USERPROFILE%\.acp-cockpit\watch)
.PARAMETER Remove   unregister the task instead
.PARAMETER DryRun   print what would be registered, register nothing
.PARAMETER NoRun    register without the verification run
Exit 0 ok, 1 failed.
#>
param(
    [string]$Python = "",
    [string]$At = "08:00",
    [string]$StateDir = "$env:USERPROFILE\.acp-cockpit\watch",
    [switch]$Remove,
    [switch]$DryRun,
    [switch]$NoRun
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here "watch_upstream.py"
$name = "acp-cockpit upstream watch"
$logDir = Join-Path $StateDir "logs"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Output "removed '$name'"
    exit 0
}
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { Write-Output "no python on PATH; pass -Python"; exit 1 }
    $Python = $cmd.Source
}
# prove the interpreter runs (the Store alias under WindowsApps is a stub)
& $Python -c "import sys" | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Output "python does not run: $Python"; exit 1 }

New-Item -ItemType Directory -Force $logDir | Out-Null
# cmd /c so that >> and 2>&1 apply; the date in the log name is resolved by
# cmd at run time (%DATE% is locale-dependent, so a fixed name per day is
# derived by the script's own audit log instead -- this one is the raw output)
$argument = "/c `"`"$Python`" `"$script`" --daily -q >> `"$logDir\task-output.log`" 2>&1`""

if ($DryRun) {
    Write-Output "DRY-RUN: Register-ScheduledTask '$name' -Daily $At -> cmd.exe $argument"
    exit 0
}
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $argument -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Description "acp-cockpit daily upstream watch (adapter on npm, ACP schema, adapter repo releases/issues)" -Force | Out-Null
Write-Output "registered '$name' daily $At -> $Python $script --daily"

if ($NoRun) { exit 0 }
# The scheduler is not verified by registering it (rule 23, QUANTUMESPRESSO
# 2026-09-04): run it once and read the result.
$before = (Get-ScheduledTaskInfo -TaskName $name).LastRunTime
Start-ScheduledTask -TaskName $name
$deadline = (Get-Date).AddMinutes(5)
# wait for a run that STARTED after we asked (LastRunTime moves) and ended
# (0x41301 = still running) — a stale LastTaskResult once passed for a run
do {
    Start-Sleep -Seconds 3
    $info = Get-ScheduledTaskInfo -TaskName $name
} while (($info.LastRunTime -eq $before -or $info.LastTaskResult -eq 267009) -and (Get-Date) -lt $deadline)
if ($info.LastRunTime -eq $before) { Write-Output "the task did not start within 5 minutes"; exit 1 }
Write-Output ("LastRunTime {0}  LastTaskResult {1}" -f $info.LastRunTime, $info.LastTaskResult)
if ($info.LastTaskResult -ne 0) {
    Write-Output "the verification run did not exit 0; read $logDir\task-output.log"
    exit 1
}
$today = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
$report = Join-Path (Join-Path (Split-Path -Parent $here) "docs\watch") "$today.md"
if (-not (Test-Path $report)) { Write-Output "no report at $report"; exit 1 }
Write-Output "verified: $report"
