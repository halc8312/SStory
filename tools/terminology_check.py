#!/usr/bin/env python3
"""
Terminology Checker for SStory Worldbuilding Documents

Scans Markdown files for terms that violate the Japanese-priority style guide.
Uses terminology/dictionary.yaml for pattern definitions.

Usage: python tools/terminology_check.py
Exit code 0 if no issues, 1 if issues found.
"""

import os
import sys
import re
import yaml
from pathlib import Path

def load_dictionary(dict_path):
    with open(dict_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data.get('terms', [])

def check_file(filepath, terms):
    """Check a single file for forbidden patterns. Returns list of (lineno, pattern, correct)."""
    issues = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        print(f"Warning: Could not read {filepath} as text, skipping.")
        return issues

    for lineno, line in enumerate(lines, 1):
        # Optionally skip lines inside code fences? We'll check all lines.
        for term in terms:
            pattern = term['pattern']
            # Use regex search; pattern may contain regex special chars, so we treat as literal unless regex?
            # For simplicity, use regex. Patterns should be escaped if needed.
            if re.search(pattern, line, re.IGNORECASE):
                # Found a match
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
        print("✅ No terminology issues found.")
        sys.exit(0)

if __name__ == '__main__':
    main()
