#!/usr/bin/env bash
# refresh_satellite.sh
#
# Hourly automation: fetch fresh Popocatepetl satellite data (MOUNTS live
# API), regenerate the .wav/.csv sonification + envelope files in place,
# copy them into the REAPER project's satellite_envelopes/ folder, bake the
# fresh envelope points directly into the .RPP (via apply_satellite_envelopes.py),
# then restart REAPER so it reloads everything.
#
# Restarting REAPER causes a brief (~8-10s) audio gap while lxsession's
# @-prefixed autostart entry (start_reaper.sh) automatically relaunches it --
# an accepted trade-off for guaranteed-fresh audio + envelopes every hour
# without any fragile live ReaScript/GUI hooks.
#
# Run manually to test: /home/sjc/dreammachine/pi/refresh_satellite.sh
# Normally triggered by dreammachine-satellite-refresh.timer (hourly).

set -euo pipefail

SATELLITE_DIR="/home/sjc/dreammachine/satellite"
PROJECT_ENV_DIR="/home/sjc/reaper-projects/Dreammachine_popo_01/satellite_envelopes"
RPP_PATH="/home/sjc/reaper-projects/Dreammachine_popo_01/Dreammachine_popo_01.RPP"
APPLY_SCRIPT="/home/sjc/dreammachine/pi/apply_satellite_envelopes.py"
LISTEN_MINUTES=4
LOG_FILE="/tmp/dreammachine_satellite_refresh.log"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >> "$LOG_FILE"; }

log "=== refresh start ==="

cd "$SATELLITE_DIR"
python3 POPO01.py satellite --sat-types all --listen-minutes "$LISTEN_MINUTES" --sat-live >> "$LOG_FILE" 2>&1

cp -f "$SATELLITE_DIR"/datasets/satellite/sonifications/popo_*.wav "$PROJECT_ENV_DIR"/
cp -f "$SATELLITE_DIR"/datasets/satellite/envelopes/popo_*_envelope.csv "$PROJECT_ENV_DIR"/
log "copied fresh wav/csv into $PROJECT_ENV_DIR"

python3 "$APPLY_SCRIPT" --rpp "$RPP_PATH" --envelopes-dir "$PROJECT_ENV_DIR" >> "$LOG_FILE" 2>&1

# Restart REAPER so it reloads fresh audio + envelopes. lxsession's
# @-prefixed autostart entry relaunches start_reaper.sh automatically once
# the process exits (built-in 8s settle delay before it reopens the project).
pkill -x reaper || true
log "=== refresh done (reaper restart requested) ==="
