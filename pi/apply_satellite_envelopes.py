#!/usr/bin/env python3
"""
apply_satellite_envelopes.py

Bakes fresh satellite control-curve envelope points directly into a REAPER
.RPP project file's text, without needing REAPER to be running or any
ReaScript/GUI interaction. Designed to run as part of an hourly automation
cycle (see refresh_satellite.sh) right before REAPER is restarted so it
reloads the file with up-to-date envelopes.

Prerequisite (one-time, manual, in the REAPER GUI):
  Each popo_<type>.wav must already be on its own track in the project,
  with a Volume envelope visible/created on that track (an ReaScript run of
  reaper/import_satellite_envelope.lua once, or just enabling the Volume
  envelope, is enough -- it doesn't matter what points are on it already,
  this script replaces them).

What it does, for each sat_type in SAT_TYPES:
  1. Finds the <TRACK ...> block whose item source FILE references
     popo_<type>.wav.
  2. Within that track block, finds its <VOLENV2 ...> (Volume envelope)
     sub-block.
  3. Replaces all existing "PT ..." point lines in that sub-block with
     freshly generated ones from datasets/satellite/envelopes' matching
     popo_<type>_envelope.csv (columns: time_s, value_norm, value_raw),
     mapping value_norm (0..1) linearly to gain via MIN_GAIN..MAX_GAIN --
     identical math to reaper/import_satellite_envelope.lua.
  4. Leaves everything else in the .RPP byte-for-byte untouched.

Tracks/types with no matching CSV (e.g. popo_satellite_mix, which is an
audio-only mix with no control curve) are silently skipped -- their audio
still gets refreshed in place by refresh_satellite.sh, just no envelope
edit happens.

A timestamped backup of the .RPP is written to <project>/Backups/ before
any edit, in addition to REAPER's own autosave backups.

Usage:
  python3 apply_satellite_envelopes.py \\
      --rpp /home/sjc/reaper-projects/Dreammachine_popo_01/Dreammachine_popo_01.RPP \\
      --envelopes-dir /home/sjc/reaper-projects/Dreammachine_popo_01/satellite_envelopes
"""

import argparse
import csv
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Must match reaper/import_satellite_envelope.lua's MIN_GAIN/MAX_GAIN exactly.
MIN_GAIN = 0.05
MAX_GAIN = 1.0

SAT_TYPES = ["so2", "mirova", "disp", "coh"]  # satellite_mix has no envelope CSV


def parse_blocks(lines):
    """Return a list of (tag, start_idx, end_idx) for every <TAG ...> ... > block,
    inclusive of the opening/closing lines, at any nesting depth. Nesting is
    determined structurally (any line starting with '<' opens a block, any
    line that is exactly '>' closes the innermost open one) -- this matches
    REAPER's RPP chunk format regardless of exact indentation."""
    blocks = []
    stack = []  # each entry: (tag, start_idx)
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith("<"):
            tag = s[1:].split()[0] if len(s) > 1 else ""
            stack.append((tag, i))
        elif s == ">":
            if stack:
                tag, start = stack.pop()
                blocks.append((tag, start, i))
    return blocks


def load_csv_points(csv_path):
    rows = []
    with open(csv_path, "r", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            try:
                t = float(row[0])
                n = float(row[1])
            except ValueError:
                continue
            rows.append((t, n))
    return rows


def build_pt_lines(indent, rows):
    lines = []
    for t, n in rows:
        gain = MIN_GAIN + n * (MAX_GAIN - MIN_GAIN)
        lines.append(f"{indent}PT {t:.3f} {gain:.4f} 0")
    return lines


def apply_envelopes(rpp_path: Path, envelopes_dir: Path):
    text = rpp_path.read_text()
    lines = text.split("\n")
    blocks = parse_blocks(lines)

    track_blocks = [b for b in blocks if b[0] == "TRACK"]
    if not track_blocks:
        print("No <TRACK blocks found -- is this a valid .RPP file?", file=sys.stderr)
        return 1

    file_re = re.compile(r'FILE\s+"([^"]*)"')
    pt_re = re.compile(r"^(\s*)PT\s")

    updated_types = []
    skipped_types = []

    for sat_type in SAT_TYPES:
        wav_name = f"popo_{sat_type}.wav"
        csv_path = envelopes_dir / f"popo_{sat_type}_envelope.csv"

        matching_track = None
        for tag, start, end in track_blocks:
            for ln in lines[start:end + 1]:
                m = file_re.search(ln)
                if m and m.group(1).endswith(wav_name):
                    matching_track = (start, end)
                    break
            if matching_track:
                break

        if not matching_track:
            skipped_types.append((sat_type, "no track found referencing " + wav_name))
            continue

        if not csv_path.exists():
            skipped_types.append((sat_type, f"no envelope csv at {csv_path}"))
            continue

        t_start, t_end = matching_track
        # Find the VOLENV2 sub-block that lies within this track's line range.
        volenv = None
        for tag, start, end in blocks:
            if tag == "VOLENV2" and t_start <= start and end <= t_end:
                volenv = (start, end)
                break

        if not volenv:
            skipped_types.append((sat_type, "track has no VOLENV2 (Volume envelope) block"))
            continue

        v_start, v_end = volenv
        rows = load_csv_points(csv_path)
        if not rows:
            skipped_types.append((sat_type, f"no data rows in {csv_path}"))
            continue

        # Determine indent from an existing PT line, default to 6 spaces.
        indent = "      "
        for ln in lines[v_start:v_end + 1]:
            m = pt_re.match(ln)
            if m:
                indent = m.group(1)
                break

        new_pt_lines = build_pt_lines(indent, rows)

        # Replace: keep all non-PT lines in the VOLENV2 block, insert the new
        # PT lines right after the last non-PT header line (before the
        # closing '>').
        header_lines = []
        for ln in lines[v_start:v_end + 1]:
            if pt_re.match(ln):
                continue
            header_lines.append(ln)
        # header_lines includes the opening "<VOLENV2" line ... and the
        # closing ">" line (last element). Insert new PT lines just before
        # the closing ">".
        closing = header_lines.pop()  # the ">" line
        new_block = header_lines + new_pt_lines + [closing]

        lines[v_start:v_end + 1] = new_block
        # Block line count changed -- re-parse blocks/track ranges before
        # continuing to the next sat_type since indices have shifted.
        blocks = parse_blocks(lines)
        track_blocks = [b for b in blocks if b[0] == "TRACK"]

        updated_types.append((sat_type, len(rows)))

    if not updated_types:
        print("Nothing updated. Details:", file=sys.stderr)
        for sat_type, reason in skipped_types:
            print(f"  - {sat_type}: {reason}", file=sys.stderr)
        return 1

    # Backup before writing.
    backups_dir = rpp_path.parent / "Backups"
    backups_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = backups_dir / f"{rpp_path.stem}_preenv_{stamp}.RPP"
    shutil.copy2(rpp_path, backup_path)

    rpp_path.write_text("\n".join(lines))

    print(f"Backed up project to {backup_path}")
    for sat_type, n in updated_types:
        print(f"Updated {sat_type}: {n} envelope points")
    for sat_type, reason in skipped_types:
        print(f"Skipped {sat_type}: {reason}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rpp", required=True, help="Path to the .RPP project file")
    ap.add_argument("--envelopes-dir", required=True,
                     help="Directory containing popo_<type>.wav and popo_<type>_envelope.csv")
    args = ap.parse_args()

    rpp_path = Path(args.rpp)
    envelopes_dir = Path(args.envelopes_dir)

    if not rpp_path.exists():
        print(f"RPP file not found: {rpp_path}", file=sys.stderr)
        return 1
    if not envelopes_dir.is_dir():
        print(f"Envelopes dir not found: {envelopes_dir}", file=sys.stderr)
        return 1

    return apply_envelopes(rpp_path, envelopes_dir)


if __name__ == "__main__":
    raise SystemExit(main())
