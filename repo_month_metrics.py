#!/usr/bin/env python3
"""
git_metrics.py — Collect monthly git commit metrics from a local repository
and write them to CSV in the shape:

    month,repos,commits,insertions,deletions,total_msg_chars,avg_insertions,avg_deletions,avg_msg_length

Usage:
    python3 git_metrics.py /path/to/repo -o metrics.csv
    python3 git_metrics.py                 # defaults to current directory, git_metrics.csv

Options:
    -o, --output FILE     Output CSV path (default: git_metrics.csv)
    --all                 Include commits from all branches (git log --all)
                           instead of just the current branch (HEAD).
    --author PATTERN      Only count commits whose author name/email matches
                           PATTERN (passed to `git log --author`).
    --since DATE          Only count commits after DATE (e.g. 2025-01-01).
    --until DATE          Only count commits before DATE.

By default counts ALL commits on the current branch (HEAD), regardless of
author.

Definitions:
    repos            always 1 (single-repo run) — kept for CSV compatibility
    commits          total commits that month
    insertions       total lines inserted (from git numstat)
    deletions        total lines deleted (from git numstat)
    total_msg_chars  sum of commit message lengths (full message, subject+body,
                      trailing blank lines stripped)
    avg_insertions   insertions / commits
    avg_deletions    deletions / commits
    avg_msg_length   total_msg_chars / commits
"""

import argparse
import csv
import os
import re
import subprocess
import sys
from collections import defaultdict

RS = "\x1e"  # record separator between commits
US = "\x1f"  # unit separator between hash / date / message
NUMSTAT_RE = re.compile(r"^(\d+|-)\t(\d+|-)\t")


def is_git_repo(path):
    return subprocess.run(
        ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True
    ).stdout.strip() == "true"


def run_git_log(repo_path, use_all=False, author=None, since=None, until=None):
    fmt = f"{RS}%H{US}%ad{US}%B"
    cmd = ["git", "-C", repo_path, "log", "--date=format:%Y-%m",
           f"--pretty=format:{fmt}", "--numstat"]
    if use_all:
        cmd.append("--all")
    if author:
        cmd.extend(["--author", author])
    if since:
        cmd.extend(["--since", since])
    if until:
        cmd.extend(["--until", until])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"error: git log failed for {repo_path}: {result.stderr.strip()}")
    return result.stdout


def parse_commits(raw_output):
    """Yield (month, insertions, deletions, msg_len) per commit."""
    for chunk in raw_output.split(RS):
        if not chunk.strip():
            continue
        try:
            commit_hash, date, remainder = chunk.split(US, 2)
        except ValueError:
            continue
        month = date.strip()
        lines = remainder.split("\n")

        # Walk from the bottom collecting numstat lines; everything above
        # (minus trailing blank lines) is the commit message.
        i = len(lines) - 1
        insertions = 0
        deletions = 0
        while i >= 0:
            line = lines[i]
            if line.strip() == "":
                i -= 1
                continue
            m = NUMSTAT_RE.match(line)
            if m:
                added, removed = m.group(1), m.group(2)
                if added != "-":
                    insertions += int(added)
                if removed != "-":
                    deletions += int(removed)
                i -= 1
            else:
                break

        message = "\n".join(lines[:i + 1]).rstrip("\n")
        msg_len = len(message)
        yield month, insertions, deletions, msg_len


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo", nargs="?", default=".",
                         help="Path to the git repository (default: current directory)")
    parser.add_argument("-o", "--output", default="git_metrics.csv")
    parser.add_argument("--all", action="store_true", help="Use `git log --all`")
    parser.add_argument("--author", help="Filter commits by author pattern")
    parser.add_argument("--since", help="Only commits after this date")
    parser.add_argument("--until", help="Only commits before this date")
    args = parser.parse_args()

    repo_path = os.path.abspath(args.repo)
    if not is_git_repo(repo_path):
        sys.exit(f"error: {repo_path} is not a git repository")

    # month -> aggregate stats
    stats = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0,
                                  "total_msg_chars": 0})

    raw = run_git_log(repo_path, use_all=args.all, author=args.author,
                       since=args.since, until=args.until)
    for month, ins, dele, msg_len in parse_commits(raw):
        s = stats[month]
        s["commits"] += 1
        s["insertions"] += ins
        s["deletions"] += dele
        s["total_msg_chars"] += msg_len

    rows = []
    for month in sorted(stats.keys()):
        s = stats[month]
        commits = s["commits"]
        insertions = s["insertions"]
        deletions = s["deletions"]
        total_msg_chars = s["total_msg_chars"]
        avg_insertions = round(insertions / commits, 1) if commits else 0.0
        avg_deletions = round(deletions / commits, 1) if commits else 0.0
        avg_msg_length = round(total_msg_chars / commits, 1) if commits else 0.0
        rows.append([
            month,
            1,  # repos — single-repo run
            commits,
            insertions,
            deletions,
            total_msg_chars,
            avg_insertions,
            avg_deletions,
            avg_msg_length,
        ])

    with open(args.output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["month", "repos", "commits", "insertions", "deletions",
                          "total_msg_chars", "avg_insertions", "avg_deletions",
                          "avg_msg_length"])
        writer.writerows(rows)

    print(f"Wrote {len(rows)} month(s) of metrics for {repo_path} to {args.output}")


if __name__ == "__main__":
    main()