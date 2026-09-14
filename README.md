# numbers
Experimenting with numbers.

## Collecting data

`scripts/generate_aggregate.py` reads a local git repository and produces a
monthly CSV in the format the visualizer (`index.html`) expects — either as
the default `aggregate.csv` (auto-loaded on page open) or as a file you upload
manually via the "Upload" button.

```
python3 scripts/generate_aggregate.py /path/to/repo -o aggregate.csv
```

- Pass multiple repo paths to aggregate stats across several repos at once.
- `--branch <name>` — walk a specific branch/ref instead of `HEAD`.
- `--since <date>` / `--until <date>` — limit the commit range (e.g. `--since 2024-01-01`).
- `--include-merges` — count merge commits too (excluded by default).
- Omit `-o` to print the CSV to stdout instead of writing a file.

Columns produced: `month, repos, commits, insertions, deletions,
total_msg_chars, avg_insertions, avg_deletions, avg_msg_length,
active_authors, net_lines, churn_ratio, files_changed, avg_files_per_commit`.

`scripts/generate_aggregate_old.py` is the same tool but only emits the
original 9-column schema (no `active_authors`/`net_lines`/`churn_ratio`/
`files_changed`/`avg_files_per_commit`), for when you need output matching
exactly what `aggregate.csv` used to contain.
