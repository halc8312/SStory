#!/usr/bin/env python3
"""
Terminology Checker for SStory Worldbuilding Documents

Scans Markdown files for terms that violate the Japanese-priority style guide.
Uses terminology/dictionary.yaml for pattern definitions.

Usage: python tools/terminology_check.py
Exit code 0 if no issues, 1 if issues found.
"""

import re
import os
import sys
import yaml
from pathlib import Path


ASCII_LETTER_RE = re.compile(r"[A-Za-z]")
JAPANESE_TEXT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff々]")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

def load_dictionary(dict_path):
    with open(dict_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data.get('terms', [])


def strip_non_prose(line):
    """Remove Markdown constructs whose contents are not prose."""
    line = re.sub(r"<!--.*?-->", "", line)
    line = re.sub(r"`[^`]*`", "", line)
    line = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", line)
    return re.sub(r"<[^>]+>", "", line)


def requires_japanese_context(term):
    """English rules apply only when they occur in Japanese prose by default."""
    if 'requires_japanese_context' in term:
        return bool(term['requires_japanese_context'])
    return bool(ASCII_LETTER_RE.search(term['pattern']))

def check_file(filepath, terms):
    """Check a single file for forbidden patterns. Returns list of (lineno, pattern, correct)."""
    issues = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        print(f"Warning: Could not read {filepath} as text, skipping.")
        return issues

    in_frontmatter = False
    fence_character = None
    fence_length = 0

    for lineno, raw_line in enumerate(lines, 1):
        stripped = raw_line.strip()

        if lineno == 1 and stripped == '---':
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == '---':
                in_frontmatter = False
            continue

        fence_match = FENCE_RE.match(raw_line)
        if fence_match:
            marker = fence_match.group(1)
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            continue
        if fence_character is not None:
            continue

        line = strip_non_prose(raw_line)
        for term in terms:
            pattern = term['pattern']
            if requires_japanese_context(term) and not JAPANESE_TEXT_RE.search(line):
                continue
            if re.search(pattern, line, re.IGNORECASE):
                issues.append((lineno, pattern, term.get('correct', '')))
    return issues

def main():
    repo_root = Path(__file__).parent.parent.resolve()
    dict_path = repo_root / 'terminology' / 'dictionary.yaml'
    if not dict_path.exists():
        print(f"Error: Dictionary not found at {dict_path}")
        sys.exit(1)

    terms = load_dictionary(dict_path)
    if not terms:
        print("Warning: No terms defined in dictionary.", file=sys.stderr)

    # Collect markdown files from world/ directory only
    md_files = []
    world_dir = repo_root / 'world'
    for root, dirs, files in os.walk(world_dir):
        for fname in files:
            if fname.endswith('.md'):
                md_files.append(os.path.join(root, fname))

    total_issues = 0
    for filepath in sorted(md_files):
        relpath = os.path.relpath(filepath, repo_root)
        issues = check_file(filepath, terms)
        if issues:
            for lineno, pattern, correct in issues:
                print(f"{relpath}:{lineno}: found '{pattern}' -> use '{correct}'")
            total_issues += len(issues)

    if total_issues:
        print(f"\nTotal terminology issues found: {total_issues}")
        print("Please fix the above issues or update the dictionary if they are intentional.")
        sys.exit(1)
    else:
        print("No terminology issues found.")
        sys.exit(0)

if __name__ == '__main__':
    main()
