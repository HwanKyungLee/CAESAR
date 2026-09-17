"""Run the production AlphaExportWorker without opening the GUI."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass
from gui.worker import AlphaExportWorker


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", type=Path, nargs="+", required=True)
    p.add_argument("--wavecal", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--channel", type=int, required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--pixel-min", type=int, default=0)
    p.add_argument("--pixel-max", type=int, default=2048,
                   help="exclusive; use the actual fit/R-cal ROI, not detector edges")
    p.add_argument("--avg-sec", type=float, default=60.0)
    p.add_argument("--purge-settle-sec", type=float, default=60.0,
                   help="drop ambient scans within N sec after a ZA/He block "
                        "(cavity still holding purge gas); 0 keeps them")
    p.add_argument("--rl-factor", type=float, default=1.0)
    p.add_argument("--cavity-cm", type=float, default=51.8)
    p.add_argument("--campaign", default="",
                   help="output sub-root: {output}/{campaign}/{date}/alpha/ (default: 'default')")
    p.add_argument("--rt-path", type=Path,
                   help="optional production R(t) npz when this raw file has no He scan")
    args = p.parse_args()
    wave = np.loadtxt(args.wavecal, dtype=float).reshape(-1)
    if len(wave) != 2048 or not np.isfinite(wave).all() or not np.all(np.diff(wave) > 0):
        raise SystemExit("ABSTAIN: wavecal must be a finite, monotonic 2048-pixel axis")
    if not 0 <= args.pixel_min < args.pixel_max <= len(wave):
        raise SystemExit("ABSTAIN: invalid pixel ROI")
    worker = AlphaExportWorker(
        [str(path) for path in args.raw], args.pixel_min, args.pixel_max,
        wave[args.pixel_min:args.pixel_max],
        flag_za=[500], flag_he=[510], flag_amb=[1],
        rl_factor=args.rl_factor, cavity_len=args.cavity_cm,
        output_dir=str(args.output), channel=args.channel,
        avg_sec=args.avg_sec, purge_settle_sec=args.purge_settle_sec,
        channel_label=args.label,
        rt_path=str(args.rt_path) if args.rt_path else None,
        campaign=args.campaign,
    )
    messages: list[str] = []
    worker.status_msg.connect(lambda message: messages.append(str(message)))
    worker.finished.connect(lambda message: messages.append("FINISHED: " + str(message)))
    # Deliberately call the production implementation synchronously: this CLI
    # is for reproducible batch generation, not a second alpha algorithm.
    worker._run_inner()
    for message in messages:
        print(message)
    if not messages or messages[-1].startswith("FINISHED: ERROR"):
        raise SystemExit("ABSTAIN: alpha generation failed")


if __name__ == "__main__":
    main()
