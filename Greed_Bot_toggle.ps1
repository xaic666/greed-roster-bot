$ErrorActionPreference = "Stop"
$taskName = "Greed Roster Bot"

function Show-Status {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    Write-Host ""
    Write-Host "Task: $taskName" -ForegroundColor Cyan
    Write-Host "Status: $($task.State)" -ForegroundColor $(if ($task.State -eq "Running") { "Green" } elseif ($task.State -eq "Disabled") { "Yellow" } else { "Cyan" })
    Write-Host "SPACE: stop/start bot | Q or ESC: close this window" -ForegroundColor Gray
}

try {
    Get-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
} catch {
    Write-Host "Cannot find scheduled task '$taskName': $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "GREED ROSTER BOT | MAINTENANCE CONTROL" -ForegroundColor Cyan
Show-Status

while ($true) {
    $key = [Console]::ReadKey($true).Key
    if ($key -eq [ConsoleKey]::Q -or $key -eq [ConsoleKey]::Escape) {
        Write-Host "Closing control window. Current bot state is unchanged." -ForegroundColor Gray
        break
    }
    if ($key -ne [ConsoleKey]::Spacebar) {
        continue
    }

    try {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        if ($task.State -eq "Running") {
            Write-Host "Stopping bot and enabling maintenance mode..." -ForegroundColor Yellow
            Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop
            Disable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
            Write-Host "Bot stopped. Press SPACE to start it again." -ForegroundColor Yellow
        } else {
            Write-Host "Starting bot..." -ForegroundColor Cyan
            if ($task.State -eq "Disabled") {
                Enable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
            }
            Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
            Write-Host "Start requested. Check Discord for connection." -ForegroundColor Green
        }
    } catch {
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    }
    Start-Sleep -Milliseconds 500
    Show-Status
}
