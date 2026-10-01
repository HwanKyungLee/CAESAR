"""zenodo_deposit.py — create a Zenodo DRAFT deposition (never publishes unless --publish).

Usage (PowerShell):
    $env:ZENODO_TOKEN = "<personal access token with deposit:write>"
    python tools/zenodo_deposit.py --meta .zenodo.json --file <zip> [--sandbox]
    python tools/zenodo_deposit.py --meta benchmark/doas_benchmark_v1/.zenodo.json --file <zip>

The draft shows a reserved DOI immediately; check it on the website, then publish there
(or rerun with --publish --id <deposition id>). Publishing is permanent: a published
record and its DOI cannot be deleted, only versioned.
"""
import argparse, json, os, sys

def main():
    import requests   # 업로드 때만 필요 — requirements.txt 에 없어 최상위에 두면 CI 임포트 스모크가 깨진다
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--sandbox", action="store_true", help="use sandbox.zenodo.org (test DOIs)")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--id", type=int, help="existing deposition id (with --publish)")
    a = ap.parse_args()
    tok = os.environ.get("ZENODO_TOKEN")
    if not tok:
        sys.exit("set ZENODO_TOKEN first")
    base = "https://sandbox.zenodo.org/api" if a.sandbox else "https://zenodo.org/api"
    H = {"Authorization": f"Bearer {tok}"}
    meta = json.load(open(a.meta, encoding="utf-8"))
    meta.pop("notes", None) if str(meta.get("notes", "")).startswith("TODO") else None
    if a.publish:
        if not a.id:
            sys.exit("--publish needs --id")
        r = requests.post(f"{base}/deposit/depositions/{a.id}/actions/publish", headers=H)
        r.raise_for_status(); print("published:", r.json().get("doi")); return
    r = requests.post(f"{base}/deposit/depositions", headers=H, json={})
    r.raise_for_status(); d = r.json()
    for f in a.file:
        with open(f, "rb") as fh:
            u = requests.put(f"{d['links']['bucket']}/{os.path.basename(f)}", data=fh, headers=H)
        u.raise_for_status(); print("uploaded", os.path.basename(f), u.json().get("size"), "bytes")
    r = requests.put(f"{base}/deposit/depositions/{d['id']}", headers=H, json={"metadata": {**meta, "prereserve_doi": True}})
    r.raise_for_status(); m = r.json()["metadata"]
    print("draft id:", d["id"])
    print("reserved DOI:", m.get("prereserve_doi", {}).get("doi"))
    print("review:", d["links"]["html"])

if __name__ == "__main__":
    main()
