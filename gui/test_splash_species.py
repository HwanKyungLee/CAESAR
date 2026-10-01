"""gui/splash.py 의 레퍼런스 이름 읽기 자체검증 (Qt 창 없음, 데이터 불필요).

  1) v2 FitSet → **활성 채널**의 refs 이름
  2) v1(단일 채널) FitSet → refs 이름
  3) 없는 파일·깨진 json·빈 경로 → [] (스플래시는 σ 로 대체, 절대 실패하지 않는다)
  4) 표시용 아래첨자: NO2 → NO₂, CHOCHO 는 그대로
"""
# 한글 Windows 콘솔(cp949)에서 직접 실행해도 '—'·'✓' 등에서 죽지 않게(2026-10-01).
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.splash import display_species, fitset_species


def _write(obj_or_text):
    fd, p = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text))
    return p


def main():
    v2 = {"version": 2, "active": 2, "channels": {
        "1": {"refs": [{"name": "NO2"}, {"name": "H2O"}]},
        "2": {"refs": [{"name": "NO2"}, {"name": "CHOCHO"}, {"name": "O4"}, {"name": ""}]}}}
    assert fitset_species(_write(v2)) == ["NO2", "CHOCHO", "O4"], "활성 채널(2)이어야 하고 빈 이름은 뺀다"
    print("PASS v2 활성 채널")
    assert fitset_species(_write({"refs": [{"name": "NO2"}]})) == ["NO2"]
    print("PASS v1 단일 채널")
    assert fitset_species("") == [] and fitset_species(r"C:\없는\경로.json") == []
    assert fitset_species(_write("{깨진")) == []
    print("PASS 없음·깨짐 → []")
    assert display_species("NO2") == "NO₂" and display_species("H2O") == "H₂O"
    assert display_species("CHOCHO") == "CHOCHO" and display_species("O4") == "O₄"
    print("PASS 아래첨자")
    print("\nOK")


if __name__ == "__main__":
    main()
