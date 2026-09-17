# tati-bot 日次キュー確認・通知スクリプト(Windowsタスクスケジューラから起動)
# Claudeエージェントは一切起動しない(単なるファイル読み取り+通知)。
# クラウドの「tati-bot週次ファクター探索」ルーティンが調査待ちキューに新しい候補を
# 追加していないかを毎日チェックし、あればWindows通知を出すだけ。
# 実際の実証テストは、通知を見たユーザーがClaude Codeセッションで
# 「テストして」と依頼した時に(人間の確認を経て)行う。
#
# 2026-09-17設定。手動テスト:
#   powershell -NoProfile -ExecutionPolicy Bypass -File check_queue_and_notify.ps1

$ErrorActionPreference = "Stop"
Set-Location "C:\BP\tati"

git pull origin main --quiet 2>$null

$logFile = "C:\BP\tati\logs_local_routine\queue_check.log"
$logDir = Split-Path $logFile
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

$content = Get-Content -Raw -Encoding UTF8 "FACTOR_RESEARCH_LOG.md"

# 「調査待ちキュー」セクションのテーブル行(| 数字 | で始まる行)を数える
$section = $content -split "## 調査待ちキュー"
if ($section.Length -lt 2) {
    Add-Content -Path $logFile -Value "$(Get-Date -Format o) セクションが見つかりません"
    exit
}
$afterHeading = ($section[1] -split "## ")[0]
$rows = [regex]::Matches($afterHeading, "(?m)^\|\s*\d+\s*\|")

if ($rows.Count -eq 0) {
    Add-Content -Path $logFile -Value "$(Get-Date -Format o) 未検証候補なし" -Encoding UTF8
    exit
}

# 先頭候補のファクター名を通知に含める(3列目)
$firstRowLine = ($afterHeading -split "`n" | Where-Object { $_ -match "^\|\s*\d+\s*\|" } | Select-Object -First 1)
$cols = $firstRowLine -split "\|"
$factorName = if ($cols.Length -ge 4) { $cols[3].Trim() } else { "(名称取得失敗)" }

Add-Content -Path $logFile -Value "$(Get-Date -Format o) 未検証候補あり: $factorName (計$($rows.Count)件)" -Encoding UTF8

Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true
$notify.BalloonTipTitle = "tati-bot: 検証待ち候補あり"
$notify.BalloonTipText = "$factorName など計$($rows.Count)件が未検証です。Claude Codeで「テストして」と依頼してください。"
$notify.ShowBalloonTip(15000)
Start-Sleep -Seconds 16
$notify.Dispose()
