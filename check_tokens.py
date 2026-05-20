import sys, glob, os

directory = sys.argv[1] if len(sys.argv) > 1 else "."
files = sorted(glob.glob(os.path.join(directory, "*.dat")))[:2]

for fp in files:
    print(f"\n=== {os.path.basename(fp)} ===")
    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            tokens = line.strip().split("\t")
            if len(tokens) < 6:
                continue
            print(f"  line {i+1}  tokens[0~6]: {tokens[:6]}")
            if i >= 2:
                break
