"""Alpha Generator fallback wavecal folder must follow the channel identity, not the number.

app_window_inputs used {1:'roi1', 2:'roi2'}; the 2026 Yeosu pairing is crossed
(ch1 = ANs <-> roi2, ch2 = PNs <-> roi1, README glossary). Checked against
tools/channel_map.json so the two can't drift apart silently.
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gui.app_window_inputs import InputsAlphaMixin  # noqa: E402


def main():
    with open(os.path.join(ROOT, "tools", "channel_map.json"), encoding="utf-8") as fh:
        cm = json.load(fh)["channels"]
    fb = InputsAlphaMixin._FALLBACK_CH_ROI
    assert fb[1] == cm["ans"]["wavecal_dir"] == "roi2", fb   # ch1 = ANs
    assert fb[2] == cm["pns"]["wavecal_dir"] == "roi1", fb   # ch2 = PNs
    print("alpha fallback roi mapping matches channel identity OK")


if __name__ == "__main__":
    main()
