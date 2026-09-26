"""Generate an audience-ready combined figure for the DREAMMACHINE project:
left column = per-channel waveforms of the last fetched hour, right column =
context map showing the volcano and nearby cities (station position marked as
approximate until CZB coordinates are confirmed).

Usage:
    python POPO_audience_plot.py datasets/ground/mseed/popo_live_20260925T124640_60m.mseed
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import POPO01


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python POPO_audience_plot.py <path_to.mseed>")
    mseed_path = sys.argv[1]
    st = POPO01.load_stream(mseed_path)
    st.sort(keys=["channel"])

    n_traces = len(st)
    fig = plt.figure(figsize=(16, 9), facecolor=POPO01.BG_COLOR)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.35, 1.0], wspace=0.28,
                          left=0.06, right=0.97, top=0.88, bottom=0.08)

    # -- Left: waveform stack ------------------------------------------------
    sub_gs = gs[0].subgridspec(n_traces, 1, hspace=0.45)
    t0 = min(tr.stats.starttime for tr in st)
    duration_s = max((tr.stats.starttime - t0) + tr.stats.npts / tr.stats.sampling_rate
                     for tr in st)
    time_divisor, time_label, _ = POPO01._pick_time_axis_unit(duration_s)

    for i, tr in enumerate(st):
        ax = fig.add_subplot(sub_gs[i])
        offset_s = tr.stats.starttime - t0
        data = tr.data.astype(np.float64)
        times = (tr.times() + offset_s) / time_divisor
        step = max(1, len(data) // 100_000)
        times, data = times[::step], data[::step]

        color = POPO01.component_color(tr.stats.channel)
        env = POPO01.rms_envelope(data, tr.stats.sampling_rate / step)
        ax.fill_between(times, -env, env, color=color, alpha=0.30, linewidth=0)
        ax.plot(times, data, color=color, linewidth=0.4)

        is_infra = tr.stats.channel.upper().startswith("HDF")
        kind = "infrasound (air pressure)" if is_infra else "seismic (ground motion)"
        loc = tr.stats.location
        ax.set_title(f"{tr.stats.channel}  loc {loc}  |  {kind}", color="white",
                     fontsize=8, loc="left", pad=1)
        ax.set_xlim(0, duration_s / time_divisor)
        ax.set_ylim(-1.15 * np.max(np.abs(data)), 1.15 * np.max(np.abs(data)))
        POPO01.style_axes(ax)
        if i < n_traces - 1:
            ax.set_xticklabels([])
        else:
            ax.set_xlabel(time_label, color=POPO01.FG_COLOR, fontsize=9)

    start = t0.datetime
    end = (t0 + duration_s).datetime
    fig.text(0.06, 0.945, "Popocatepetl -- MX.CZB (MOUNTS / UNAM network)",
             color="white", fontsize=13, weight="bold", family="monospace")
    fig.text(0.06, 0.915,
             f"{start:%Y-%m-%d %H:%M} - {end:%H:%M} UTC   |   "
             f"3x seismic accelerometer + 4x infrasound microphone   |   "
             f"data via MOUNTS FDSN (mounts-observatory.org)",
             color=POPO01.FG_COLOR, fontsize=8.5, family="monospace")

    # -- Right: context map --------------------------------------------------
    map_ax = fig.add_subplot(gs[1])
    POPO01.draw_context_map(map_ax, compact=True)

    base = os.path.splitext(os.path.basename(mseed_path))[0]
    out_path = os.path.join(POPO01.PLOT_DIR, f"{base}_audience.png")
    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[audience] Saved combined figure to {out_path}")


if __name__ == "__main__":
    main()
