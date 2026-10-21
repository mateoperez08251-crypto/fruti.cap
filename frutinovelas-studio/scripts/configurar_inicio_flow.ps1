param([switch]$Enable, [switch]$Disable)
$ErrorActionPreference = 'Stop'
if ($Enable -eq $Disable) { throw 'Elige -Enable o -Disable.' }
$studioPath = Split-Path $PSScriptRoot -Parent
$startupPath = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupPath 'Frutinovelas Flow Agent.lnk'
if ($Disable) {
    if (Test-Path $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
    Write-Host 'Inicio automático de Flow desactivado.'
    exit 0
}
$launcherPath = Join-Path $studioPath 'iniciar_flow_agente.cmd'
if (-not (Test-Path -LiteralPath $launcherPath)) { throw 'No se encontró el iniciador del agente.' }
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcherPath
$shortcut.WorkingDirectory = $studioPath
$shortcut.Description = 'Agente Flow local; requiere sesión de escritorio abierta.'
$shortcut.Save()
Write-Host 'El agente se abrirá al iniciar sesión en Windows. No iniciará sesión en Userflex.'
