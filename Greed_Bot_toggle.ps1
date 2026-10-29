
$ErrorActionPreference = "Stop"
$taskName = "Greed Roster Bot"

try {
    $task = Get-ScheduledTask -TaskName $taskName

    Write-Host "Current task state: $($task.State)" -ForegroundColor Cyan

    if ($task.State -eq "Disabled") {
        Enable-ScheduledTask -TaskName $taskName | Out-Null
        Start-ScheduledTask -TaskName $taskName

        Write-Host "BOT ENABLED AND STARTED" -ForegroundColor Green
    }
    else {
        Disable-ScheduledTask -TaskName $taskName | Out-Null
        Stop-ScheduledTask -TaskName $taskName

        Write-Host "MAINTENANCE MODE ACTIVE - BOT STOPPED" -ForegroundColor Yellow
    }

    Start-Sleep -Seconds 2
    $task = Get-ScheduledTask -TaskName $taskName
    Write-Host "New task state: $($task.State)" -ForegroundColor Cyan
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
}

Read-Host "Press Enter to close"
