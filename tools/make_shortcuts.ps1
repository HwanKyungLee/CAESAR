# Augur / Vigil desktop shortcuts with the emblem icons (icons/*.ico).
# Run once per PC from the repo root:   powershell -ExecutionPolicy Bypass -File tools\make_shortcuts.ps1
# The shortcuts start .venv\Scripts\pythonw.exe directly (no console flash). In Vigil you pick the raw
# folder with the dashboard's Choose folder button (no fixed watch folder). Re-running overwrites them.
$repo = Split-Path -Parent $PSScriptRoot
$desk = [Environment]::GetFolderPath('Desktop')
$py = Join-Path $repo '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $py)) { Write-Error "not found: $py (create the .venv first)"; exit 1 }
$ws = New-Object -ComObject WScript.Shell
$items = @(
  @{ Name = 'Augur'; Args = 'main.py';            Icon = 'icons\augur.ico'; Desc = 'Augur - BBCEAS trace-gas analysis' },
  @{ Name = 'Vigil'; Args = 'vigil\run_vigil.py'; Icon = 'icons\vigil.ico'; Desc = 'Vigil - live instrument monitor (choose the raw folder with the dashboard button)' }
)
foreach ($it in $items) {
  $lnk = $ws.CreateShortcut((Join-Path $desk ($it.Name + '.lnk')))
  $lnk.TargetPath = $py
  $lnk.Arguments = $it.Args
  $lnk.WorkingDirectory = $repo
  $lnk.IconLocation = (Join-Path $repo $it.Icon) + ',0'
  $lnk.Description = $it.Desc
  $lnk.Save()
  Write-Output ("created: " + (Join-Path $desk ($it.Name + '.lnk')))
}
