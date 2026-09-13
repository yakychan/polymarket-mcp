"""Consistent SQLite backup; no credentials, no overwrite and no trade submission."""
import argparse
from pathlib import Path
import sqlite3


def backup(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_file():
        raise ValueError("Source database does not exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb"):
        pass
    original = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    copied = sqlite3.connect(output)
    try:
        original.backup(copied)
        if copied.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed")
    finally:
        copied.close()
        original.close()
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(backup(args.source, args.output))


if __name__ == "__main__":
    main()
