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
PROJECT_DIR="/home/sjc/reaper-projects/Dreammachine_popo_01"
PROJECT_ENV_DIR="$PROJECT_DIR/satellite_envelopes"
PROJECT_MEDIA_DIR="$PROJECT_DIR/Media"
RPP_PATH="$PROJECT_DIR/Dreammachine_popo_01.RPP"
APPLY_SCRIPT="/home/sjc/dreammachine/pi/apply_satellite_envelopes.py"
LISTEN_MINUTES=4
LOG_FILE="/tmp/dreammachine_satellite_refresh.log"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >> "$LOG_FILE"; }

log "=== refresh start ==="

cd "$SATELLITE_DIR"
python3 POPO01.py satellite --sat-types all --listen-minutes "$LISTEN_MINUTES" --sat-live >> "$LOG_FILE" 2>&1

# Keep a copy of the raw output next to the project (source of truth for the
# .RPP patcher's CSV lookups) ...
cp -f "$SATELLITE_DIR"/datasets/satellite/sonifications/popo_*.wav "$PROJECT_ENV_DIR"/
cp -f "$SATELLITE_DIR"/datasets/satellite/envelopes/popo_*_envelope.csv "$PROJECT_ENV_DIR"/

# ... but REAPER actually plays back from its own pooled copy in Media/
# (created when the tracks were first dragged in), so the audio REAPER
# reads on reload must be refreshed there too, same filenames.
cp -f "$SATELLITE_DIR"/datasets/satellite/sonifications/popo_*.wav "$PROJECT_MEDIA_DIR"/
# Drop stale waveform peak caches so REAPER regenerates them for the new
# audio instead of showing an out-of-date waveform (cosmetic only, does not
# affect playback, but keeps the UI honest).
rm -f "$PROJECT_MEDIA_DIR"/peaks/popo_*.wav.reapeaks

log "copied fresh wav/csv into $PROJECT_ENV_DIR and $PROJECT_MEDIA_DIR"

python3 "$APPLY_SCRIPT" --rpp "$RPP_PATH" --envelopes-dir "$PROJECT_ENV_DIR" >> "$LOG_FILE" 2>&1

# Restart REAPER so it reloads fresh audio + envelopes. We explicitly kill
# *and* relaunch it ourselves here (rather than only killing it and relying
# on lxsession's autostart entry to notice and respawn it) so this is fully
# self-healing even if REAPER had already crashed/been closed before this
# ran, with no dependency on the desktop session's autostart timing.
export DISPLAY=:0
export XAUTHORITY=/home/sjc/.Xauthority

if pgrep -x reaper > /dev/null; then
    pkill -x reaper || true
    for _ in $(seq 1 10); do
        pgrep -x reaper > /dev/null || break
        sleep 1
    done
fi

nohup /usr/local/bin/reaper "$RPP_PATH" > /tmp/reaper_stdout.log 2>&1 &
disown
log "=== refresh done (REAPER relaunched with fresh project) ==="
