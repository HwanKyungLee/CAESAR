"""Safety contract for the legacy FitSet policy-copy tool."""
import json
import os
import tempfile

from migrate_fitset_policy import migrate, sha256


def main():
    with tempfile.TemporaryDirectory() as td:
        source = os.path.join(td, "old.json")
        output = os.path.join(td, "new.json")
        original = {"keep": {"nested": [1, 2]}, "channels": {"1": {"name": "x"}, "2": {}},
                    "policy_migration": {"source_path": r"C:\\Users\\Person\\private\\older.json",
                                         "source_sha256": "abc", "note": "preserve"},
                    "policy_migrations": [{"source_path": "/home/person/private/oldest.json",
                                           "source_sha256": "def"}]}
        with open(source, "w", encoding="utf-8") as fh:
            json.dump(original, fh)
        before = sha256(source)
        migrated = migrate(source, output, True)
        assert sha256(source) == before
        assert migrated["keep"] == original["keep"]
        assert all(c["allow_negative_gas"] is True for c in migrated["channels"].values())
        assert migrated["policy_migrations"][-1]["source_sha256"] == before
        assert migrated["policy_migrations"][-1]["source_name"] == "old.json"
        assert "source_path" not in migrated["policy_migrations"][-1]
        assert [h["source_name"] for h in migrated["policy_migrations"][:2]] == [
            "oldest.json", "older.json"]
        assert all("source_path" not in h for h in migrated["policy_migrations"])
        assert migrated["policy_migrations"][1]["note"] == "preserve"
        for bad_source, bad_output in ((source, source), (source, output)):
            try:
                migrate(bad_source, bad_output, False)
            except (ValueError, FileExistsError):
                pass
            else:
                raise AssertionError("unsafe output was accepted")
        try:
            migrate(source, os.path.join(td, "bad.json"), 1)
        except TypeError:
            pass
        else:
            raise AssertionError("non-bool policy was accepted")
        try:
            migrate(output, os.path.join(td, "again.json"), False)
        except ValueError as exc:
            assert "replace-policy" in str(exc)
        else:
            raise AssertionError("existing policy was silently replaced")
        migrated = migrate(output, os.path.join(td, "again.json"), False,
                           replace_policy=True)
        assert sha256(source) == before
        assert all(c["allow_negative_gas"] is False for c in migrated["channels"].values())
        assert len(migrated["policy_migrations"]) == 4
        alias = os.path.join(td, "alias.json")
        try:
            os.link(source, alias)
            migrate(source, alias, True, overwrite=True)
        except OSError:
            pass  # Filesystem may not permit hardlinks.
        except ValueError:
            pass
        else:
            raise AssertionError("same-file alias was accepted")
    print("test_migrate_fitset_policy: PASS")


if __name__ == "__main__":
    main()
