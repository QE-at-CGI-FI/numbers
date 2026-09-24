#!/usr/bin/env python3
"""Find the first commit date that introduced any AI-tooling marker path
into every 'side' repo in repos-with-metrics.csv, using the authenticated
GitHub REST API. Resumable via a progress JSON file; stops gracefully and
saves progress if the rate limit runs low.
"""
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CANDIDATE_PATHS = [
    ".claude",
    ".github/skills",
    ".github/agents",
    ".github/copilot-instructions.md",
    ".cursor",
    "CLAUDE.md",
    "AGENTS.md",
]

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "..", "repos-with-metrics.csv")
PROGRESS_FILE = os.path.join(HERE, "ai_adoption_progress_all.json")

API = "https://api.github.com"
GH_TOKEN = os.environ.get("GH_TOKEN", "")


def load_repo_list():
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        return [(r["org"], r["repo"]) for r in reader if r["repo_type"] == "side"]


def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_progress(progress):
    tmp = PROGRESS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(progress, f)
    os.replace(tmp, PROGRESS_FILE)


def gh_request(url):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "numbers-ai-adoption-script",
    }
    if GH_TOKEN:
        headers["Authorization"] = f"Bearer {GH_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    # retry transient server/network errors (GitHub occasionally 500s on
    # commits?path= for some repos) before giving up
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                remaining = int(resp.headers.get("X-RateLimit-Remaining", "0"))
                link = resp.headers.get("Link", "")
                body = json.loads(resp.read().decode())
                return body, link, remaining, resp.status
        except urllib.error.HTTPError as e:
            remaining = int(e.headers.get("X-RateLimit-Remaining", "0"))
            if e.code in (404, 409):
                return [], "", remaining, e.code
            if e.code == 403:
                # rate limited or abuse-detection backoff
                return [], "", 0, 403
            if e.code < 500 or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(5 * (attempt + 1))


def last_page_url(link_header):
    if not link_header:
        return None
    for part in link_header.split(","):
        m = re.search(r'<([^>]+)>;\s*rel="last"', part)
        if m:
            return m.group(1)
    return None


def find_first_commit_for_path(owner, repo, path, rate_state):
    url = f"{API}/repos/{owner}/{repo}/commits?path={urllib.parse.quote(path)}&per_page=1"
    body, link, remaining, status = gh_request(url)
    rate_state["remaining"] = remaining
    if status == 404:
        return None, "repo_not_found"
    if status == 403:
        return None, "rate_limited"
    if status == 409 or not body:
        return None, "no_hits"

    last_url = last_page_url(link)
    if last_url is None:
        commit = body[0]
        return commit["commit"]["committer"]["date"], "ok"

    body2, _, remaining2, status2 = gh_request(last_url)
    rate_state["remaining"] = remaining2
    if status2 == 403:
        return None, "rate_limited"
    if not body2:
        return None, "no_hits"
    commit = body2[-1]
    return commit["commit"]["committer"]["date"], "ok"


def main():
    limit = None
    if len(sys.argv) > 1 and sys.argv[1] == "--limit":
        limit = int(sys.argv[2])

    repos = load_repo_list()
    progress = load_progress()
    rate_state = {"remaining": 5000}

    try:
        body, _, remaining, _ = gh_request(f"{API}/rate_limit")
        rate_state["remaining"] = body["resources"]["core"]["remaining"]
    except Exception as e:
        print(f"rate_limit check failed: {e}", file=sys.stderr)

    floor = 50
    limit_note = f", limit {limit} repos this run" if limit else ""
    print(f"Starting with {rate_state['remaining']} requests remaining, {len(repos)} repos to check{limit_note}", file=sys.stderr)

    done_count = 0
    for org, repo in repos:
        if limit is not None and done_count >= limit:
            print(f"Reached limit of {limit} repos this run, stopping.", file=sys.stderr)
            save_progress(progress)
            return

        key = f"{org}/{repo}"
        entry = progress.get(key)
        if entry is not None and entry.get("_complete"):
            continue

        entry = progress.setdefault(key, {})
        repo_missing = False
        for path in CANDIDATE_PATHS:
            if path in entry:
                if entry[path]["status"] == "repo_not_found":
                    repo_missing = True
                continue
            if repo_missing:
                entry[path] = {"date": None, "status": "repo_not_found"}
                continue
            if rate_state["remaining"] <= floor:
                print(f"Rate limit nearly exhausted at {done_count}/{len(repos)} repos, stopping.", file=sys.stderr)
                save_progress(progress)
                return
            try:
                date, status = find_first_commit_for_path(org, repo, path, rate_state)
            except Exception as e:
                # leave this repo incomplete so a rerun retries it
                print(f"{key} {path}: {e}, skipping repo for now", file=sys.stderr)
                status = "error"
                break
            if status == "rate_limited":
                print(f"Hit 403/rate-limit at {done_count}/{len(repos)} repos, stopping.", file=sys.stderr)
                save_progress(progress)
                return
            entry[path] = {"date": date, "status": status}
            if status == "repo_not_found":
                repo_missing = True

        if any(path not in entry for path in CANDIDATE_PATHS):
            continue
        entry["_complete"] = True
        done_count += 1
        if done_count % 20 == 0:
            print(f"...{done_count}/{len(repos)} repos done (remaining budget={rate_state['remaining']})", file=sys.stderr)
            save_progress(progress)

    save_progress(progress)
    print(f"Finished all {len(repos)} repos.", file=sys.stderr)


if __name__ == "__main__":
    main()
