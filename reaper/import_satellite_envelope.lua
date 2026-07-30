--[[
import_satellite_envelope.lua

Imports one of POPO01.py's satellite control-curve CSVs
(datasets/satellite/envelopes/popo_<type>_envelope.csv, columns:
time_s, value_norm, value_raw) as native REAPER envelope points on the
Volume envelope of the currently selected track.

Setup in REAPER (once):
  1. Select the track you want to control (e.g. the one playing
     popo_so2.wav / popo_satellite_mix.wav).
  2. Make sure its Volume envelope is visible: right-click the track's
     volume fader / TCP -> "Volume" (or press the small down-arrow under
     the track name -> Volume envelope). It doesn't need to have any
     points yet -- this script adds them.
  3. Actions List -> "Load ReaScript..." -> pick this file -> Run
     (or bind it to a toolbar button / shortcut for repeated use).

What it does:
  - Prompts for the CSV file (defaults to this project's
    datasets/satellite/envelopes/ folder).
  - Optionally clears existing points in [0, last CSV time] first.
  - Maps value_norm (0..1) linearly to a gain range you can tune below
    (MIN_GAIN..MAX_GAIN, where 1.0 = unity/0dB) and inserts one envelope
    point per CSV row, then sorts and redraws.

The CSV's time_s is already on the same compressed timeline used to
generate the matching .wav (--listen-minutes), so if you start playback
at the top of that track, the volume envelope and the audio/light stay
in sync automatically -- no manual scrubbing needed.
--]]

-- ---------------------------------------------------------------------
-- Tunable mapping: value_norm (0..1) -> envelope gain (1.0 = 0 dB / unity)
-- ---------------------------------------------------------------------
local MIN_GAIN = 0.05   -- floor so the track never goes fully silent (~-26 dB)
local MAX_GAIN = 1.0    -- ceiling (1.0 = unity / 0 dB; >1.0 would boost)
local CLEAR_EXISTING = true

local function fail(msg)
  reaper.ShowMessageBox(msg, "Import satellite envelope", 0)
end

local track = reaper.GetSelectedTrack(0, 0)
if not track then
  fail("Select a track first (the one whose volume should follow the satellite data), then run this script again.")
  return
end

local env = reaper.GetTrackEnvelopeByName(track, "Volume")
if not env then
  fail("This track has no visible Volume envelope.\n\nRight-click the track's volume fader (or the small arrow under the track name) and enable the Volume envelope, then run this script again.")
  return
end

local function has_envelope_csv(dir)
  return reaper.file_exists(dir .. "popo_so2_envelope.csv")
      or reaper.file_exists(dir .. "popo_mirova_envelope.csv")
      or reaper.file_exists(dir .. "popo_disp_envelope.csv")
      or reaper.file_exists(dir .. "popo_coh_envelope.csv")
end

-- Try the deployed layout first (CSVs next to the REAPER project), then the
-- dev repo's relative layout (script_dir/../datasets/satellite/envelopes/).
-- Always forward slashes -- REAPER accepts them on Windows too, and
-- backslashes are not a path separator on Linux/macOS.
-- Wrapped in pcall: a failed/renamed API here must never abort the script
-- silently -- worst case we just fall back to an empty default_dir.
local default_dir = ""
local proj_ok, _, proj_fn = pcall(reaper.EnumProjects, -1, "")
if proj_ok and proj_fn and proj_fn ~= "" then
  local proj_dir = proj_fn:match("(.*[/\\])")
  if proj_dir and has_envelope_csv(proj_dir .. "satellite_envelopes/") then
    default_dir = proj_dir .. "satellite_envelopes/"
  end
end
if default_dir == "" then
  local script_path = ({reaper.get_action_context()})[2]
  local script_dir = script_path:match("(.*[/\\])")
  local repo_dir = (script_dir or "") .. "../datasets/satellite/envelopes/"
  if has_envelope_csv(repo_dir) then
    default_dir = repo_dir
  end
end

local ok, csv_path = reaper.GetUserFileNameForRead(default_dir, "Select a popo_<type>_envelope.csv file", "*.csv")
if not ok then return end

local f = io.open(csv_path, "r")
if not f then
  fail("Could not open file:\n" .. csv_path)
  return
end

local rows = {}
local header_skipped = false
for line in f:lines() do
  if not header_skipped then
    header_skipped = true  -- first line is "time_s,value_norm,value_raw"
  else
    local t_str, n_str = line:match("([^,]+),([^,]+)")
    if t_str and n_str then
      rows[#rows + 1] = { t = tonumber(t_str), n = tonumber(n_str) }
    end
  end
end
f:close()

if #rows == 0 then
  fail("No data rows found in:\n" .. csv_path)
  return
end

reaper.Undo_BeginBlock()

if CLEAR_EXISTING then
  local last_t = rows[#rows].t
  -- Delete any existing points from just before the start through just after the end.
  reaper.DeleteEnvelopePointRange(env, -0.001, last_t + 0.001)
end

for _, row in ipairs(rows) do
  local gain = MIN_GAIN + row.n * (MAX_GAIN - MIN_GAIN)
  -- shape 0 = linear segment to the next point (smooth fader motion)
  reaper.InsertEnvelopePoint(env, row.t, gain, 0, 0, false, true)
end

reaper.Envelope_SortPoints(env)
reaper.UpdateArrange()
reaper.Undo_EndBlock("Import satellite control-curve envelope", -1)

reaper.ShowConsoleMsg(string.format(
  "Imported %d envelope points from %s (gain range %.2f..%.2f)\n",
  #rows, csv_path, MIN_GAIN, MAX_GAIN))
