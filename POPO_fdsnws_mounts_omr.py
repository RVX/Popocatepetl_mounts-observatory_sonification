"""POPO_fdsnws_mounts_omr -- self-contained near-real-time sonification of
Popocatepetl MX.CZB ground data via the MOUNTS FDSN web service
(https://mounts-observatory.org).

Single-file merge of the parts of POPO01.py needed for live ground-data
sonification (channel map, folder layout, audification) plus the FDSN fetch
loop -- no matplotlib, no satellite code, no SDS-archive machinery, so a
Raspberry Pi only needs `python3-obspy python3-numpy python3-scipy`.

Each run:
  1. Fetches the last --minutes of MX.CZB waveforms (3x seismic HN? @ loc 00 +
     4x infrasound HDF @ loc 01-04), ending --delay-minutes behind current
     UTC (default 60 min -- safe margin over the server's ~10 min reindex
     cycle), then waits --stagger-minutes first so a fleet of Pis doesn't all
     hit the server at the same instant.
  2. Audifies every channel into datasets/ground/sonifications/ at BOTH 5x
     and 10x speed (the two speeds that work on the installation's 18" subs).
  3. Prunes popo_live_* files older than --keep-days (default 5) from
     datasets/ground/{mseed,sonifications}/ -- but ONLY after a successful
     run, so a failed fetch never deletes anything.

Quick test (small window, recent past, no stagger):
    python POPO_fdsnws_mounts_omr.py --minutes 5

Normal hourly cron use (Pi #N staggers by N*10 minutes):
    python POPO_fdsnws_mounts_omr.py --stagger-minutes 10
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from obspy import Stream, UTCDateTime
from obspy.clients.fdsn import Client
from scipy.io import wavfile

FDSN_BASE_URL = "https://mounts-observatory.org"
NETWORK = "MX"
STATION = "CZB"

# Channel tokens -> (location, channel) SEED codes.
# HN? = strong-motion accelerometer; HDF = infrasound (air pressure).
CHANNEL_TOKEN_MAP = {
    "HNZ": ("00", "HNZ"),
    "HNN": ("00", "HNN"),
    "HNE": ("00", "HNE"),
    "HDF01": ("01", "HDF"),
    "HDF02": ("02", "HDF"),
    "HDF03": ("03", "HDF"),
    "HDF04": ("04", "HDF"),
}

# Output folders, created next to this script -- each Pi keeps its own local
# datasets/ tree, nothing is shared or hardcoded to an absolute path.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MSEED_DIR = os.path.join(BASE_DIR, "datasets", "ground", "mseed")
SONIFY_DIR = os.path.join(BASE_DIR, "datasets", "ground", "sonifications")
for _dir in (MSEED_DIR, SONIFY_DIR):
    os.makedirs(_dir, exist_ok=True)


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=60.0,
                    help="Length of the data window to fetch, minutes (default: 60)")
    ap.add_argument("--delay-minutes", type=float, default=60.0,
                    help="How far behind current UTC the window ENDS (default: 60, "
                         "safe margin over the server's ~10 min reindexing cycle)")
    ap.add_argument("--stagger-minutes", type=float, default=0.0,
                    help="Wait this many minutes before fetching, so multiple Pis "
                         "don't all query the server at the same instant. Suggested: "
                         "Pi #N uses N*10 (e.g. Pi 1 = 10, Pi 2 = 20, ...).")
    ap.add_argument("--channels", default="all", metavar="LIST",
                    help=f"Comma-list of channel tokens from "
                         f"{sorted(CHANNEL_TOKEN_MAP)}, or 'all' (default)")
    ap.add_argument("--speed-ups", default="5,10", metavar="LIST",
                    help="Comma-list of audification speed multipliers; one set of "
                         "wavs is written per speed (default: 5,10)")
    ap.add_argument("--keep-days", type=float, default=5.0,
                    help="Delete popo_live_* mseed/wav files older than this many "
                         "days after a successful run (default: 5)")
    ap.add_argument("--end", default=None, metavar="ISO",
                    help="Override the window end explicitly (e.g. 2026-09-16T06:00:00) "
                         "instead of now-delay; for testing against a known-good moment")
    return ap.parse_args()


def fetch_channel(client, loc, chan, start, end):
    try:
        st = client.get_waveforms(NETWORK, STATION, loc, chan,
                                 UTCDateTime(start), UTCDateTime(end))
    except Exception as exc:
        # FDSN 'no data' surfaces as an exception; skip silently-ish.
        print(f"[fetch] {NETWORK}.{STATION}.{loc}.{chan}: no data ({exc})")
        return None
    if not st:
        return None
    print(f"[fetch] {st[0].id}: {len(st)} trace(s), "
          f"{st[0].stats.starttime} - {st[-1].stats.endtime} UTC")
    return st


def sonify_one_trace(tr, mseed_path, speed_up_factor, channel_tag=None):
    data = tr.data.astype(np.float64)
    data -= data.mean()
    peak = np.max(np.abs(data))
    if peak > 0:
        data /= peak
    audio = (data * 32767).astype(np.int16)

    wav_sample_rate = int(tr.stats.sampling_rate * speed_up_factor)
    input_duration_s = tr.stats.npts / tr.stats.sampling_rate
    output_duration_s = input_duration_s / speed_up_factor

    base = os.path.splitext(os.path.basename(mseed_path))[0]
    if channel_tag:
        wav_path = os.path.join(SONIFY_DIR, f"{base}_{channel_tag}_{int(speed_up_factor)}x.wav")
    else:
        wav_path = os.path.join(SONIFY_DIR, f"{base}_{int(speed_up_factor)}x.wav")
    wavfile.write(wav_path, wav_sample_rate, audio)
    print(f"[sonify] {wav_path}")
    print(f"[sonify]  trace: {tr.id}  |  input: {input_duration_s:.1f}s  ->  "
          f"output: {output_duration_s:.1f}s at {speed_up_factor:.0f}x speed "
          f"(wav sample rate {wav_sample_rate} Hz)")
    return wav_path


def sonify_all(mseed_path, st, speed_up_factor):
    wav_paths = []
    seen_tag_counts = {}
    for tr in st:
        channel_tag = tr.id.replace(".", "-")
        seen_tag_counts[channel_tag] = seen_tag_counts.get(channel_tag, 0) + 1
        if seen_tag_counts[channel_tag] > 1:
            channel_tag = f"{channel_tag}_seg{seen_tag_counts[channel_tag]}"
        wav_paths.append(sonify_one_trace(tr, mseed_path, speed_up_factor, channel_tag))
    return wav_paths


def prune_old_files(keep_days):
    """Delete popo_live_* files older than keep_days from the mseed and
    sonifications folders. Only ever touches this script's own outputs."""
    cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86400
    removed = 0
    for folder, suffix in ((MSEED_DIR, ".mseed"), (SONIFY_DIR, ".wav")):
        for name in os.listdir(folder):
            if not (name.startswith("popo_live_") and name.endswith(suffix)):
                continue
            path = os.path.join(folder, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
    if removed:
        print(f"[cleanup] pruned {removed} file(s) older than {keep_days:g} days")


def main():
    args = parse_args()

    if args.stagger_minutes > 0:
        print(f"[stagger] waiting {args.stagger_minutes:g} min before fetching "
              f"(per-Pi fleet offset)")
        time.sleep(args.stagger_minutes * 60.0)

    if args.end:
        end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    else:
        end = datetime.now(timezone.utc) - timedelta(minutes=args.delay_minutes)
    start = end - timedelta(minutes=args.minutes)
    print(f"[window] {start:%Y-%m-%dT%H:%M:%S} - {end:%Y-%m-%dT%H:%M:%S} UTC "
          f"({args.minutes:g} min, ends {args.delay_minutes:g} min behind real time)")

    tokens = (list(CHANNEL_TOKEN_MAP)
              if args.channels.strip().lower() == "all"
              else [t.strip().upper() for t in args.channels.split(",")])

    client = Client(base_url=FDSN_BASE_URL, _discover_services=False)

    st = Stream()
    for token in tokens:
        if token not in CHANNEL_TOKEN_MAP:
            print(f"[fetch] unknown channel token '{token}', skipping", file=sys.stderr)
            continue
        loc, chan = CHANNEL_TOKEN_MAP[token]
        fetched = fetch_channel(client, loc, chan, start, end)
        if fetched:
            st += fetched

    if not st:
        raise SystemExit("No data returned for any channel -- try a larger "
                         "--delay-minutes or an explicit --end in the past.")

    st.merge(method=1, fill_value=0)
    st.detrend("demean")
    for tr in st:
        if tr.stats.channel.startswith("HDF"):
            tr.filter("bandpass", freqmin=0.05, freqmax=20.0, corners=4, zerophase=True)
        else:
            tr.filter("bandpass", freqmin=0.5, freqmax=10.0, corners=4, zerophase=True)

    stamp = start.strftime("%Y%m%dT%H%M%S")
    mseed_path = os.path.join(MSEED_DIR,
                              f"popo_live_{stamp}_{int(args.minutes)}m.mseed")
    for tr in st:
        tr.data = tr.data.astype(np.int32)
    st.write(mseed_path, format="MSEED", encoding="STEIM2")
    print(f"[fetch] Saved merged stream to {mseed_path} ({len(st)} traces)")

    speed_ups = [float(s.strip()) for s in args.speed_ups.split(",")]
    wav_paths = []
    for speed in speed_ups:
        wav_paths += sonify_all(mseed_path, st, speed)
    print(f"[done] {len(wav_paths)} wav file(s) in {SONIFY_DIR} "
          f"({len(speed_ups)} speed(s) x {len(st)} channels)")

    prune_old_files(args.keep_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
