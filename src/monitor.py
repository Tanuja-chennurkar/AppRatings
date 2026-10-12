"""Cautious comparison of theme shares across non-overlapping broad-sample windows."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import pandas as pd

MIN_WINDOW_N = 100
MIN_CHANGE = 0.05

def compare_windows(data: pd.DataFrame, baseline_start: str, baseline_end: str, current_start: str, current_end: str) -> pd.DataFrame:
    """Compare broad sample theme proportions; suppress alerts below minimum sample size."""
    df=data.copy()
    df["review_date"]=pd.to_datetime(df.review_date,errors="coerce",utc=True)
    broad=df[df.sample_strategy.eq("broad_recent") & df.review_id.notna()].drop_duplicates("review_id")
    b0,b1,c0,c1=[pd.Timestamp(x,tz="UTC") for x in (baseline_start,baseline_end,current_start,current_end)]
    if b0>b1 or c0>c1 or b1>=c0:
        raise ValueError("Provide ordered, non-overlapping baseline and current date windows.")
    windows={"baseline":broad[broad.review_date.between(b0,b1)],"current":broad[broad.review_date.between(c0,c1)]}
    def counts(frame: pd.DataFrame) -> tuple[int,dict[str,int]]:
        counter={}
        for row in frame.itertuples():
            for label in set(str(row.themes or "Other or unclear").split("|")):
                counter[label]=counter.get(label,0)+1
        return frame.review_id.nunique(),counter
    n0,cnt0=counts(windows["baseline"]); n1,cnt1=counts(windows["current"])
    records=[]
    for theme in sorted(set(cnt0)|set(cnt1)):
        x0,x1=cnt0.get(theme,0),cnt1.get(theme,0); p0=x0/n0 if n0 else 0; p1=x1/n1 if n1 else 0
        if n0<MIN_WINDOW_N or n1<MIN_WINDOW_N: z=None; p_value=None; alert=False; status="insufficient_sample"
        else:
            pooled=(x0+x1)/(n0+n1); se=math.sqrt(max(pooled*(1-pooled)*(1/n0+1/n1),1e-15)); z=(p1-p0)/se; p_value=math.erfc(abs(z)/math.sqrt(2)); alert=(p1-p0>=MIN_CHANGE and p_value<0.05); status="increase_flagged" if alert else "no_flag"
        records.append({"theme":theme,"baseline_n":n0,"baseline_mentions":x0,"baseline_share":p0,"current_n":n1,"current_mentions":x1,"current_share":p1,"share_change_pp":100*(p1-p0),"z_score":z,"p_value":p_value,"status":status,"interpretation":"Screening signal only; inspect reviews and confirm with internal telemetry."})
    return pd.DataFrame(records).sort_values("share_change_pp",ascending=False)

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data",type=Path,default=Path("data/processed/classified_reviews.csv"))
    parser.add_argument("--baseline-start",required=True); parser.add_argument("--baseline-end",required=True)
    parser.add_argument("--current-start",required=True); parser.add_argument("--current-end",required=True)
    parser.add_argument("--out",type=Path,default=Path("outputs/monitoring/theme_change.csv"))
    args=parser.parse_args()
    if not args.data.exists(): raise SystemExit(f"No classified data at {args.data}. Run `py -m src.pipeline analyze` first.")
    result=compare_windows(pd.read_csv(args.data),args.baseline_start,args.baseline_end,args.current_start,args.current_end)
    args.out.parent.mkdir(parents=True,exist_ok=True); result.to_csv(args.out,index=False)
    print(f"Wrote {args.out}; minimum n={MIN_WINDOW_N} per window, alert threshold >=5 pp and p<0.05. Flags are screening signals, not causal evidence.")

if __name__=="__main__": main()
