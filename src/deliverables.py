"""Generate editable Markdown, PDF and PowerPoint summaries from current analysis outputs."""
from pathlib import Path
import json
import re
from html import escape
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE

ROOT=Path(__file__).resolve().parents[1]
PROC=ROOT/"data"/"processed"
OUT=ROOT/"outputs"

def generate() -> None:
    OUT.mkdir(exist_ok=True); (OUT/"reports").mkdir(exist_ok=True); (OUT/"presentations").mkdir(exist_ok=True)
    report=OUT/"reports"/"candidate_report.md"
    analysis=json.loads((PROC/"analysis.json").read_text(encoding="utf-8")) if (PROC/"analysis.json").exists() else {"status":"pending","message":"No valid review analysis generated yet."}
    q=json.loads((PROC/"data_quality.json").read_text(encoding="utf-8")) if (PROC/"data_quality.json").exists() else {}
    broad=analysis.get("samples",{}).get("broad_recent",{})
    targeted=analysis.get("samples",{}).get("targeted_1_2_star",{})
    lines=["# MoveInSync FDE case study: public review evidence", "", "## Executive summary", "", f"Analysis status: **{analysis.get('status','pending')}**. {analysis.get('message','')} ", "", "## Source and method", "", "Source: official Google Play listing [MoveInSync employee app](https://play.google.com/store/apps/details?id=com.moveinsync.ets). Collection uses `google-play-scraper` when available. Samples are bounded, recent public reviews, not a complete store history. Broad recent and targeted 1–2 star samples remain separate.", "", "## Dataset coverage and quality", "", f"{json.dumps(q,indent=2) if q else 'No validated dataset yet.'}", "", "## Rating analysis", "", "Broad recent sample estimates apply only to the collected sample, not all Play Store reviews. Targeted 1–2-star results are shown separately and are not prevalence estimates.", "", "## Complaint taxonomy and validation", "", "Keyword categories are exploratory, multi-label rules. No manual validation set is provided, so no classification precision, recall or F1 is claimed. Root causes require internal telemetry.", "", "## Key findings and recommendations", "", "Observed complaint themes are counts of reviews matched by explicit keywords. A keyword match is evidence of text mention, not a confirmed product defect or cause. Recommended next action is to review the excerpts, verify funnel/operational telemetry, and assign an owner only after validating the failure mode.", "", "## Roadmap and metrics", "", "Immediate: manually review the highest-frequency broad-sample excerpts and check associated booking or trip records. Near term: instrument and address the validated failure mode; select outcome and operational metrics tied to that issue. Longer term: evaluate platform changes with staged rollout and a holdout or comparable pre/post window. Do not infer rating lift from these samples.", "", "## Monitoring design", "", "Rerun collection and analysis periodically; retain timestamped raw files. Compare broad samples only against like-for-like country/language/strategy windows. Flag theme increases only after at least 100 reviews in each comparison window and inspect uncertainty; this threshold is a screening default, not a guarantee of significance.", "", "## Limitations", "", "Public reviews are self-selected and may be edited or unavailable later. Targeted low-star samples cannot estimate prevalence. Keyword categories can miss sarcasm/context and are not measured classification quality. No MoveInSync telemetry or internal architecture was available; no causal claims or rating lift forecasts are made.", "", "## Reproducibility", "", "See README for setup, collection, CSV import, dashboard and deliverables. The repository is designed to use Python, pandas, NumPy, Plotly, Streamlit, google-play-scraper, ReportLab and python-pptx; no LLM calls are made."]
    if broad:
        br=broad.get("rating_distribution",{}); bn=max(int(broad.get("n",0)),1)
        lines += ["", "## Broad sample rating results", "", f"N={bn}; dates {broad.get('date_min','')[:10]} to {broad.get('date_max','')[:10]}; sample mean {broad.get('rating_mean',0):.2f}/5; median {broad.get('rating_median',0):.1f}.", "", "| Stars | Reviews | Share |", "|---:|---:|---:|"]
        for star,count in br.items(): lines.append(f"| {star} | {count} | {100*int(count)/bn:.1f}% |")
        lines += ["", f"Targeted low-rating discovery sample: n={targeted.get('n',0)}; ratings={targeted.get('rating_distribution',{})}. Do not interpret as overall prevalence."]
    if (PROC/"issue_priorities.csv").exists():
        table=pd.read_csv(PROC/"issue_priorities.csv").sort_values("priority_score",ascending=False)
        if len(table):
            lines += ["", "## Data-backed theme table", "", "```text\n"+table.to_string(index=False)+"\n```" ]
    reviews=PROC/"classified_reviews.csv"
    if reviews.exists():
        data=pd.read_csv(reviews)
        data=data[data.sample_strategy.eq("broad_recent") & data.rating.le(2)].dropna(subset=["review_text"])
        if len(data):
            lines += ["", "## Representative low-rating excerpts", "", "Excerpts are shortened and basic contact details redacted. They illustrate text, not verified causes."]
            for _,row in data.head(6).iterrows():
                excerpt=re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}","[email redacted]",str(row.review_text))
                excerpt=re.sub(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)","[phone redacted]",excerpt)
                lines.append(f"- **{int(row.rating)} star, broad recent:** {excerpt[:240].replace(chr(10),' ')}")
    report.write_text("\n".join(lines),encoding="utf-8")
    top_text="No valid data yet."
    fix_text="Validate themes with review evidence and internal telemetry before choosing fixes."
    table=pd.DataFrame()
    if (PROC/"issue_priorities.csv").exists():
        table=pd.read_csv(PROC/"issue_priorities.csv")
        it=table[table.sample_type.eq("broad_recent") & ~table.theme.eq("Other or unclear")].sort_values("unique_reviews",ascending=False)
        if len(it): top_text="\n".join(f"{r.theme}: {int(r.unique_reviews)} / {broad.get('n',0)} broad reviews" for r in it.head(5).itertuples())
        if len(it): fix_text="\n".join(f"{r.theme} ({int(r.unique_reviews)}/{broad.get('n',0)}): {r.recommended_intervention}" for r in it.head(3).itertuples())
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small",parent=styles["BodyText"],fontSize=8,leading=10))
    story=[Paragraph("MoveInSync FDE Case Study",styles["Title"]),Paragraph("Public Google Play review evidence and product action plan",styles["Heading2"]),Spacer(1,8)]
    story += [Paragraph("Executive summary",styles["Heading1"])]
    if broad:
        n=int(broad.get("n",0)); low=sum(int(broad.get("rating_distribution",{}).get(str(s),0)) for s in (1,2))
        story.append(Paragraph(f"The bounded broad recent sample contains <b>{n}</b> reviews from {broad.get('date_min','')[:10]} to {broad.get('date_max','')[:10]}. Its mean rating is <b>{broad.get('rating_mean',0):.2f}/5</b> (median {broad.get('rating_median',0):.1f}); {low} of {n} reviews ({100*low/n:.1f}%) are 1-2 star. This describes only the collected sample, not all Play Store ratings. The separate targeted sample has {targeted.get('n',0)} reviews and is for low-rating discovery, not prevalence estimation.</Paragraph>"))
    else: story.append(Paragraph("No valid dataset is available; findings are pending.",styles["BodyText"]))
    story += [Spacer(1,7),Paragraph("Source and scope",styles["Heading1"]),Paragraph("Official Google Play listing for package com.moveinsync.ets. Collected with google-play-scraper on 2026-10-11 (UTC). Bounded recent fetch; not a complete store history. Broad and targeted samples remain separate.",styles["BodyText"]),Spacer(1,6),Paragraph("Coverage and data quality",styles["Heading1"])]
    cov=[["Measure","Result"],["Sample memberships",str(q.get("valid_rows_including_cross_strategy_membership","pending"))],["Unique review IDs",str(q.get("unique_review_ids","pending"))],["IDs in both strategies",str(q.get("review_ids_in_multiple_strategies",0))],["Missing app version",str(q.get("invalid_or_missing_app_version","pending"))],["Invalid/excluded rows",str(q.get("excluded_rows","pending"))],["Collection errors",str(q.get("collection_errors","pending"))]]
    story.append(Table(cov,colWidths=[220,270],style=TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17324D")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#C9D4DF")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F1F5F8")]),("FONTSIZE",(0,0),(-1,-1),9), ("PADDING",(0,0),(-1,-1),5)])))
    story += [Spacer(1,7),Paragraph("Rating patterns: broad recent sample",styles["Heading1"])]
    rating_rows=[["Stars","Reviews","Share"]]
    for star,count in broad.get("rating_distribution",{}).items(): rating_rows.append([f"{star} star",str(count),f"{100*int(count)/max(int(broad.get('n',1)),1):.1f}%"])
    story.append(Table(rating_rows,colWidths=[130,130,130],style=TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17324D")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#C9D4DF")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F1F5F8")]),("FONTSIZE",(0,0),(-1,-1),9),("PADDING",(0,0),(-1,-1),5)])))
    story += [Spacer(1,7),Paragraph("Complaint themes and priorities",styles["Heading1"]),Paragraph("Keyword matches are exploratory evidence of mentions. They do not establish technical defects or causes. Priority score is a heuristic; review counts, sample denominator, mean rating and severity flags are shown separately.",styles["BodyText"])]
    if len(table):
        btab=table[table.sample_type.eq("broad_recent") & ~table.theme.eq("Other or unclear")].sort_values("unique_reviews",ascending=False).head(8)
        data=[["Theme","Reviews / n","Mean stars","Severity flags"]]
        for row in btab.itertuples(): data.append([row.theme,f"{int(row.unique_reviews)} / {int(broad.get('n',0))}",f"{row.mean_rating:.2f}",str(int(row.severity_reviews))])
        story.append(Table(data,colWidths=[205,90,80,95],style=TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17324D")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#C9D4DF")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F1F5F8")]),("FONTSIZE",(0,0),(-1,-1),8),("PADDING",(0,0),(-1,-1),4)])))
        story += [Spacer(1,5),Paragraph("Recommended interventions to validate",styles["Heading2"])]
        recs=[[Paragraph("Theme",styles["Small"]),Paragraph("Next step",styles["Small"]),Paragraph("Suggested owner / effort",styles["Small"])]]
        for row in btab.head(5).itertuples(): recs.append([Paragraph(escape(str(row.theme)),styles["Small"]),Paragraph(escape(str(row.recommended_intervention)),styles["Small"]),Paragraph(escape(f"{row.suggested_owner}; {row.effort_estimate}"),styles["Small"])])
        story.append(Table(recs,colWidths=[110,245,115],style=TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17324D")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#C9D4DF")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F1F5F8")]),("VALIGN",(0,0),(-1,-1),"TOP"),("PADDING",(0,0),(-1,-1),4)])))
    story += [Spacer(1,7),Paragraph("Recommended next steps",styles["Heading1"]),Paragraph("Immediate: manually review the highest-frequency matched excerpts and verify booking or trip records. Near term: choose an issue-specific engineering change only after confirming it in internal telemetry. Track relevant journey outcomes (for example booking completion or pickup ETA error) alongside operational diagnostics. Evaluate with a staged rollout and holdout or comparable pre/post window; do not infer a rating lift from these samples.",styles["BodyText"]),Paragraph("Representative excerpts",styles["Heading1"]),Paragraph("Shortened broad-sample 1-2 star excerpts; basic email and phone patterns redacted. Review text is not a verified root cause.",styles["Small"])]
    review_path=PROC/"classified_reviews.csv"
    if review_path.exists():
        ex=pd.read_csv(review_path); ex=ex[ex.sample_strategy.eq("broad_recent") & ex.rating.le(2)].dropna(subset=["review_text"]).head(5)
        for row in ex.itertuples():
            excerpt=re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}","[email redacted]",str(row.review_text)); excerpt=re.sub(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)","[phone redacted]",excerpt)
            story.append(Paragraph(escape(f"{int(row.rating)} star: {excerpt[:220]}"),styles["Small"]))
    story += [Spacer(1,7),Paragraph("Classification and limitations",styles["Heading1"]),Paragraph("Themes use transparent multi-label keyword rules. No manually labeled validation set was available; precision, recall and F1 are not reported. Google Play reviews are self-selected, the broad sample is recent and bounded, and low-rating samples are targeted. Public text cannot confirm internal root causes. No internal MoveInSync telemetry or architecture was available.",styles["BodyText"]),Paragraph("Monitoring",styles["Heading1"]),Paragraph("Retain timestamped raw snapshots and rerun the pipeline periodically. Compare like-for-like broad samples by country, language and window. The 100-review per-window threshold is a conservative screening rule, not proof of statistical significance; investigate uncertainty before acting.",styles["BodyText"])]
    SimpleDocTemplate(str(OUT/"reports"/"candidate_report.pdf"),pagesize=letter,rightMargin=54,leftMargin=54,topMargin=48,bottomMargin=48).build(story)
    prs=Presentation()
    slides=[("MoveInSync - FDE case study","Why do employee app reviews turn negative? Public review evidence and an action plan"),("Executive summary",f"Broad recent sample: n={broad.get('n','pending')}\nSample mean: {broad.get('rating_mean','pending')} / 5\nInterpretation is bounded to this sample."),("Source and method","Official Google Play listing\nBounded recent sample + targeted 1-2 star discovery sample\nSamples analyzed separately; targeted results do not estimate prevalence"),("Coverage and quality",f"Valid sample memberships: {q.get('valid_rows_including_cross_strategy_membership','pending')}\nUnique review IDs: {q.get('unique_review_ids','pending')}\nDate range: {q.get('date_min','pending')} to {q.get('date_max','pending')}\nSnapshot, not complete store history"),("Rating patterns",f"Broad sample n={broad.get('n','pending')}\nMean {broad.get('rating_mean','pending')} / 5; median {broad.get('rating_median','pending')}\nDistribution: {broad.get('rating_distribution','pending')}"),("Complaint themes",top_text+"\nKeyword classification is exploratory and unvalidated."),("Prioritized fixes",fix_text+"\nConfirm each issue with internal telemetry; effort is an initial estimate."),("Implementation roadmap","Immediate: manually review evidence and instrument the implicated journey\nNear term: fix validated failure modes\nLong term: evaluate changes with holdout/staged rollout"),("Success metrics and monitoring","Choose outcome + operational diagnostics relevant to each validated issue\nCompare like-for-like windows (at least 100 reviews per window for screening)\nNo rating lift forecast"),("Limitations and conclusion","Self-selection bias; review text cannot confirm internal causes. No manually labeled validation set or internal telemetry was available.")]
    for title,body in slides:
        s=prs.slides.add_slide(prs.slide_layouts[1]); s.shapes.title.text=title; s.placeholders[1].text=body
        if title=="Rating patterns" and broad.get("rating_distribution"):
            chart_data=CategoryChartData(); chart_data.categories=list(broad["rating_distribution"].keys()); chart_data.add_series("Broad recent reviews",list(broad["rating_distribution"].values()))
            s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,Inches(6.0),Inches(1.7),Inches(6.1),Inches(4.5),chart_data)
    prs.save(OUT/"presentations"/"candidate_deck.pptx")

if __name__=="__main__": generate()
