"""Build an allowlisted source archive. Never include a user's environment or DB."""
import argparse
import hashlib
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = ("README.md", "README.en.md", "CHANGELOG.md", "CHANGELOG.en.md", "pyproject.toml", ".env.example", ".gitignore", "run_mcp.py")
GROUPS = {"polymarket_mcp": "*.py", "tests": "test_*.py", "docs": "*.md",
          "examples": "*", "scripts": "*.py", ".github/workflows": "*.yml"}


def package_files(root=ROOT):
    root = Path(root).resolve()
    files = [root / name for name in TOP_LEVEL]
    for folder, pattern in GROUPS.items():
        files.extend(p for p in (root / folder).glob(pattern) if p.is_file())
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError("Invalid share source: " + path.name)
        if path.parent.name == "examples" and path.suffix not in (".json", ".toml"):
            raise ValueError("Unexpected example type")
    return sorted(set(files))


def build(root=ROOT, output=None):
    root = Path(root).resolve()
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    output = Path(output) if output else root / "dist" / f"polymarket-mcp-{version}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    files = package_files(root)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"polymarket-mcp-{version}/" + path.relative_to(root).as_posix())
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
    return output, hashlib.sha256(output.read_bytes()).hexdigest(), len(files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    output, digest, count = build(output=args.output)
    print(f"{output}\nFiles: {count}\nSHA256: {digest}")


if __name__ == "__main__":
    main()
