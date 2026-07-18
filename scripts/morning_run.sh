#!/bin/bash
# Neuron daily morning run - refreshes leads/inbox with fresh leads.
set -uo pipefail

VAULT="$HOME/second brain"
DATE=$(date +%Y-%m-%d)

echo "=== Neuron morning run: $DATE $(date +%H:%M:%S) ==="

# API key never lives in a plaintext file - pulled from macOS Keychain at run time.
GOOGLE_PLACES_KEY="$(security find-generic-password -a "$USER" -s google_places_api_key -w 2>/dev/null)"
export GOOGLE_PLACES_KEY

if [ -z "${GOOGLE_PLACES_KEY:-}" ]; then
  echo "WARNING: GOOGLE_PLACES_KEY not found in Keychain."
  echo "Run once: security add-generic-password -a \"$USER\" -s google_places_api_key -w"
  echo "Skipping lead search."
else
  python3 "$VAULT/scripts/find_leads.py"
fi

echo "=== Morning run done: $(date +%H:%M:%S) ==="
