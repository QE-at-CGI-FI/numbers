#!/usr/bin/env python3
"""Generate aggregate.csv-format monthly commit stats from local git repositories.

Matches aggregate.csv's original 9-column schema exactly (no extra columns).
See generate_aggregate.py for a version with additional metrics
(active_authors, net_lines, churn_ratio, files_changed).

Usage:
    python3 scripts/generate_aggregate_old.py /path/to/repo [more/repos ...] > aggregate.csv
    python3 scripts/generate_aggregate_old.py .  --since 2024-01-01 --output aggregate.csv
"""
import argparse
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

RS = '\x1e'  # record separator between commits
FS = '\x1f'  # field separator within a commit header


def run_git_log(repo, branch, include_merges, since, until):
    fmt = f'{RS}%H{FS}%ad{FS}%s'
    cmd = ['git', '-C', str(repo), 'log', branch,
           '--date=format:%Y-%m', f'--pretty=format:{fmt}', '--numstat']
    if not include_merges:
        cmd.insert(4, '--no-merges')
    if since:
        cmd.append(f'--since={since}')
    if until:
        cmd.append(f'--until={until}')
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'git log failed for {repo}: {result.stderr.strip()}')
    return result.stdout


def parse_commits(output):
    """Yield (month, insertions, deletions, subject_length) per commit."""
    for chunk in output.split(RS):
        if not chunk.strip():
            continue
        lines = chunk.split('\n')
        _commit_hash, month, subject = lines[0].split(FS)
        insertions = deletions = 0
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            added, removed = parts[0], parts[1]
            insertions += int(added) if added.isdigit() else 0
            deletions += int(removed) if removed.isdigit() else 0
        yield month, insertions, deletions, len(subject)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repos', nargs='*', default=['.'], help='path(s) to local git repositories')
    parser.add_argument('-o', '--output', help='output CSV path (default: stdout)')
    parser.add_argument('--branch', default='HEAD', help='branch/ref to walk (default: HEAD)')
    parser.add_argument('--since', help='only count commits after this date (e.g. 2024-01-01)')
    parser.add_argument('--until', help='only count commits before this date')
    parser.add_argument('--include-merges', action='store_true', help='include merge commits (excluded by default)')
    args = parser.parse_args()

    monthly = defaultdict(lambda: {'commits': 0, 'insertions': 0, 'deletions': 0, 'msg_chars': 0, 'repos': set()})

    for repo in args.repos:
        repo_path = Path(repo).resolve()
        if not (repo_path / '.git').exists():
            print(f'warning: {repo_path} does not look like a git repo root, skipping', file=sys.stderr)
            continue
        output = run_git_log(repo_path, args.branch, args.include_merges, args.since, args.until)
        for month, insertions, deletions, msg_len in parse_commits(output):
            m = monthly[month]
            m['commits'] += 1
            m['insertions'] += insertions
            m['deletions'] += deletions
            m['msg_chars'] += msg_len
            m['repos'].add(str(repo_path))

    out = open(args.output, 'w', newline='') if args.output else sys.stdout
    writer = csv.writer(out)
    writer.writerow(['month', 'repos', 'commits', 'insertions', 'deletions',
                      'total_msg_chars', 'avg_insertions', 'avg_deletions', 'avg_msg_length'])
    for month in sorted(monthly):
        d = monthly[month]
        c = d['commits']
        writer.writerow([
            month, len(d['repos']), c, d['insertions'], d['deletions'], d['msg_chars'],
            round(d['insertions'] / c, 1) if c else 0,
            round(d['deletions'] / c, 1) if c else 0,
            round(d['msg_chars'] / c, 1) if c else 0,
        ])
    if args.output:
        out.close()
        print(f'Wrote {args.output}', file=sys.stderr)


if __name__ == '__main__':
    main()
