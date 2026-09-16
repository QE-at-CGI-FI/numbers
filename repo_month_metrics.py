#!/usr/bin/env python3
"""
git_metrics.py — collect monthly git activity metrics from one or more local
repositories and write them to a CSV in the same shape as:

    month,repos,commits,insertions,deletions,total_msg_chars,avg_insertions,avg_deletions,avg_msg_length

Usage
-----
    # One or more repo paths:
    python3 git_metrics.py /path/to/repo1 /path/to/repo2 -o metrics.csv

    # Auto-discover every git repo under a parent directory (one level deep
    # or recursive with --scan-recursive):
    python3 git_metrics.py --scan /path/to/projects -o metrics.csv

    # Include all branches, not just the currently checked-out one:
    python3 git_metrics.py /path/to/repo --all-branches -o metrics.csv

    # Filter to a single author (name or email substring, case-insensitive):
    python3 git_metrics.py /path/to/repo --author "maaret.pyhajarvi@gmail.com"

Notes
-----
- "repos" in the output is the number of distinct repositories that had at
  least one commit in that month (useful when passing multiple repos).
- "commits" / "insertions" / "deletions" / "total_msg_chars" are summed
  across all repos for that month.
- avg_insertions / avg_deletions / avg_msg_length are per-commit averages
  for that month, rounded to 1 decimal place.
- Merge commits normally report no diffstat from `git log --shortstat`
  (that's git's default behaviour), so they count toward "commits" but
  contribute 0 insertions/deletions unless you pass --include-merges-diff,
  which asks git to diff merges against their first parent.
- Requires Python 3.7+ and git on PATH. No third-party dependencies.
"""

import argparse
import csv
import os
import re
import subprocess
import sys
from collections import defaultdict

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"

SHORTSTAT_RE = re.compile(
    r"(?:(\d+) files? changed)?"
    r"(?:, (\d+) insertions?\(\+\))?"
    r"(?:, (\d+) deletions?\(-\))?"
)


def find_git_repos(root, recursive=False):
    """Discover git repos under root. Non-recursive: only immediate children."""
    repos = []
    if os.path.isdir(os.path.join(root, ".git")):
        repos.append(root)
        if not recursive:
            return repos

    if recursive:
        for dirpath, dirnames, _ in os.walk(root):
            if ".git" in dirnames or os.path.isdir(os.path.join(dirpath, ".git")):
                repos.append(dirpath)
                dirnames[:] = []  # don't descend into a repo we already found
            else:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
    else:
        for entry in sorted(os.listdir(root)):
            candidate = os.path.join(root, entry)
            if os.path.isdir(os.path.join(candidate, ".git")):
                repos.append(candidate)

    # de-dupe while preserving order
    seen = set()
    unique = []
    for r in repos:
        rp = os.path.abspath(r)
        if rp not in seen:
            seen.add(rp)
            unique.append(rp)
    return unique


def run_git(repo, args):
    result = subprocess.run(
        ["git", "-C", repo] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {repo}:\n{result.stderr.strip()}"
        )
    return result.stdout


def collect_messages(repo, all_branches, author):
    """hash -> (year_month, message_length, author_name)"""
    fmt = f"%H{FIELD_SEP}%ad{FIELD_SEP}%an{FIELD_SEP}%B{RECORD_SEP}"
    args = ["log", "--date=format:%Y-%m", f"--pretty=format:{fmt}"]
    if all_branches:
        args.insert(1, "--all")
    if author:
        args += [f"--author={author}"]

    out = run_git(repo, args)
    info = {}
    for record in out.split(RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(FIELD_SEP, 3)
        if len(parts) != 4:
            continue
        commit_hash, month, author_name, message = parts
        info[commit_hash] = (month, len(message.strip()), author_name)
    return info


def collect_stats(repo, all_branches, author, include_merges_diff):
    """hash -> (insertions, deletions)"""
    args = ["log", "--pretty=format:%H", "--shortstat"]
    if include_merges_diff:
        args.append("-m")
        args.append("--first-parent")
    if all_branches:
        args.insert(1, "--all")
    if author:
        args += [f"--author={author}"]

    out = run_git(repo, args)
    stats = {}
    current_hash = None
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r"[0-9a-f]{7,40}", line):
            current_hash = line
            stats.setdefault(current_hash, (0, 0))
            continue
        m = SHORTSTAT_RE.search(line)
        if m and current_hash:
            ins = int(m.group(2) or 0)
            dels = int(m.group(3) or 0)
            prev_ins, prev_dels = stats.get(current_hash, (0, 0))
            stats[current_hash] = (prev_ins + ins, prev_dels + dels)
    return stats


def collect_repo_metrics(repo, all_branches, author, include_merges_diff):
    messages = collect_messages(repo, all_branches, author)
    stats = collect_stats(repo, all_branches, author, include_merges_diff)

    per_month = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0, "msg_chars": 0})
    for commit_hash, (month, msg_len, _author_name) in messages.items():
        ins, dels = stats.get(commit_hash, (0, 0))
        bucket = per_month[month]
        bucket["commits"] += 1
        bucket["insertions"] += ins
        bucket["deletions"] += dels
        bucket["msg_chars"] += msg_len
    return per_month


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repos", nargs="*", help="Path(s) to git repositories.")
    parser.add_argument("--scan", metavar="DIR", help="Directory to scan for git repos.")
    parser.add_argument("--scan-recursive", action="store_true", help="Scan --scan directory recursively.")
    parser.add_argument("--all-branches", action="store_true", help="Include commits from all branches (git log --all), not just HEAD.")
    parser.add_argument("--author", help="Filter to commits by this author (name or email substring, case-insensitive).")
    parser.add_argument("--include-merges-diff", action="store_true", help="Diff merge commits against their first parent so they contribute insertions/deletions too.")
    parser.add_argument("-o", "--output", default="git_metrics.csv", help="Output CSV path (default: git_metrics.csv).")
    args = parser.parse_args()

    repos = list(args.repos)
    if args.scan:
        repos += find_git_repos(args.scan, recursive=args.scan_recursive)

    if not repos:
        parser.error("No repositories given. Pass repo path(s) and/or --scan DIR.")

    repos = [os.path.abspath(r) for r in repos]
    for r in repos:
        if not os.path.isdir(os.path.join(r, ".git")):
            print(f"Warning: {r} does not look like a git repo root (no .git dir) — skipping.", file=sys.stderr)
    repos = [r for r in repos if os.path.isdir(os.path.join(r, ".git"))]

    if not repos:
        sys.exit("No valid git repositories found.")

    print(f"Scanning {len(repos)} repo(s):", file=sys.stderr)
    for r in repos:
        print(f"  - {r}", file=sys.stderr)

    # month -> {"repos": set(), "commits":, "insertions":, "deletions":, "msg_chars":}
    combined = defaultdict(lambda: {"repos": set(), "commits": 0, "insertions": 0, "deletions": 0, "msg_chars": 0})

    for repo in repos:
        try:
            per_month = collect_repo_metrics(repo, args.all_branches, args.author, args.include_merges_diff)
        except RuntimeError as e:
            print(f"Error processing {repo}: {e}", file=sys.stderr)
            continue

        for month, bucket in per_month.items():
            c = combined[month]
            c["repos"].add(repo)
            c["commits"] += bucket["commits"]
            c["insertions"] += bucket["insertions"]
            c["deletions"] += bucket["deletions"]
            c["msg_chars"] += bucket["msg_chars"]

    rows = []
    for month in sorted(combined.keys()):
        c = combined[month]
        commits = c["commits"]
        avg_ins = round(c["insertions"] / commits, 1) if commits else 0.0
        avg_del = round(c["deletions"] / commits, 1) if commits else 0.0
        avg_msg = round(c["msg_chars"] / commits, 1) if commits else 0.0
        rows.append([
            month,
            len(c["repos"]),
            commits,
            c["insertions"],
            c["deletions"],
            c["msg_chars"],
            avg_ins,
            avg_del,
            avg_msg,
        ])

    with open(args.output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "month", "repos", "commits", "insertions", "deletions",
            "total_msg_chars", "avg_insertions", "avg_deletions", "avg_msg_length",
        ])
        writer.writerows(rows)

    print(f"Wrote {len(rows)} month(s) to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()