from pathlib import Path

import pytest
import yaml

from procurement_agent.eval.runner import (
    EvalCase,
    load_cases,
    measure_context_reduction,
    run_eval,
)


def test_load_cases_returns_30_unique(tmp_path):
    cases = load_cases()
    assert len(cases) == 30
    assert len({case.id for case in cases}) == 30
    assert all(isinstance(case, EvalCase) for case in cases)
    assert sum(1 for case in cases if case.expect_approval) == 8


def test_duplicate_ids_rejected(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: A\n  request_text: x\n- id: A\n  request_text: y\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="重复"):
        load_cases(path)


def small_cases(path: Path) -> list[EvalCase]:
    data = [
        {
            "id": "S-1",
            "request_text": "采购 50 箱 A4 纸",
            "quantity": 50,
            "faults": {},
            "expect_state": "COMPLETED",
            "expect_approval": False,
        },
        {
            "id": "S-2",
            "request_text": "采购 3000 箱 A4 纸",
            "quantity": 3000,
            "faults": {"all_quotes_over_budget": True},
            "expect_state": "AWAITING_APPROVAL",
            "expect_approval": True,
        },
        {
            "id": "S-3",
            "request_text": "采购 50 箱 A4 纸（B 资质异常）",
            "quantity": 50,
            "faults": {"supplier_b_expired": True},
            "expect_state": "COMPLETED",
            "expect_approval": False,
        },
    ]
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return load_cases(path)


def test_run_eval_produces_valid_report(tmp_path):
    cases = small_cases(tmp_path / "small.yaml")
    report = run_eval(cases, tmp_path / "runs")
    assert report.status == "finished"
    assert report.total == 3
    assert 0.0 <= report.success_rate <= 1.0
    assert 0.0 <= report.intervention_rate <= 1.0
    assert report.token_peak >= 0
    assert report.success_count >= 1


def test_run_eval_is_reproducible(tmp_path):
    cases = small_cases(tmp_path / "small.yaml")
    first = run_eval(cases, tmp_path / "runs-a")
    second = run_eval(cases, tmp_path / "runs-b")
    assert first.success_rate == second.success_rate
    assert first.token_peak == second.token_peak
    assert first.intervention_rate == second.intervention_rate


def test_failures_carry_task_ids(tmp_path):
    data = [
        {
            "id": "X-1",
            "request_text": "采购 50 箱 A4 纸",
            "quantity": 50,
            "faults": {},
            "expect_state": "FAILED",
            "expect_approval": False,
        }
    ]
    path = tmp_path / "cases.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    report = run_eval(load_cases(path), tmp_path / "runs")
    assert report.failures
    assert report.failures[0]["task_id"].startswith("t-")
    assert report.failures[0]["case_id"] == "X-1"


def test_context_reduction_is_measured_and_reproducible():
    before, after, reduction = measure_context_reduction()
    assert before > after
    assert 0 < reduction < 1
    assert measure_context_reduction() == (before, after, reduction)


def test_report_includes_context_metrics(tmp_path):
    cases = small_cases(tmp_path / "small.yaml")
    report = run_eval(cases, tmp_path / "runs")
    assert report.context_before_tokens > 0
    assert report.context_after_tokens > 0
    assert report.context_reduction_rate > 0


def test_report_counts_delegation_modes(tmp_path):
    """报告必须区分框架委派与降级，不能把降级算成委派成功。"""
    cases = small_cases(tmp_path / "small.yaml")
    report = run_eval(cases, tmp_path / "runs")
    # 三条用例各三次委派，离线模型始终发出 task 工具调用
    assert report.delegation_framework == 9
    assert report.delegation_fallback == 0


def test_offline_mode_records_no_fake_token_totals(tmp_path):
    """离线模型没有真实用量，token 总量必须为 0，不能拿估算值冒充。"""
    cases = small_cases(tmp_path / "small.yaml")
    report = run_eval(cases, tmp_path / "runs")
    assert report.token_total_mean == 0
    assert report.token_total_max == 0
