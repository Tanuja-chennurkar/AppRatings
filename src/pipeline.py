"""Collection, validation, transparent classification and analysis pipeline."""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

APP_ID = "com.moveinsync.ets"
SOURCE_URL = f"https://play.google.com/store/apps/details?id={APP_ID}"
FIELDS = ["review_id", "review_text", "rating", "review_date", "app_version", "developer_response", "developer_response_date", "country", "language", "collected_at", "sample_strategy", "source_url"]
THEMES: dict[str, list[str]] = {
    "Booking and trip creation": ["book", "booking", "trip", "request cab"],
    "Login, authentication, onboarding": ["login", "log in", "otp", "sign in", "password"],
    "Pickup timing and ETA": ["late", "delay", "pickup", "eta", "wait", "timing"],
    "Live tracking and GPS": ["track", "tracking", "gps", "location", "map"],
    "Driver or vehicle": ["driver", "cab", "vehicle", "car", "conductor"],
    "Route planning and detours": ["route", "detour", "divert", "wrong way"],
    "Safety verification": ["safety", "verify", "verification", "check in"],
    "Notifications and communication": ["notification", "alert", "message", "call", "inform"],
    "Crashes, loading, performance": ["crash", "loading", "slow", "hang", "freeze", "error"],
    "UI and usability": ["interface", "design", "confusing", "user friendly", "button"],
    "Shift or roster synchronization": ["shift", "roster", "schedule", "office"],
    "Cancellation and modification": ["cancel", "cancellation", "modify", "change trip"],
    "Customer support": ["support", "help", "complaint", "resolve", "response"],
}
SEVERITY_WORDS = ("unsafe", "stranded", "missed", "danger", "accident", "emergency", "no show", "not picked", "stuck")

def collect(country: str = "in", language: str = "en", broad_count: int = 500, negative_count: int = 200, delay: float = 1.0, out: Path = Path("data/raw")) -> None:
    """Fetch separate recent and targeted low-star samples; preserve each run as raw JSONL."""
    try:
        from google_play_scraper import Sort, reviews
    except ImportError as exc:
        raise RuntimeError("Install dependencies with `py -m pip install -r requirements.txt` and retry.") from exc
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    all_records = []
    for strategy, count, rating in (("broad_recent", broad_count, None), ("targeted_1_2_star", negative_count, 1)):
        if count <= 0: continue
        try:
            if strategy == "broad_recent":
                batch, _ = reviews(APP_ID, lang=language, country=country, sort=Sort.NEWEST, count=count, filter_score_with=None)
            else:
                # Explicitly gather 1 and 2 stars separately: targeted data never represents prevalence.
                batch = []
                for stars in (1, 2):
                    rows, _ = reviews(APP_ID, lang=language, country=country, sort=Sort.NEWEST, count=max(1, count // 2), filter_score_with=stars)
                    batch.extend(rows); time.sleep(max(0, delay))
            for row in batch:
                all_records.append({"review_id": row.get("reviewId"), "review_text": row.get("content"), "rating": row.get("score"), "review_date": row.get("at"), "app_version": row.get("reviewCreatedVersion"), "developer_response": row.get("replyContent"), "developer_response_date": row.get("repliedAt"), "country": country, "language": language, "collected_at": stamp, "sample_strategy": strategy, "source_url": SOURCE_URL})
            time.sleep(max(0, delay))
        except Exception as exc:
            logging.exception("Collection failed for %s", strategy)
            all_records.append({"sample_strategy": strategy, "collection_error": str(exc), "collected_at": stamp, "source_url": SOURCE_URL})
    target = out / f"reviews_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    target.write_text("".join(json.dumps(x, default=str, ensure_ascii=False) + "\n" for x in all_records), encoding="utf-8")
    print(f"Saved {len(all_records)} records/collection notices to {target}. Availability is partial and not a complete Play Store history.")

def classify(text: Any) -> dict[str, Any]:
    """Multi-label keyword baseline; evidence spans quote only words present in review."""
    raw = "" if pd.isna(text) else str(text)
    low = raw.lower()
    labels = [name for name, terms in THEMES.items() if any(term in low for term in terms)]
    evidence = next((term for name in labels for term in THEMES[name] if term in low), "")
    return {"themes": labels or ["Other or unclear"], "severity_indicator": any(x in low for x in SEVERITY_WORDS), "evidence_span": evidence, "sentiment": "negative" if any(x in low for x in ("bad", "worst", "poor", "hate", "not", "never", "late", "issue", "problem", "fail")) else "uncertain"}

def load_inputs(paths: list[Path]) -> pd.DataFrame:
    frames=[]
    for path in paths:
        if path.suffix.lower() == ".csv": frames.append(pd.read_csv(path))
        elif path.suffix.lower() == ".jsonl": frames.append(pd.read_json(path, lines=True))
        elif path.suffix.lower() == ".json": frames.append(pd.read_json(path))
        else: logging.warning("Skipped unsupported input: %s", path)
    if not frames: return pd.DataFrame(columns=FIELDS)
    df=pd.concat(frames, ignore_index=True)
    aliases={"reviewId":"review_id", "content":"review_text", "score":"rating", "at":"review_date", "reviewCreatedVersion":"app_version", "replyContent":"developer_response", "repliedAt":"developer_response_date"}
    return df.rename(columns={k:v for k,v in aliases.items() if k in df and v not in df})

def validate(df: pd.DataFrame, out: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Retain raw input; exclude only unusable records and report every exclusion."""
    out.mkdir(parents=True, exist_ok=True)
    for col in FIELDS:
        if col not in df: df[col] = pd.NA
    df["review_date"] = pd.to_datetime(df.review_date, errors="coerce", utc=True)
    df["rating"] = pd.to_numeric(df.rating, errors="coerce")
    reasons=[]
    for idx,row in df.iterrows():
        why=[]
        if pd.isna(row.review_text) or not str(row.review_text).strip(): why.append("blank_review_text")
        if pd.isna(row.rating) or row.rating not in range(1,6): why.append("invalid_rating")
        if pd.isna(row.review_date): why.append("invalid_review_date")
        reasons.append(";".join(why))
    df["exclusion_reason"] = reasons
    excluded=df[df.exclusion_reason.ne("")].copy(); clean=df[df.exclusion_reason.eq("")].copy()
    # A review can legitimately belong to both broad and targeted samples. Deduplicate
    # repeats within a strategy, but retain cross-strategy membership for separate analysis.
    duplicate_ids=int(clean.dropna(subset=["review_id"]).duplicated(subset=["review_id","sample_strategy"]).sum())
    cross_strategy_ids=int(clean.dropna(subset=["review_id"]).groupby("review_id").sample_strategy.nunique().gt(1).sum())
    clean=clean.drop_duplicates(subset=["review_id","sample_strategy"], keep="first") if clean.review_id.notna().any() else clean
    clean["duplicate_text_count"] = clean.review_text.astype(str).str.strip().str.lower().map(clean.review_text.astype(str).str.strip().str.lower().value_counts())
    counts=clean.sample_strategy.fillna("unspecified").value_counts().to_dict()
    report={"source_url":SOURCE_URL,"generated_at":datetime.now(timezone.utc).isoformat(),"input_rows":len(df),"valid_rows_including_cross_strategy_membership":len(clean),"unique_review_ids":int(clean.review_id.nunique()),"excluded_rows":len(excluded),"exclusion_reasons":excluded.exclusion_reason.value_counts().to_dict(),"duplicate_review_ids_removed_within_strategy":duplicate_ids,"review_ids_in_multiple_strategies":cross_strategy_ids,"duplicate_text_rows_diagnostic":int((clean.duplicate_text_count>1).sum()),"invalid_or_missing_app_version":int(clean.app_version.isna().sum()),"sample_strategy_counts":counts,"country_counts":clean.country.fillna("missing").value_counts().to_dict(),"language_counts":clean.language.fillna("missing").value_counts().to_dict(),"date_min":str(clean.review_date.min()) if len(clean) else None,"date_max":str(clean.review_date.max()) if len(clean) else None,"collection_errors":int(df.get("collection_error",pd.Series(dtype=object)).notna().sum())}
    clean.to_csv(out/"reviews_clean.csv",index=False); excluded.to_csv(out/"excluded_records.csv",index=False)
    (out/"data_quality.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    (out/"audit_summary.md").write_text("# Data quality audit\n\n"+"\n".join(f"- **{k.replace('_',' ').title()}:** {v}" for k,v in report.items()),encoding="utf-8")
    return clean,report

def analyze(df: pd.DataFrame, out: Path) -> dict[str, Any]:
    """Write data-backed analysis tables, maintaining broad and targeted samples separately."""
    out.mkdir(parents=True,exist_ok=True)
    if df.empty:
        summary={"status":"no_valid_reviews","message":"No valid review dataset. Collect public reviews or import a legitimate CSV."}
        (out/"analysis.json").write_text(json.dumps(summary,indent=2),encoding="utf-8"); return summary
    df=df.copy(); df["rating"]=pd.to_numeric(df.rating,errors="coerce")
    cls=df.review_text.map(classify); df["themes"]=cls.map(lambda x:"|".join(x["themes"])); df["severity_indicator"]=cls.map(lambda x:x["severity_indicator"]); df["evidence_span"]=cls.map(lambda x:x["evidence_span"])
    df.to_csv(out/"classified_reviews.csv",index=False)
    summaries={}
    for strategy,g in df.groupby(df.sample_strategy.fillna("unspecified")):
        response_dates=pd.to_datetime(g.developer_response_date,errors="coerce",utc=True)
        review_dates=pd.to_datetime(g.review_date,errors="coerce",utc=True)
        response_lag=(response_dates-review_dates).dt.total_seconds()/86400
        valid_lag=response_lag[response_lag.ge(0)]
        summaries[strategy]={"n":len(g),"date_min":str(g.review_date.min()),"date_max":str(g.review_date.max()),"rating_mean":float(g.rating.mean()),"rating_median":float(g.rating.median()),"rating_distribution":{str(int(k)):int(v) for k,v in g.rating.value_counts().sort_index().items()},"developer_response_coverage":float(g.developer_response.fillna("").astype(str).str.strip().ne("").mean()),"median_nonnegative_response_days":float(valid_lag.median()) if len(valid_lag) else None,"reviews_with_calculable_response_lag":int(len(valid_lag))}
        rating_themes=g.assign(theme=g.themes.str.split("|")).explode("theme")
        pd.crosstab(rating_themes.rating,rating_themes.theme).to_csv(out/f"theme_by_rating_{re.sub('[^a-z0-9]+','_',strategy.lower())}.csv")
    exploded=df.assign(theme=df.themes.str.split("|")).explode("theme")
    denom=df.groupby(df.sample_strategy.fillna("unspecified")).size().to_dict()
    table=exploded.groupby([exploded.sample_strategy.fillna("unspecified"),"theme"]).agg(unique_reviews=("review_id","nunique"),mentions=("theme","size"),severity_reviews=("severity_indicator","sum"),mean_rating=("rating","mean")).reset_index().rename(columns={"sample_strategy":"sample_type"})
    table["share_of_sample"]=table.apply(lambda r:r.unique_reviews/denom.get(r.sample_type,1),axis=1)
    table["confidence"]="Exploratory; unvalidated keyword rules"
    table["priority_score"]=(table.share_of_sample*40 + (6-table.mean_rating)*10 + table.severity_reviews.div(table.unique_reviews.clip(lower=1))*20)
    blockers={"Booking and trip creation","Pickup timing and ETA","Driver or vehicle","Safety verification","Login, authentication, onboarding"}
    table["core_journey_blocker_proxy"]=table.theme.isin(blockers)
    table["effort_estimate"]="Needs engineering scoping"
    table["likely_explanation_hypothesis"]="Unverified; review text does not establish technical cause"
    table["telemetry_to_check"]=table.theme.map({"Booking and trip creation":"Booking funnel completion and booking API errors","Pickup timing and ETA":"Planned vs actual pickup time; ETA error","Live tracking and GPS":"GPS update freshness and location permission state","Driver or vehicle":"Trip assignment, dispatch and vehicle/driver complaint records","Notifications and communication":"Notification delivery, latency and open rate","Crashes, loading, performance":"Crash-free sessions, ANR and screen/API latency","Customer support":"Contact rate and time to resolution"}).fillna("Inspect issue-specific journey events and support contacts")
    table["recommended_next_action"]="Manually review excerpts, then verify issue-specific telemetry before selecting a fix"
    actions={
        "Driver or vehicle":("Review assignment and vehicle/driver detail freshness; add a clear pickup escalation path.","Transport operations + mobile", "Medium"),
        "Pickup timing and ETA":("Compare promised and actual pickup times; show when ETA last refreshed and communicate validated delays.","Dispatch + mobile", "Medium"),
        "Live tracking and GPS":("Instrument location freshness and permission state; show an explicit stale-location state and recovery guidance.","Mobile + location platform", "Medium"),
        "Booking and trip creation":("Trace booking funnel failures; improve retry and error recovery only for confirmed failure points.","Booking product + backend", "Medium"),
        "Crashes, loading, performance":("Correlate review times with crash, ANR and latency dashboards; fix the confirmed highest-impact regression.","Mobile engineering", "Medium"),
        "Notifications and communication":("Audit delivery and lateness for trip updates; make in-app trip status available when push delivery fails.","Notifications + mobile", "Medium"),
        "Customer support":("Review resolution examples; route trip-blocking reports with trip context and measure time to resolution.","Support operations + product", "Small"),
    }
    table["recommended_intervention"]=table.theme.map(lambda theme:actions.get(theme,("Review representative evidence, then instrument and address the confirmed journey failure.","Product + relevant engineering", "Needs scoping"))[0])
    table["suggested_owner"]=table.theme.map(lambda theme:actions.get(theme,("Review representative evidence, then instrument and address the confirmed journey failure.","Product + relevant engineering", "Needs scoping"))[1])
    table["effort_estimate"]=table.theme.map(lambda theme:actions.get(theme,("Review representative evidence, then instrument and address the confirmed journey failure.","Product + relevant engineering", "Needs scoping"))[2]+"; estimate only")
    table["success_metric"]="Select an issue-specific task outcome and corresponding operational diagnostic after validation"
    table.to_csv(out/"issue_priorities.csv",index=False)
    version_rows=df.dropna(subset=["app_version"]).copy()
    if len(version_rows):
        version_rows.groupby(["sample_strategy","app_version"]).agg(review_count=("rating","size"),mean_rating=("rating","mean"),median_rating=("rating","median")).reset_index().to_csv(out/"app_version_summary.csv",index=False)
    else:
        pd.DataFrame(columns=["sample_strategy","app_version","review_count","mean_rating","median_rating"]).to_csv(out/"app_version_summary.csv",index=False)
    stop={"the","and","for","you","app","this","that","with","are","was","not","but","have","has","from","very","can","use","its","they","their","your","when","what","how","all","one","out","get","had","been","after","more","too","only","also","just","will","would","could","should","good","nice","best","please","thanks","thank","much"}
    term_rows=[]
    for strategy,g in df.groupby(df.sample_strategy.fillna("unspecified")):
        tokens=[]
        for review in g.review_text.dropna().astype(str):
            words=[w for w in re.findall(r"[a-z]{3,}",review.lower()) if w not in stop]
            tokens.extend(words); tokens.extend(f"{a} {b}" for a,b in zip(words,words[1:]))
        for term,n_term in Counter(tokens).most_common(30): term_rows.append({"sample_strategy":strategy,"term_or_phrase":term,"occurrences":n_term})
    pd.DataFrame(term_rows,columns=["sample_strategy","term_or_phrase","occurrences"]).to_csv(out/"common_terms.csv",index=False)
    trend_dates=pd.to_datetime(df.review_date,errors="coerce",utc=True).dt.tz_convert(None).dt.to_period("M").astype(str)
    df.assign(month=trend_dates).groupby(["sample_strategy","month"]).agg(review_count=("rating","size"),mean_rating=("rating","mean")).to_csv(out/"time_trends.csv")
    summary={"status":"complete","samples":summaries,"classification":"transparent keyword rules; multi-label; not manually validated","limitation":"Public review text cannot establish internal root cause; targeted samples are not prevalence estimates."}
    (out/"analysis.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8"); return summary

def main() -> None:
    p=argparse.ArgumentParser(description="MoveInSync public review analysis")
    sub=p.add_subparsers(dest="command",required=True)
    c=sub.add_parser("collect"); c.add_argument("--country",default="in"); c.add_argument("--language",default="en"); c.add_argument("--broad-count",type=int,default=500); c.add_argument("--negative-count",type=int,default=200); c.add_argument("--delay",type=float,default=1)
    v=sub.add_parser("analyze"); v.add_argument("inputs",nargs="*",type=Path); v.add_argument("--out",type=Path,default=Path("data/processed"))
    a=p.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    if a.command=="collect": collect(a.country,a.language,a.broad_count,a.negative_count,a.delay)
    else:
        inputs=a.inputs or list(Path("data/raw").glob("*.jsonl"))+list(Path("data/raw").glob("*.csv"))
        df=load_inputs(inputs); clean,_=validate(df,a.out); print(json.dumps(analyze(clean,a.out),indent=2,default=str))

if __name__=="__main__": main()
