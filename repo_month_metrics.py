#!/usr/bin/env python3
"""
git_monthly_metrics.py

Collect monthly git activity metrics from one or more local repositories
and write them to a CSV with columns:

    month,repos,commits,insertions,deletions,total_msg_chars,
    avg_insertions,avg_deletions,avg_msg_length

- month              : YYYY-MM
- repos              : number of distinct repos with >=1 commit that month
- commits            : total commit count that month (across all given repos)
- insertions         : total lines inserted that month
- deletions          : total lines deleted that month
- total_msg_chars    : total characters across all commit messages that month
                        (full message: subject + body, whitespace-trimmed)
- avg_insertions     : insertions / commits, rounded to 1 decimal
- avg_deletions      : deletions / commits, rounded to 1 decimal
- avg_msg_length     : total_msg_chars / commits, rounded to 1 decimal

Usage:
    python3 git_monthly_metrics.py /path/to/repo1 [/path/to/repo2 ...] \
        [--output metrics.csv] [--all-branches] [--merges] \
        [--author "name or email"] [--since 2025-01-01] [--until 2026-01-01]

Notes:
    * By default only the current branch (HEAD) history is walked and merge
      commits are excluded, since --numstat on merge commits is ambiguous.
      Pass --all-branches to walk every ref (git log --all), and --merges to
      include merge commits.
    * --author does a case-insensitive substring match against "Name <email>"
      (same as `git log --author=...`).
    * Requires only git + python3, no third-party packages.
"""

import argparse
import csv
import subprocess
import sys
from collections import defaultdict

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"


def run_git(repo_path, args):
    result = subprocess.run(
        ["git", "-C", repo_path] + args,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def collect_messages(repo_path, log_args):
    """Return {commit_hash: (month, msg_char_len)}"""
    fmt = f"%H{FIELD_SEP}%ad{FIELD_SEP}%B{RECORD_SEP}"
    out = run_git(
        repo_path,
        ["log", "--date=format:%Y-%m", f"--pretty=format:{fmt}"] + log_args,
    )
    data = {}
    for record in out.split(RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(FIELD_SEP, 2)
        if len(parts) != 3:
            continue
        commit_hash, month, message = parts
        data[commit_hash] = (month, len(message.strip()))
    return data


def collect_numstat(repo_path, log_args):
    """Return {commit_hash: (insertions, deletions)}"""
    out = run_git(
        repo_path,
        ["log", "--pretty=format:@@%H", "--numstat"] + log_args,
    )
    data = {}
    current_hash = None
    for line in out.splitlines():
        if line.startswith("@@"):
            current_hash = line[2:].strip()
            data[current_hash] = [0, 0]
            continue
        if not line.strip() or current_hash is None:
            continue
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        ins, dele = cols[0], cols[1]
        ins = int(ins) if ins.isdigit() else 0
        dele = int(dele) if dele.isdigit() else 0
        data[current_hash][0] += ins
        data[current_hash][1] += dele
    return {k: tuple(v) for k, v in data.items()}


def collect_repo_commits(repo_path, all_branches, include_merges, author, since, until):
    log_args = []
    if all_branches:
        log_args.append("--all")
    if not include_merges:
        log_args.append("--no-merges")
    if author:
        log_args.append(f"--author={author}")
    if since:
        log_args.append(f"--since={since}")
    if until:
        log_args.append(f"--until={until}")

    messages = collect_messages(repo_path, log_args)
    numstats = collect_numstat(repo_path, log_args)

    commits = []
    for commit_hash, (month, msg_len) in messages.items():
        ins, dele = numstats.get(commit_hash, (0, 0))
        commits.append((month, ins, dele, msg_len))
    return commits


def main():
    parser = argparse.ArgumentParser(description="Collect monthly git metrics from local repos.")
    parser.add_argument("repos", nargs="+", help="Path(s) to local git repositories")
    parser.add_argument("--output", "-o", default=None, help="Output CSV path (default: stdout)")
    parser.add_argument("--all-branches", action="store_true", help="Walk all refs (git log --all) instead of just HEAD")
    parser.add_argument("--merges", action="store_true", help="Include merge commits")
    parser.add_argument("--author", default=None, help="Filter by author (substring match on 'Name <email>')")
    parser.add_argument("--since", default=None, help="Only commits after this date (git --since format)")
    parser.add_argument("--until", default=None, help="Only commits before this date (git --until format)")
    args = parser.parse_args()

    # month -> { 'commits': int, 'ins': int, 'del': int, 'msg_chars': int, 'repos': set }
    monthly = defaultdict(lambda: {"commits": 0, "ins": 0, "del": 0, "msg_chars": 0, "repos": set()})

    for repo_path in args.repos:
        try:
            commits = collect_repo_commits(
                repo_path,
                all_branches=args.all_branches,
                include_merges=args.merges,
                author=args.author,
                since=args.since,
                until=args.until,
            )
        except subprocess.CalledProcessError as e:
            print(f"warning: skipping {repo_path}: {e.stderr.strip()}", file=sys.stderr)
            continue

        for month, ins, dele, msg_len in commits:
            m = monthly[month]
            m["commits"] += 1
            m["ins"] += ins
            m["del"] += dele
            m["msg_chars"] += msg_len
            m["repos"].add(repo_path)

    rows = []
    for month in sorted(monthly.keys()):
        m = monthly[month]
        commits = m["commits"]
        avg_ins = round(m["ins"] / commits, 1) if commits else 0.0
        avg_del = round(m["del"] / commits, 1) if commits else 0.0
        avg_msg = round(m["msg_chars"] / commits, 1) if commits else 0.0
        rows.append({
            "month": month,
            "repos": len(m["repos"]),
            "commits": commits,
            "insertions": m["ins"],
            "deletions": m["del"],
            "total_msg_chars": m["msg_chars"],
            "avg_insertions": avg_ins,
            "avg_deletions": avg_del,
            "avg_msg_length": avg_msg,
        })

    fieldnames = ["month", "repos", "commits", "insertions", "deletions",
                  "total_msg_chars", "avg_insertions", "avg_deletions", "avg_msg_length"]

    out_file = open(args.output, "w", newline="") if args.output else sys.stdout
    try:
        writer = csv.DictWriter(out_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    finally:
        if args.output:
            out_file.close()

    if args.output:
        print(f"Wrote {len(rows)} monthly rows to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()