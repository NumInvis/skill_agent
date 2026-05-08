# Skill Agent 远程调试启动脚本
# 自动清理缓存、杀掉旧进程、启动新进程并实时输出日志

$PluginDir = "D:\ai\skill_agent"
$LogFile = "$PluginDir\plugin.log"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Skill Agent 远程调试启动器" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. 清理 Python 缓存
Write-Host "`n[1/4] 清理 Python 缓存..." -ForegroundColor Yellow
$pycaches = @(
    "$PluginDir\__pycache__",
    "$PluginDir\tools\__pycache__",
    "$PluginDir\utils\__pycache__"
)
foreach ($dir in $pycaches) {
    if (Test-Path $dir) {
        Remove-Item -Recurse -Force $dir
        Write-Host "  已清理: $dir"
    }
}
Write-Host "  缓存清理完成" -ForegroundColor Green

# 2. 杀掉旧的远程调试进程
Write-Host "`n[2/4] 查找并终止旧的远程调试进程..." -ForegroundColor Yellow
$oldProcs = Get-WmiObject Win32_Process -Filter "name='python.exe'" | Where-Object {
    $_.CommandLine -like '*main*' -and $_.CommandLine -like '*skill_agent*'
}
if ($oldProcs) {
    foreach ($proc in $oldProcs) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "  已终止 PID: $($proc.ProcessId)"
    }
} else {
    Write-Host "  没有旧进程在运行"
}
Write-Host "  旧进程清理完成" -ForegroundColor Green

# 3. 清空旧日志
Write-Host "`n[3/4] 清空旧日志..." -ForegroundColor Yellow
if (Test-Path $LogFile) {
    Clear-Content $LogFile -ErrorAction SilentlyContinue
    Write-Host "  已清空: $LogFile"
}
Write-Host "  日志清理完成" -ForegroundColor Green

# 4. 启动新进程
Write-Host "`n[4/4] 启动远程调试进程..." -ForegroundColor Yellow
$env:PYTHONUNBUFFERED = "1"
Set-Location $PluginDir

# 使用 Start-Process 在后台启动，避免阻塞
$proc = Start-Process -FilePath "python" -ArgumentList "-m", "main" -WindowStyle Hidden -PassThru
Write-Host "  新进程 PID: $($proc.Id)" -ForegroundColor Green

# 等待日志文件生成
Start-Sleep -Seconds 2

# 检查是否成功连接
$logContent = Get-Content $LogFile -Raw -ErrorAction SilentlyContinue
if ($logContent -and $logContent -match "Installed tool: skill_agent") {
    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "  远程调试启动成功!" -ForegroundColor Green
    Write-Host "  PID: $($proc.Id)" -ForegroundColor Green
    Write-Host "  日志: $LogFile" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host "`n========================================" -ForegroundColor Yellow
    Write-Host "  进程已启动，等待连接确认..." -ForegroundColor Yellow
    Write-Host "  PID: $($proc.Id)" -ForegroundColor Yellow
    Write-Host "  日志: $LogFile" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Yellow
}

# 5. 实时跟踪日志
Write-Host "`n[日志输出] 按 Ctrl+C 停止跟踪（进程仍在后台运行）`n" -ForegroundColor Cyan

# 使用 .NET FileSystemWatcher 实现实时日志跟踪
$lastSize = 0
try {
    while ($true) {
        if (Test-Path $LogFile) {
            $fileInfo = Get-Item $LogFile
            if ($fileInfo.Length -gt $lastSize) {
                $stream = [System.IO.StreamReader]::new($LogFile, [System.Text.Encoding]::UTF8)
                $stream.BaseStream.Position = $lastSize
                while ($null -ne ($line = $stream.ReadLine())) {
                    if ($line -match "ERROR|Error|error|失败|❌") {
                        Write-Host $line -ForegroundColor Red
                    } elseif ($line -match "DEBUG|debug") {
                        Write-Host $line -ForegroundColor DarkGray
                    } elseif ($line -match "INFO|info|成功|✅") {
                        Write-Host $line -ForegroundColor Green
                    } else {
                        Write-Host $line
                    }
                }
                $lastSize = $fileInfo.Length
                $stream.Close()
            }
        }
        Start-Sleep -Milliseconds 500
    }
} catch {
    Write-Host "`n日志跟踪已停止。远程调试进程仍在后台运行 (PID: $($proc.Id))" -ForegroundColor Yellow
    Write-Host "如需停止，运行: Stop-Process -Id $($proc.Id) -Force" -ForegroundColor Yellow
}
