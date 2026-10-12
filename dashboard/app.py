"""Interactive dashboard over generated analysis files; no fictional fallback data."""
from pathlib import Path
import json
import re
import pandas as pd
import plotly.express as px
import streamlit as st

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"/"processed"
st.set_page_config(page_title="MoveInSync Review Evidence",layout="wide")
st.title("MoveInSync employee app · review evidence")
st.caption("Public Google Play reviews are a selected sample. Review text does not establish internal root cause.")
path=DATA/"classified_reviews.csv"
if not path.exists():
    st.info("No generated review analysis is available yet. Collect reviews with `py -m src.pipeline collect` or place a legitimate CSV in `data/raw`, then run `py -m src.pipeline analyze`.")
    st.stop()
df=pd.read_csv(path)
if df.empty:
    st.info("No valid reviews were available after validation."); st.stop()
df["review_date"]=pd.to_datetime(df["review_date"],errors="coerce",utc=True)
strategies=sorted(df.sample_strategy.fillna("unspecified").unique())
with st.sidebar:
    st.header("Filters")
    chosen=st.multiselect("Sample type",strategies,default=strategies)
    ratings=st.multiselect("Rating",sorted(df.rating.dropna().unique()),default=sorted(df.rating.dropna().unique()))
    themes=sorted({x for v in df.themes.dropna().astype(str) for x in v.split("|")})
    selected_themes=st.multiselect("Theme",themes)
    dates=df.review_date.dropna()
    date_range=st.date_input("Date range",(dates.min().date(),dates.max().date())) if len(dates) else None
filtered=df[df.sample_strategy.fillna("unspecified").isin(chosen)&df.rating.isin(ratings)].copy()
if selected_themes: filtered=filtered[filtered.themes.fillna("").apply(lambda x:any(t in x.split("|") for t in selected_themes))]
if date_range and len(date_range)==2: filtered=filtered[filtered.review_date.dt.date.between(date_range[0],date_range[1])]
if any("targeted" in s for s in chosen): st.warning("Targeted low-star reviews are discovery samples. Their combined distribution and complaint shares do not estimate overall ratings or prevalence.")
if not len(filtered): st.warning("No reviews match these filters."); st.stop()
st.subheader("Executive view")
st.write(f"Filtered records: **{len(filtered):,}** · dates: **{filtered.review_date.min().date()} to {filtered.review_date.max().date()}**")
if "broad_recent" in chosen:
    broad=df[df.sample_strategy.eq("broad_recent")]
    if len(broad): st.metric("Broad sample mean rating",f"{broad.rating.mean():.2f} / 5",help=f"n={len(broad)}; selected recent reviews only")
else: st.caption("Broad-sample rating estimate is not shown because the broad sample is not selected.")
left,right=st.columns(2)
left.plotly_chart(px.histogram(filtered,x="rating",color="sample_strategy",barmode="group",title="Ratings in filtered sample"),use_container_width=True)
time=filtered.assign(month=filtered.review_date.dt.tz_convert(None).dt.to_period("M").astype(str)).groupby(["month","sample_strategy"]).size().reset_index(name="reviews")
right.plotly_chart(px.line(time,x="month",y="reviews",color="sample_strategy",markers=True,title="Review volume over time (sample-derived)"),use_container_width=True)
themes_df=filtered.assign(theme=filtered.themes.fillna("Other or unclear").str.split("|")).explode("theme")
st.plotly_chart(px.histogram(themes_df,y="theme",color="sample_strategy",barmode="group",title="Theme mentions; keyword rules are exploratory"),use_container_width=True)
st.caption("Severity flags match explicit disruption/safety terms in text; they are indicators for review, not a verified severity rating.")
versioned=filtered.dropna(subset=["app_version"])
if versioned.app_version.nunique()>1:
    version_summary=versioned.groupby(["sample_strategy","app_version"]).agg(reviews=("rating","size"),mean_rating=("rating","mean")).reset_index()
    st.plotly_chart(px.scatter(version_summary,x="app_version",y="mean_rating",size="reviews",color="sample_strategy",hover_data=["reviews"],title="App-version sample means (descriptive; uneven sample sizes)"),use_container_width=True)
    st.caption("Version comparisons are descriptive; avoid interpreting version-level rating differences as causal.")
terms_path=DATA/"common_terms.csv"
if terms_path.exists():
    terms=pd.read_csv(terms_path)
    terms=terms[terms.sample_strategy.isin(chosen)]
    st.subheader("Common words and phrases (exploratory)")
    st.dataframe(terms.groupby("term_or_phrase",as_index=False).occurrences.sum().sort_values("occurrences",ascending=False).head(20),use_container_width=True)
st.subheader("Representative review excerpts")
for _,row in filtered.dropna(subset=["review_text"]).head(10).iterrows():
    text=str(row.review_text).replace("\n"," ")
    text=re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}","[email redacted]",text)
    text=re.sub(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)","[phone redacted]",text)
    st.markdown(f"**{int(row.rating)}★ · {row.sample_strategy} · {row.review_date.date()}** — {text[:350]}")
if (DATA/"issue_priorities.csv").exists():
    st.subheader("Issue prioritization (separate sample types)")
    issues=pd.read_csv(DATA/"issue_priorities.csv")
    issues=issues[issues.sample_type.isin(chosen)]
    if selected_themes: issues=issues[issues.theme.isin(selected_themes)]
    st.dataframe(issues.sort_values("priority_score",ascending=False),use_container_width=True)
    st.download_button("Download issue table CSV",issues.to_csv(index=False),"issue_priorities_filtered.csv","text/csv")
st.download_button("Download filtered records CSV",filtered.to_csv(index=False),"filtered_reviews.csv","text/csv")
