#!/usr/bin/env python3
"""
git_metrics.py — collect monthly git activity metrics from one or more local
repositories and write them to a CSV matching this schema:

    month,repos,commits,insertions,deletions,total_msg_chars,
    avg_insertions,avg_deletions,avg_msg_length

Where, for each calendar month (YYYY-MM):
  repos            = number of distinct repos with >=1 commit that month
  commits          = total commits across all repos that month
  insertions       = total lines inserted (from numstat)
  deletions        = total lines deleted (from numstat)
  total_msg_chars  = total characters across all commit messages that month
  avg_insertions   = insertions / commits
  avg_deletions    = deletions / commits
  avg_msg_length   = total_msg_chars / commits

Usage:
    python3 git_metrics.py /path/to/repo [/path/to/repo2 ...] -o metrics.csv

Common options:
    --author SUBSTRING   only count commits whose author name or email
                          contains SUBSTRING (case-insensitive). Handy for
                          "just my own commits" — e.g. --author you@example.com
    --since DATE         passed straight to `git log --since=DATE`
    --until DATE         passed straight to `git log --until=DATE`
    --branch REF         branch/ref to walk (default: current HEAD in each repo)
    --include-merges     include merge commits (excluded by default, since
                          their numstat is usually empty/misleading)

Example — your own commits across two repos, from 2025-01 onward:
    python3 git_metrics.py ~/code/repo-a ~/code/repo-b \\
        --author maaret.pyhajarvi@gmail.com --since 2025-01-01 \\
        -o ts-pw-d365-ce-fo.csv
"""

import argparse
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

RECORD_START = "\x02"
FIELD_SEP = "\x1f"
RECORD_END = "\x03"


def run_git_log(repo_path, branch, author, since, until, include_merges):
    fmt = f"{RECORD_START}%H{FIELD_SEP}%ad{FIELD_SEP}%an{FIELD_SEP}%ae{FIELD_SEP}%B{RECORD_END}"
    cmd = [
        "git", "-C", str(repo_path), "log",
        f"--pretty=format:{fmt}",
        "--date=format:%Y-%m",
        "--numstat",
    ]
    if not include_merges:
        cmd.append("--no-merges")
    if author:
        cmd.append(f"--author={author}")
        cmd.append("-i")  # case-insensitive author match
    if since:
        cmd.append(f"--since={since}")
    if until:
        cmd.append(f"--until={until}")
    if branch:
        cmd.append(branch)

    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, check=True
        ).stdout
    except subprocess.CalledProcessError as e:
        print(f"git log failed for {repo_path}: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    return out


def parse_log(raw):
    """Yield (month, msg_char_count, insertions, deletions) per commit."""
    records = raw.split(RECORD_START)
    for rec in records:
        if not rec.strip():
            continue
        if RECORD_END not in rec:
            continue
        header, rest = rec.split(RECORD_END, 1)
        parts = header.split(FIELD_SEP)
        if len(parts) < 5:
            continue
        _commit_hash, month, _author_name, _author_email, message = (
            parts[0], parts[1], parts[2], parts[3], FIELD_SEP.join(parts[4:])
        )
        message = message.strip("\n")

        insertions = 0
        deletions = 0
        for line in rest.splitlines():
            line = line.strip()
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            ins, dele, _fname = cols
            if ins.isdigit():
                insertions += int(ins)
            if dele.isdigit():
                deletions += int(dele)

        yield month, len(message), insertions, deletions


def collect_metrics(repo_paths, branch, author, since, until, include_merges):
    # month -> dict of aggregate counters
    stats = defaultdict(lambda: {
        "commits": 0, "insertions": 0, "deletions": 0, "msg_chars": 0,
        "repos": set(),
    })

    for repo in repo_paths:
        repo = Path(repo).expanduser().resolve()
        if not (repo / ".git").exists():
            print(f"warning: {repo} does not look like a git repo root (no .git), skipping", file=sys.stderr)
            continue
        raw = run_git_log(repo, branch, author, since, until, include_merges)
        for month, msg_chars, insertions, deletions in parse_log(raw):
            s = stats[month]
            s["commits"] += 1
            s["insertions"] += insertions
            s["deletions"] += deletions
            s["msg_chars"] += msg_chars
            s["repos"].add(str(repo))

    return stats


def write_csv(stats, out_path):
    rows = []
    for month in sorted(stats.keys()):
        s = stats[month]
        commits = s["commits"]
        insertions = s["insertions"]
        deletions = s["deletions"]
        msg_chars = s["msg_chars"]
        repos = len(s["repos"])
        avg_insertions = round(insertions / commits, 1) if commits else 0.0
        avg_deletions = round(deletions / commits, 1) if commits else 0.0
        avg_msg_length = round(msg_chars / commits, 1) if commits else 0.0
        rows.append([
            month, repos, commits, insertions, deletions, msg_chars,
            avg_insertions, avg_deletions, avg_msg_length,
        ])

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "month", "repos", "commits", "insertions", "deletions",
            "total_msg_chars", "avg_insertions", "avg_deletions", "avg_msg_length",
        ])
        writer.writerows(rows)

    print(f"Wrote {len(rows)} monthly rows to {out_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repos", nargs="+", help="Path(s) to local git repositories")
    parser.add_argument("-o", "--output", default="git_metrics.csv", help="Output CSV path")
    parser.add_argument("--author", default=None, help="Filter commits by author name/email substring (case-insensitive)")
    parser.add_argument("--since", default=None, help="Only commits after this date (git --since format)")
    parser.add_argument("--until", default=None, help="Only commits before this date (git --until format)")
    parser.add_argument("--branch", default=None, help="Branch/ref to walk (default: repo's current HEAD)")
    parser.add_argument("--include-merges", action="store_true", help="Include merge commits (excluded by default)")
    args = parser.parse_args()

    stats = collect_metrics(
        args.repos, args.branch, args.author, args.since, args.until, args.include_merges
    )
    write_csv(stats, args.output)


if __name__ == "__main__":
    main()