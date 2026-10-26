#requires -Version 5.1
<#
Prepara únicamente una VM de VirtualBox en un disco distinto a Windows.
No instala Windows ni UserFlex; requiere ISO con licencia y compatibilidad revisada.
Ejemplo:
powershell -ExecutionPolicy Bypass -File .\scripts\preparar_vm_userflex.ps1 -VmRoot "D:\FruticapVM" -IsoPath "D:\ISO\Windows.iso"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$VmRoot,
    [Parameter(Mandatory = $true)][string]$IsoPath,
    [string]$VmName = "Fruticap-UserFlex",
    [ValidateRange(4096, 8192)][int]$RamMB = 6144,
    [ValidateRange(1, 2)][int]$CpuCount = 2,
    [ValidateRange(50, 100)][int]$DiskGB = 70,
    [ValidateSet("Windows10_64", "Windows11_64")][string]$OsType = "Windows10_64"
)
$ErrorActionPreference = "Stop"

$iso = (Resolve-Path -LiteralPath $IsoPath -ErrorAction Stop).Path
if ([IO.Path]::GetExtension($iso).ToLowerInvariant() -ne ".iso") {
    throw "La instalación necesita una imagen ISO de Windows legítima."
}
$root = [IO.Path]::GetFullPath($VmRoot)
$drive = [IO.Path]::GetPathRoot($root)
if ($drive.TrimEnd("\").ToUpperInvariant() -eq $env:SystemDrive.ToUpperInvariant()) {
    throw "No se permite crear esta VM en la unidad de Windows; usa el disco de 480 GB."
}
if (-not (Test-Path -LiteralPath $drive)) { throw "La unidad del disco destino no está disponible." }
$disk = Get-PSDrive -Name $drive.Substring(0, 1) -PSProvider FileSystem -ErrorAction Stop
if ($disk.Free -lt 80GB) { throw "Se recomiendan 80 GB libres en el destino para Windows y sus descargas." }
if (-not (Test-Path -LiteralPath $root)) { New-Item -ItemType Directory -Path $root -Force | Out-Null }
if ((Get-ChildItem -LiteralPath $root -Force -ErrorAction Stop | Select-Object -First 1)) {
    throw "La carpeta destino no está vacía; usa una carpeta nueva para no sobrescribir nada."
}
$vbox = (Get-Command VBoxManage.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $vbox) {
    $candidate = Join-Path $env:ProgramFiles "Oracle\VirtualBox\VBoxManage.exe"
    if (-not (Test-Path $candidate)) { throw "Instala VirtualBox primero; no se encontró VBoxManage.exe." }
    $vbox = $candidate
}
function Invoke-VBox([string[]]$Params) {
    & $vbox @Params
    if ($LASTEXITCODE -ne 0) { throw "Falló VirtualBox al ejecutar '$($Params[0])' (código $LASTEXITCODE)." }
}
$existing = & $vbox list vms
if ($LASTEXITCODE -ne 0) { throw "No se pudo consultar VirtualBox." }
if ($existing | Where-Object { $_ -match ('^"' + [regex]::Escape($VmName) + '"') }) {
    throw "Ya existe una VM con ese nombre; no se modificará."
}
Write-Host "Creando VM '$VmName' en $root"
Invoke-VBox @("createvm", "--name", $VmName, "--ostype", $OsType, "--basefolder", $root, "--register")
Invoke-VBox @("modifyvm", $VmName, "--memory", "$RamMB", "--cpus", "$CpuCount",
    "--ioapic", "on", "--firmware", "efi", "--graphicscontroller", "vboxsvga",
    "--vram", "64", "--nic1", "nat", "--clipboard-mode", "disabled", "--draganddrop", "disabled")
Invoke-VBox @("storagectl", $VmName, "--name", "SATA", "--add", "sata", "--controller", "IntelAhci")
$diskPath = Join-Path (Join-Path $root $VmName) "Fruticap-UserFlex.vdi"
Invoke-VBox @("createmedium", "disk", "--filename", $diskPath, "--size", "$($DiskGB * 1024)", "--format", "VDI", "--variant", "Standard")
Invoke-VBox @("storageattach", $VmName, "--storagectl", "SATA", "--port", "0", "--device", "0", "--type", "hdd", "--medium", $diskPath)
Invoke-VBox @("storageattach", $VmName, "--storagectl", "SATA", "--port", "1", "--device", "0", "--type", "dvddrive", "--medium", $iso)
Write-Host "VM creada. Revisa el SO invitado, su licencia/actualizaciones y la compatibilidad de UserFlex antes de continuar."
Write-Host "Para abrirla: VBoxManage startvm `"$VmName`" --type gui"
