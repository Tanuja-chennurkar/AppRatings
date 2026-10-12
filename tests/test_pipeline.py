import pandas as pd
from src.pipeline import classify, validate
from src.monitor import compare_windows

def test_classifier_evidence_and_multilabel():
    result=classify("Driver was late and GPS tracking failed")
    assert "Pickup timing and ETA" in result["themes"]
    assert "Live tracking and GPS" in result["themes"]
    assert result["evidence_span"] in "Driver was late and GPS tracking failed".lower()

def test_validation_excludes_bad_records_and_retains_text_duplicates(tmp_path):
    df=pd.DataFrame([{"review_id":"1","review_text":"late cab","rating":1,"review_date":"2026-01-01","sample_strategy":"broad_recent"},{"review_id":"2","review_text":"late cab","rating":2,"review_date":"2026-01-02","sample_strategy":"targeted_1_2_star"},{"review_id":"3","review_text":"","rating":5,"review_date":"bad"}])
    clean,report=validate(df,tmp_path)
    assert len(clean)==2 and report["excluded_rows"]==1
    assert report["duplicate_text_rows_diagnostic"]==2

def test_same_review_can_remain_in_distinct_sample_strategies(tmp_path):
    df=pd.DataFrame([{"review_id":"same","review_text":"late cab","rating":1,"review_date":"2026-01-01","sample_strategy":"broad_recent"},{"review_id":"same","review_text":"late cab","rating":1,"review_date":"2026-01-01","sample_strategy":"targeted_1_2_star"}])
    clean,report=validate(df,tmp_path)
    assert len(clean)==2
    assert report["review_ids_in_multiple_strategies"]==1

def test_monitor_suppresses_tiny_windows():
    data=pd.DataFrame([{"review_id":"a","review_date":"2026-01-02","sample_strategy":"broad_recent","themes":"Pickup timing and ETA"}])
    result=compare_windows(data,"2026-01-01","2026-01-03","2026-01-04","2026-01-06")
    assert set(result.status)=={"insufficient_sample"}

