$ErrorActionPreference = "Stop"
$taskName = "Greed Roster Bot"
$project = (Resolve-Path -LiteralPath $PSScriptRoot).Path.TrimEnd('\')
$venvPython = Join-Path $project ".venv\Scripts\python.exe"

Write-Host "GREED ROSTER BOT | EMERGENCY STOP" -ForegroundColor Yellow
Write-Host "Project: $project"

try {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        if ($task.State -ne "Disabled") {
            Disable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
        }
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Write-Host "Scheduled task disabled and stop requested." -ForegroundColor Green
    } else {
        Write-Host "Scheduled task not found, continuing with process cleanup." -ForegroundColor DarkYellow
    }
} catch {
    Write-Host "Task Scheduler error: $($_.Exception.Message)" -ForegroundColor Red
}

$found = 0
$processes = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'"
foreach ($proc in $processes) {
    $exe = [string]$proc.ExecutablePath
    $cmd = [string]$proc.CommandLine
    $isBot = ($cmd -match '(?i)(^|[\s"])bot\.py([\s"]|$)') -and (
        $exe.Equals($venvPython, [StringComparison]::OrdinalIgnoreCase) -or
        $cmd.IndexOf($project, [StringComparison]::OrdinalIgnoreCase) -ge 0
    )
    if (-not $isBot) { continue }
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        $found++
        Write-Host "Stopped Greed bot process PID $($proc.ProcessId)" -ForegroundColor Green
    } catch {
        Write-Host "Could not stop PID $($proc.ProcessId): $($_.Exception.Message)" -ForegroundColor Red
    }
}
Write-Host "Bot processes terminated: $found"
Write-Host "Scheduled task remains disabled until re-enabled through Maintenance Mode."
