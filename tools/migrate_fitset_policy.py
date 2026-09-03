"""Write a legacy FitSet copy with an explicit gas-coefficient policy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_file(left, right):
    if os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right)):
        return True
    return os.path.exists(left) and os.path.exists(right) and os.path.samefile(left, right)


def _sanitize_history(entry):
    if not isinstance(entry, dict):
        raise ValueError("policy migration history entries must be objects")
    clean = {key: value for key, value in entry.items() if key != "source_path"}
    source = entry.get("source_name") or entry.get("source_path")
    if source:
        clean["source_name"] = os.path.basename(str(source).replace("\\", "/"))
    return clean


def migrate(source, output, allow_negative_gas, *, overwrite=False, replace_policy=False):
    if type(allow_negative_gas) is not bool:
        raise TypeError("allow_negative_gas must be an exact bool")
    source, output = os.path.abspath(source), os.path.abspath(output)
    if _same_file(source, output):
        raise ValueError("input and output must be different paths")
    if os.path.exists(output) and not overwrite:
        raise FileExistsError(f"output already exists: {output}")
    with open(source, encoding="utf-8") as fh:
        document = json.load(fh)
    channels = document.get("channels")
    if not isinstance(channels, dict) or not channels:
        raise ValueError("FitSet has no channels object")
    for channel in channels.values():
        if not isinstance(channel, dict):
            raise ValueError("FitSet channel must be an object")
        if "allow_negative_gas" in channel and not replace_policy:
            raise ValueError("FitSet already has an allow_negative_gas policy; use --replace-policy")
        channel["allow_negative_gas"] = allow_negative_gas
    history = document.pop("policy_migration", None)
    histories = document.get("policy_migrations", [])
    if not isinstance(histories, list):
        raise ValueError("policy_migrations must be a list")
    histories = [_sanitize_history(item) for item in histories]
    if history is not None:
        histories.append(_sanitize_history(history))
    histories.append({
        "tool": "tools/migrate_fitset_policy.py",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_name": os.path.basename(source),
        "source_sha256": sha256(source),
        "change": {"allow_negative_gas": allow_negative_gas, "scope": "all channels"},
    })
    document["policy_migrations"] = histories
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    target_dir = os.path.dirname(output) or "."
    fd, temporary = tempfile.mkstemp(prefix=".fitset-policy-", suffix=".json", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(document, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        if not overwrite and os.path.exists(output):
            raise FileExistsError(f"output already exists: {output}")
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--replace-policy", action="store_true")
    policy = parser.add_mutually_exclusive_group(required=True)
    policy.add_argument("--allow-negative-gas", action="store_true")
    policy.add_argument("--nonnegative-gas", action="store_true")
    args = parser.parse_args(argv)
    try:
        migrate(args.source, args.output, bool(args.allow_negative_gas), overwrite=args.overwrite,
                replace_policy=args.replace_policy)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(os.path.abspath(args.output))


if __name__ == "__main__":
    sys.exit(main())
