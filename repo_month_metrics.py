#!/usr/bin/env python3
"""
git_metrics.py

Collect monthly commit metrics from one or more local git repositories and
write them to a CSV in this format:

    month,repos,commits,insertions,deletions,total_msg_chars,avg_insertions,avg_deletions,avg_msg_length

Columns
-------
month            YYYY-MM (based on commit author date, local repo timezone)
repos            number of distinct repos that had at least one commit that month
commits          total number of commits across all repos that month
insertions       total lines inserted that month
deletions        total lines deleted that month
total_msg_chars  total characters across all commit messages (full message body) that month
avg_insertions   insertions / commits
avg_deletions    deletions / commits
avg_msg_length   total_msg_chars / commits

Usage
-----
    python3 git_metrics.py /path/to/repo1 [/path/to/repo2 ...] -o metrics.csv

Options
-------
    -o, --output FILE     output CSV path (default: git_metrics.csv)
    --branch BRANCH       only consider this branch instead of --all refs
    --author AUTHOR       filter to commits by this author (git log --author= syntax)
    --since DATE          only commits after this date (git log --since= syntax)
    --until DATE          only commits before this date (git log --until= syntax)
    --include-merges      include merge commits (excluded by default)

Requires: Python 3.7+, and `git` available on PATH. No third-party
dependencies.
"""

import argparse
import csv
import subprocess
import sys
from collections import defaultdict

RECORD_SEP = "\x1e"  # ASCII Record Separator, marks the start of each commit
FIELD_SEP = "\x1f"   # ASCII Unit Separator, separates fields within a commit


def run_git_log(repo_path, branch=None, author=None, since=None, until=None,
                 include_merges=False):
    """Run `git log` in repo_path and yield (month, hash, msg_chars) plus
    numstat lines, one commit at a time, as a single interleaved text
    stream we then parse."""
    pretty_fmt = f"{RECORD_SEP}%H{FIELD_SEP}%ad{FIELD_SEP}%B{FIELD_SEP}"
    cmd = [
        "git", "-C", repo_path, "log",
        f"--pretty=format:{pretty_fmt}",
        "--date=format:%Y-%m",
        "--numstat",
    ]
    if not include_merges:
        cmd.append("--no-merges")
    if branch:
        cmd.append(branch)
    else:
        cmd.append("--all")
    if author:
        cmd.append(f"--author={author}")
    if since:
        cmd.append(f"--since={since}")
    if until:
        cmd.append(f"--until={until}")

    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git log failed for {repo_path!r}:\n{result.stderr.strip()}"
        )
    return result.stdout


def parse_log_output(raw):
    """Parse the interleaved commit-header + numstat output produced by
    run_git_log. Yields dicts: {month, insertions, deletions, msg_chars}."""
    # Split on the record separator; first chunk before any RS is empty/junk.
    records = raw.split(RECORD_SEP)
    for record in records:
        if not record.strip():
            continue
        parts = record.split(FIELD_SEP, 2)
        if len(parts) < 3:
            continue
        commit_hash, month, rest = parts
        # `rest` contains the commit message followed by a trailing
        # FIELD_SEP and then the numstat lines (one per changed file).
        if FIELD_SEP in rest:
            msg, numstat_block = rest.split(FIELD_SEP, 1)
        else:
            msg, numstat_block = rest, ""
        msg = msg.strip("\n")
        msg_chars = len(msg)

        insertions = 0
        deletions = 0
        for line in numstat_block.splitlines():
            line = line.strip()
            if not line:
                continue
            fields = line.split("\t")
            if len(fields) < 2:
                continue
            ins, dele = fields[0], fields[1]
            # Binary files report "-" for both counts; skip them.
            if ins.isdigit():
                insertions += int(ins)
            if dele.isdigit():
                deletions += int(dele)

        yield {
            "month": month,
            "insertions": insertions,
            "deletions": deletions,
            "msg_chars": msg_chars,
        }


def collect_metrics(repo_paths, **git_log_kwargs):
    """Aggregate metrics per month across all given repos."""
    monthly = defaultdict(lambda: {
        "repos": set(),
        "commits": 0,
        "insertions": 0,
        "deletions": 0,
        "total_msg_chars": 0,
    })

    for repo_path in repo_paths:
        raw = run_git_log(repo_path, **git_log_kwargs)
        for commit in parse_log_output(raw):
            m = monthly[commit["month"]]
            m["repos"].add(repo_path)
            m["commits"] += 1
            m["insertions"] += commit["insertions"]
            m["deletions"] += commit["deletions"]
            m["total_msg_chars"] += commit["msg_chars"]

    return monthly


def write_csv(monthly, output_path):
    fieldnames = [
        "month", "repos", "commits", "insertions", "deletions",
        "total_msg_chars", "avg_insertions", "avg_deletions", "avg_msg_length",
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for month in sorted(monthly.keys()):
            m = monthly[month]
            commits = m["commits"]
            avg_insertions = round(m["insertions"] / commits, 1) if commits else 0.0
            avg_deletions = round(m["deletions"] / commits, 1) if commits else 0.0
            avg_msg_length = round(m["total_msg_chars"] / commits, 1) if commits else 0.0
            writer.writerow([
                month,
                len(m["repos"]),
                commits,
                m["insertions"],
                m["deletions"],
                m["total_msg_chars"],
                avg_insertions,
                avg_deletions,
                avg_msg_length,
            ])


def main():
    parser = argparse.ArgumentParser(
        description="Collect monthly git commit metrics from one or more local repos."
    )
    parser.add_argument("repos", nargs="+", help="Path(s) to local git repositories")
    parser.add_argument("-o", "--output", default="git_metrics.csv", help="Output CSV path")
    parser.add_argument("--branch", default=None, help="Only consider this branch (default: --all refs)")
    parser.add_argument("--author", default=None, help="Filter to commits by this author")
    parser.add_argument("--since", default=None, help="Only commits after this date")
    parser.add_argument("--until", default=None, help="Only commits before this date")
    parser.add_argument("--include-merges", action="store_true", help="Include merge commits (excluded by default)")
    args = parser.parse_args()

    monthly = collect_metrics(
        args.repos,
        branch=args.branch,
        author=args.author,
        since=args.since,
        until=args.until,
        include_merges=args.include_merges,
    )

    if not monthly:
        print("No commits found matching the given criteria.", file=sys.stderr)
        sys.exit(1)

    write_csv(monthly, args.output)
    print(f"Wrote {sum(m['commits'] for m in monthly.values())} commits "
          f"across {len(monthly)} months to {args.output}")


if __name__ == "__main__":
    main()