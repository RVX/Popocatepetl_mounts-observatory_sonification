"""Near-real-time sonification of Popocatepetl ground data via the MOUNTS
FDSN web service (https://mounts-observatory.org).

Fetches the most recent window of MX.CZB waveforms (seismic HNZ/HNN/HNE +
infrasound HDF01-04), delayed by --delay-minutes from current UTC so the
server's ~10-minute reindexing cycle has safely settled (default 60 min lag),
then audifies every channel into datasets/ground/sonifications/ via POPO01's
existing sonify pipeline (default 20x speed -> 1 hour of data = 3 min audio).

Quick test (small window, recent past):
    python POPO_fdsnws_mounts_01.py --minutes 5

Normal use (1 hour of data, 1 hour behind real time):
    python POPO_fdsnws_mounts_01.py
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
from obspy import Stream, UTCDateTime
from obspy.clients.fdsn import Client

import POPO01

FDSN_BASE_URL = "https://mounts-observatory.org"
NETWORK = "MX"
STATION = "CZB"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=60.0,
                    help="Length of the data window to fetch, minutes (default: 60)")
    ap.add_argument("--delay-minutes", type=float, default=60.0,
                    help="How far behind current UTC the window ENDS (default: 60, "
                         "safe margin over the server's ~10 min reindexing cycle)")
    ap.add_argument("--channels", default="all", metavar="LIST",
                    help="Comma-list of channel tokens from POPO01.CHANNEL_TOKEN_MAP "
                         "(HNZ,HNN,HNE,HDF01..04), or 'all' (default)")
    ap.add_argument("--speed-up", type=float, default=20.0,
                    help="Audification speed multiplier (default: 20)")
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


def main():
    args = parse_args()

    if args.end:
        end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    else:
        end = datetime.now(timezone.utc) - timedelta(minutes=args.delay_minutes)
    start = end - timedelta(minutes=args.minutes)
    print(f"[window] {start:%Y-%m-%dT%H:%M:%S} - {end:%Y-%m-%dT%H:%M:%S} UTC "
          f"({args.minutes:g} min, ends {args.delay_minutes:g} min behind real time)")

    tokens = (list(POPO01.CHANNEL_TOKEN_MAP)
              if args.channels.strip().lower() == "all"
              else [t.strip().upper() for t in args.channels.split(",")])

    client = Client(base_url=FDSN_BASE_URL, _discover_services=False)

    st = Stream()
    for token in tokens:
        if token not in POPO01.CHANNEL_TOKEN_MAP:
            print(f"[fetch] unknown channel token '{token}', skipping", file=sys.stderr)
            continue
        loc, chan = POPO01.CHANNEL_TOKEN_MAP[token]
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
    mseed_path = os.path.join(POPO01.MSEED_DIR,
                              f"popo_live_{stamp}_{int(args.minutes)}m.mseed")
    for tr in st:
        tr.data = tr.data.astype(np.int32)
    st.write(mseed_path, format="MSEED", encoding="STEIM2")
    print(f"[fetch] Saved merged stream to {mseed_path} ({len(st)} traces)")

    wav_paths = POPO01.do_sonify(mseed_path, speed_up_factor=args.speed_up,
                                 channel_filter="all", st=st)
    print(f"[done] {len(wav_paths)} wav file(s) in {POPO01.SONIFY_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())