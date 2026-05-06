#!/usr/bin/env python3
"""
Package a Dify plugin directory into a .difypkg file.
This is a pure-Python fallback when the official `dify` CLI is not available.
Usage:
    python scripts/package_plugin.py <source_dir> -o <output.difypkg>
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile


def _load_ignore_patterns(ignore_file: str) -> list[str]:
    patterns: list[str] = []
    if not os.path.isfile(ignore_file):
        return patterns
    with open(ignore_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    return patterns


def _should_ignore(rel_path: str, patterns: list[str]) -> bool:
    """Simplified gitignore-style matching."""
    rel = rel_path.replace("\\", "/")
    parts = rel.split("/")
    filename = parts[-1] if parts else ""

    for pat in patterns:
        pat = pat.strip()
        if not pat:
            continue

        # Directory pattern (e.g., __pycache__/)
        if pat.endswith("/"):
            dir_name = pat.rstrip("/")
            if dir_name in parts:
                return True
            continue

        # Exact match
        if pat == rel or pat == filename:
            return True

        # Prefix wildcard (e.g., *.pyc)
        if pat.startswith("*"):
            suffix = pat.lstrip("*")
            if filename.endswith(suffix):
                return True

        # Suffix wildcard (e.g., temp*)
        if pat.endswith("*"):
            prefix = pat.rstrip("*")
            if filename.startswith(prefix):
                return True

        # Contains wildcard in the middle (e.g., *.py[cod])
        if "*" in pat:
            segments = pat.split("*")
            if all(seg in filename for seg in segments if seg):
                return True

        # Any part match for directory-like patterns without trailing /
        if pat in parts:
            return True

    return False


def package_plugin(source_dir: str, output_path: str) -> None:
    source_dir = os.path.abspath(source_dir)
    difyignore_path = os.path.join(source_dir, ".difyignore")
    patterns = _load_ignore_patterns(difyignore_path)

    # Always ignore .git regardless of .difyignore
    if ".git/" not in patterns:
        patterns.append(".git/")

    manifest_path = os.path.join(source_dir, "manifest.yaml")
    if not os.path.isfile(manifest_path):
        print("ERROR: manifest.yaml not found in source directory.", file=sys.stderr)
        sys.exit(1)

    count = 0
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            # Filter out ignored directories to avoid descending into them
            dirs[:] = [
                d for d in dirs
                if not _should_ignore(
                    os.path.relpath(os.path.join(root, d), source_dir).replace("\\", "/") + "/",
                    patterns,
                )
            ]
            for name in files:
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, source_dir).replace("\\", "/")
                if _should_ignore(rel_path, patterns):
                    continue
                zf.write(abs_path, rel_path)
                count += 1

    print(f"Packaged {count} files into {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Package a Dify plugin into .difypkg")
    parser.add_argument("source", help="Plugin source directory")
    parser.add_argument("-o", "--output", required=True, help="Output .difypkg file path")
    args = parser.parse_args()
    package_plugin(args.source, args.output)


if __name__ == "__main__":
    main()
