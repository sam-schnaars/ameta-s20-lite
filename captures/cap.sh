#!/bin/bash
# usage: sudo IFACE=rvi0 ./cap.sh <name> [seconds]   (IFACE defaults to en0)
# Captures all traffic on en0 (Wi-Fi) to captures/<name>.pcap, auto-stops after <seconds>.
NAME="${1:?name required}"; SECS="${2:-30}"
DIR="$(cd "$(dirname "$0")" && pwd)"
echo ">>> Capturing $SECS s to $NAME.pcap — do the action NOW"
tshark -i "${IFACE:-en0}" -a duration:"$SECS" -w "$DIR/$NAME.pcap" 2>&1 | tail -2
chown "$SUDO_USER" "$DIR/$NAME.pcap" 2>/dev/null
echo ">>> Done: $NAME.pcap"
