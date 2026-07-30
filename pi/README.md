# pi/ — hourly satellite automation (runs on the museum Raspberry Pi)

These files implement the "final version" unattended hourly refresh cycle:
fresh MOUNTS satellite data → new `.wav`/envelope `.csv` → baked into the
REAPER project → REAPER reload — with no manual drag-and-drop or GUI
interaction required after the one-time setup below.

## Files
- `refresh_satellite.sh` — the hourly job. Fetches fresh data via
  `POPO01.py satellite --sat-live`, copies the resulting `popo_*.wav` /
  `popo_*_envelope.csv` into the REAPER project's `satellite_envelopes/`
  folder (overwriting in place, same filenames), bakes the new envelope
  points into the `.RPP` via `apply_satellite_envelopes.py`, then restarts
  REAPER (`pkill -x reaper`) so it reloads everything fresh.
- `apply_satellite_envelopes.py` — edits the `.RPP` project file's text
  directly: for each satellite track already in the project, replaces its
  Volume envelope's `PT` points with freshly computed ones from the
  matching CSV (same `value_norm -> gain` mapping as
  `reaper/import_satellite_envelope.lua`: `MIN_GAIN=0.05..MAX_GAIN=1.0`).
  No ReaScript/GUI interaction needed. Writes a timestamped backup to
  `Backups/` before every edit.
- `dreammachine-satellite-refresh.service` / `.timer` — systemd units that
  run `refresh_satellite.sh` once at boot (+5min) and then hourly.

## One-time manual setup (in the REAPER GUI, on the Pi)
Drag each of the 5 files in `satellite_envelopes/` (`popo_so2.wav`,
`popo_mirova.wav`, `popo_disp.wav`, `popo_coh.wav`, `popo_satellite_mix.wav`)
onto its own new track, enable that track's Volume envelope (right-click the
volume fader / small arrow under the track name -> Volume), and save the
project (Ctrl+S). After this, `apply_satellite_envelopes.py` finds each
track by its item's source filename and only ever touches envelope points
inside the Volume envelope that's already there — it never creates or
restructures tracks/sources.

`popo_satellite_mix.wav` has no envelope CSV (it's a plain audio mix), so it
gets fresh audio each cycle but no envelope edit.

## Deploy on the Pi
```bash
scp pi/*.py pi/*.sh sjc@<pi>:~/dreammachine/pi/
ssh sjc@<pi> "chmod +x ~/dreammachine/pi/refresh_satellite.sh; sed -i 's/\r$//' ~/dreammachine/pi/*.py ~/dreammachine/pi/*.sh"
scp pi/*.service pi/*.timer sjc@<pi>:/tmp/
ssh sjc@<pi> "sudo mv /tmp/dreammachine-satellite-refresh.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now dreammachine-satellite-refresh.timer"
```

## Test manually
```bash
ssh sjc@<pi> "systemctl start dreammachine-satellite-refresh.service && sleep 2 && cat /tmp/dreammachine_satellite_refresh.log"
```
