# MoveInSync FDE case study

An evidence-first, repeatable analysis of public Google Play reviews for package `com.moveinsync.ets`. The pipeline never fabricates reviews. Since the workspace initially contains no review dataset, dashboard and report outputs use a clearly marked pending-analysis state until collection or a legitimate CSV import succeeds.

## Setup (Windows)

Install Python 3.10+ and confirm `py --version`. Then run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

Verified with Python 3.11.8 on Windows. Dependencies were installed from `requirements.txt`; collection, analysis, report generation, dashboard smoke test, and automated tests were run.

## Collect public reviews

```powershell
py -m src.pipeline collect --country in --language en --broad-count 500 --negative-count 200 --delay 1
```

The collector accesses public review data through `google-play-scraper`, stores timestamped raw JSONL snapshots under `data/raw`, and records source, time, strategy, locale and available fields. Its broad sample is recent and bounded, not exhaustive. The targeted 1-star and 2-star samples are for discovery only; never combine them with the broad sample to estimate overall rating distribution or prevalence. Collection can fail due to availability, rate limits or changing access; rerun later or import a legitimate export. Respect Google Play terms and applicable restrictions.

## Import, validate and analyze

Place a legitimate CSV export in `data/raw/`. Recognized columns include `review_id`, `review_text`, `rating`, `review_date`, `app_version`, `developer_response`, `developer_response_date`, `country`, `language`, `sample_strategy`; standard scraper columns (`reviewId`, `content`, `score`, `at`) are mapped. Mark imported records' strategy honestly. Then:

```powershell
py -m src.pipeline analyze
```

Outputs include excluded records, clean reviews, JSON quality report, audit Markdown, classified data, theme/rating table, trend table, app-version and common-term summaries, and separate per-strategy metrics. Duplicate text is diagnostic only. Review IDs are deduplicated within a sample strategy; cross-strategy membership is retained and reported.

## Dashboard and deliverables

```powershell
py -m streamlit run dashboard/app.py
py -m src.deliverables
```

The project Streamlit config hides developer toolbar controls, including Deploy.

The dashboard reads generated files and displays no fictional findings. Deliverables are written under `outputs/reports/` and `outputs/presentations/`. Re-run analysis after each collection. To screen theme-share changes across non-overlapping review-date windows:

```powershell
py -m src.monitor --baseline-start 2026-08-09 --baseline-end 2026-09-08 --current-start 2026-09-09 --current-end 2026-10-09
```

The monitor flags increases only when both windows have at least 100 unique broad-sample reviews, the change is at least 5 percentage points, and the two-proportion screen has p<0.05. Treat flags as investigation prompts; reviews may not be independent and text cannot establish causation. Timestamped raw snapshots preserve history, but each fetch remains a partial view rather than a complete history.

## Methodology and interpretation

The public source is the official [Google Play listing](https://play.google.com/store/apps/details?id=com.moveinsync.ets). Categories are transparent keyword rules, allow multiple themes and include an Other/unclear fallback. Severity flags match disruption/safety phrases and do not establish harm. The repository includes a small synthetic unit-test fixture only; it is never used in analysis. No LLM is called, no human-labeled validation set is claimed, and no classification precision/recall/F1 is reported. Prioritization keeps share, rating, severity indicators and an explicitly heuristic score visible; score is not a causal estimate. Possible causes require internal confirmation. No MoveInSync telemetry or architecture was available.

Recommended follow-up measures should be selected based on observed themes: booking completion/API errors, pickup ETA error, GPS freshness, crash-free sessions, notification delivery, and support resolution are diagnostic metrics; issue-specific employee task success and subsequent review sentiment are outcomes. Evaluate with staged rollout and a holdout or comparable pre/post window. Do not promise rating lift.

## Tests

```powershell
py -m pytest
```

Tests cover multi-label evidence extraction, cleaning exclusions, and duplicate-text retention. All records should remain identifiable by sample strategy. Do not report validation metrics without manually labeled ground truth.

The displayed priority score is `40 × issue share + 10 × (6 − issue mean rating) + 20 × severity-indicator share`. It is an uncalibrated ranking aid, not an impact or causal estimate; component values and sample denominators are retained alongside it. Journey-blocker flags are proxies, and engineering effort remains unscoped until telemetry and implementation context are available.
