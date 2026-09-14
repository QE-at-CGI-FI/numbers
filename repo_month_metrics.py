#!/usr/bin/env python3
"""
git_metrics.py — collect monthly git activity metrics from one or more local
repositories and write them to a CSV in the same shape as:

    month,repos,commits,insertions,deletions,total_msg_chars,avg_insertions,avg_deletions,avg_msg_length

Usage:
    python3 git_metrics.py /path/to/repo [more/repos ...] -o metrics.csv

Options:
    -o, --output PATH     Output CSV path (default: git_metrics.csv)
    --author NAME_OR_EMAIL
                           Only count commits by this author (git log --author
                           substring match). Omit to include all authors.
    --since DATE           Only commits after this date (e.g. 2025-01-01)
    --until DATE            Only commits before this date
    --branch NAME          Only walk this branch/ref (default: current HEAD)
    --all-branches         Walk all refs (git log --all) instead of just HEAD
    --include-merges       Include merge commits (excluded by default, since
                            their diffstats can double-count changes)
    --full-message         Count the full commit message (subject + body) for
                            message-length stats (default). Use --subject-only
                            to count just the first line instead.
    --subject-only         Count only the commit subject line length.

Each positional argument is a path to a local git repository (a folder that
is, or is inside, a git working tree). Metrics from all given repos are
merged and grouped by calendar month (YYYY-MM, based on commit author date).
The "repos" column for a given month is the number of distinct repos that
had at least one qualifying commit that month.

Requires: git installed and on PATH. Pure standard library otherwise.
"""

import argparse
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

RECORD_SEP = "\x1e"  # separates commit metadata fields
UNIT_SEP = "\x02"    # marks the boundary before/after the commit message body
COMMIT_START = "\x01COMMIT\x01"


def run_git_log(repo_path, author, since, until, branch, all_branches, include_merges):
    """Run git log in repo_path and return raw stdout text."""
    pretty_fmt = (
        f"{COMMIT_START}%H{RECORD_SEP}%ad{RECORD_SEP}{UNIT_SEP}%B{UNIT_SEP}"
    )
    cmd = [
        "git", "log",
        f"--pretty=format:{pretty_fmt}",
        "--date=format:%Y-%m",
        "--shortstat",
    ]
    if not include_merges:
        cmd.append("--no-merges")
    if all_branches:
        cmd.append("--all")
    elif branch:
        cmd.append(branch)
    if author:
        cmd.append(f"--author={author}")
    if since:
        cmd.append(f"--since={since}")
    if until:
        cmd.append(f"--until={until}")

    result = subprocess.run(
        cmd, cwd=repo_path, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git log failed in {repo_path}:\n{result.stderr.strip()}"
        )
    return result.stdout


def parse_git_log(raw, subject_only):
    """Parse the raw git log output into a list of commit dicts."""
    commits = []
    # Split on commit boundaries; first split chunk before any COMMIT_START is empty/junk.
    chunks = raw.split(COMMIT_START)
    for chunk in chunks:
        if not chunk.strip():
            continue
        # chunk looks like: HASH<RS>MONTH<RS><US>MESSAGE<US>\n <shortstat line>\n\n
        try:
            head, rest = chunk.split(RECORD_SEP, 1)
            month, rest = rest.split(RECORD_SEP, 1)
        except ValueError:
            continue
        commit_hash = head.strip()
        month = month.strip()

        # message is wrapped between UNIT_SEP markers
        if UNIT_SEP not in rest:
            continue
        _, remainder = rest.split(UNIT_SEP, 1)
        if UNIT_SEP not in remainder:
            continue
        message, after = remainder.split(UNIT_SEP, 1)

        if subject_only:
            msg_text = message.strip().splitlines()[0] if message.strip() else ""
        else:
            msg_text = message.strip()

        insertions = 0
        deletions = 0
        # look for a shortstat line among the remaining lines, e.g.:
        #  " 3 files changed, 10 insertions(+), 2 deletions(-)"
        for line in after.splitlines():
            line = line.strip()
            if "changed" in line and ("insertion" in line or "deletion" in line):
                for part in line.split(","):
                    part = part.strip()
                    if "insertion" in part:
                        insertions = int(part.split()[0])
                    elif "deletion" in part:
                        deletions = int(part.split()[0])
                break

        commits.append({
            "hash": commit_hash,
            "month": month,
            "insertions": insertions,
            "deletions": deletions,
            "msg_len": len(msg_text),
        })
    return commits


def collect_metrics(repo_paths, author, since, until, branch, all_branches,
                     include_merges, subject_only):
    # month -> aggregate dict, plus set of repos active that month
    monthly = defaultdict(lambda: {
        "commits": 0, "insertions": 0, "deletions": 0,
        "total_msg_chars": 0, "repos": set(),
    })

    for repo_path in repo_paths:
        repo_path = str(Path(repo_path).expanduser())
        raw = run_git_log(repo_path, author, since, until, branch,
                           all_branches, include_merges)
        commits = parse_git_log(raw, subject_only)
        for c in commits:
            m = monthly[c["month"]]
            m["commits"] += 1
            m["insertions"] += c["insertions"]
            m["deletions"] += c["deletions"]
            m["total_msg_chars"] += c["msg_len"]
            m["repos"].add(repo_path)

    return monthly


def write_csv(monthly, output_path):
    rows = []
    for month in sorted(monthly.keys()):
        d = monthly[month]
        commits = d["commits"]
        insertions = d["insertions"]
        deletions = d["deletions"]
        total_msg_chars = d["total_msg_chars"]
        avg_insertions = round(insertions / commits, 1) if commits else 0.0
        avg_deletions = round(deletions / commits, 1) if commits else 0.0
        avg_msg_length = round(total_msg_chars / commits, 1) if commits else 0.0
        rows.append([
            month, len(d["repos"]), commits, insertions, deletions,
            total_msg_chars, avg_insertions, avg_deletions, avg_msg_length,
        ])

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "month", "repos", "commits", "insertions", "deletions",
            "total_msg_chars", "avg_insertions", "avg_deletions", "avg_msg_length",
        ])
        writer.writerows(rows)

    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Collect monthly git metrics from local repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("repos", nargs="+", help="Path(s) to local git repositories")
    parser.add_argument("-o", "--output", default="git_metrics.csv", help="Output CSV path")
    parser.add_argument("--author", default=None, help="Filter commits by author (substring match)")
    parser.add_argument("--since", default=None, help="Only commits after this date")
    parser.add_argument("--until", default=None, help="Only commits before this date")
    parser.add_argument("--branch", default=None, help="Branch/ref to walk (default: current HEAD)")
    parser.add_argument("--all-branches", action="store_true", help="Walk all refs instead of just HEAD")
    parser.add_argument("--include-merges", action="store_true", help="Include merge commits")
    msg_group = parser.add_mutually_exclusive_group()
    msg_group.add_argument("--full-message", action="store_true", default=True,
                            help="Count full commit message for length stats (default)")
    msg_group.add_argument("--subject-only", action="store_true",
                            help="Count only the commit subject line for length stats")
    args = parser.parse_args()

    subject_only = args.subject_only

    for repo in args.repos:
        if not (Path(repo).expanduser() / ".git").exists() and not Path(repo).expanduser().joinpath(".git").is_dir():
            # not fatal here; git log will error out with a clear message if it's not a repo
            pass

    try:
        monthly = collect_metrics(
            args.repos, args.author, args.since, args.until,
            args.branch, args.all_branches, args.include_merges, subject_only,
        )
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not monthly:
        print("No commits found matching the given filters.", file=sys.stderr)
        sys.exit(0)

    rows = write_csv(monthly, args.output)
    print(f"Wrote {len(rows)} month(s) of metrics to {args.output}")


if __name__ == "__main__":
    main()