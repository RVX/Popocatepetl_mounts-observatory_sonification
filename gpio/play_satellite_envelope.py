#!/usr/bin/env python3
"""play_satellite_envelope.py -- drive one or more GPIO LEDs (via gpiozero
PWMLED) from a POPO01.py satellite control-curve CSV
(datasets/satellite/envelopes/popo_<type>_envelope.csv, columns:
time_s, value_norm, value_raw).

The CSV is already a uniformly-resampled 0..1 curve on the same compressed
timeline used to generate the matching .wav (--listen-minutes), so starting
this script at the same moment as REAPER playback (or the plain
popo_<type>.wav / popo_satellite_mix.wav) keeps the brightness and the
audio/light in sync.

Runs on the Raspberry Pi side, inside a venv created with
`python3 -m venv --system-site-packages` so it can see the apt-installed
gpiozero/lgpio hardware bindings (see /memories/correr-venice-pis.md for the
full gpiozero/lgpio setup notes on Debian Trixie).

Usage:
    python3 play_satellite_envelope.py --csv popo_so2_envelope.csv --pin 18
    python3 play_satellite_envelope.py --csv popo_so2_envelope.csv --pin 18 27 --loop

MIN_BRIGHTNESS floor keeps the LED from ever going fully dark:
    brightness = min_brightness + value_norm * (1 - min_brightness)
"""
import argparse
import csv
import signal
import time

from gpiozero import PWMLED


def load_envelope(csv_path):
    times = []
    values = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row["time_s"]))
            values.append(float(row["value_norm"]))
    if not times:
        raise ValueError(f"No data rows found in {csv_path}")
    return times, values


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="popo_<type>_envelope.csv path")
    parser.add_argument("--pin", type=int, nargs="+", required=True,
                         help="One or more BCM GPIO pin numbers to drive together")
    parser.add_argument("--min-brightness", type=float, default=10.0,
                         help="Brightness floor in percent, 0-100 (default: 10)")
    parser.add_argument("--pwm-freq", type=int, default=200, help="PWM frequency in Hz (default: 200)")
    parser.add_argument("--loop", action="store_true", help="Loop the envelope forever instead of running once")
    args = parser.parse_args()

    times, values = load_envelope(args.csv)
    total_s = times[-1]
    floor = max(0.0, min(100.0, args.min_brightness)) / 100.0

    leds = [PWMLED(pin, frequency=args.pwm_freq) for pin in args.pin]

    def shutdown(signum=None, frame=None):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)

    print(f"[gpio] Driving pins {args.pin} from {args.csv} "
          f"({len(times)} frames, {total_s:.0f}s, floor {args.min_brightness:.0f}%)"
          + (", looping" if args.loop else ""))

    try:
        while True:
            start = time.monotonic()
            for t, v in zip(times, values):
                brightness = floor + v * (1.0 - floor)
                for led in leds:
                    led.value = brightness
                sleep_s = (start + t) - time.monotonic()
                if sleep_s > 0:
                    time.sleep(sleep_s)
            if not args.loop:
                break
    except KeyboardInterrupt:
        pass
    finally:
        for led in leds:
            led.off()
            led.close()
        print("[gpio] Stopped, LEDs off.")


if __name__ == "__main__":
    main()
