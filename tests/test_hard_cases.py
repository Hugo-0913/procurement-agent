from pathlib import Path

import pytest

from procurement_agent.eval.runner import load_cases, run_eval

HARD_CASES = Path("src/procurement_agent/eval/cases_hard.yaml")


@pytest.fixture(scope="module")
def hard_report(tmp_path_factory):
    cases = load_cases(HARD_CASES)
    return cases, run_eval(cases, tmp_path_factory.mktemp("hard_runs"))


def test_hard_case_set_loads(hard_report):
    cases, _ = hard_report
    assert len(cases) == 10
    assert len({case.id for case in cases}) == 10


def test_vague_and_unknown_material_ask_for_clarification(hard_report):
    """模糊需求与未知物料必须停在解析阶段提问，而不是猜测后继续下单。"""
    _, report = hard_report
    failed = {item["case_id"] for item in report.failures}
    assert "H-01" not in failed, "模糊需求未被正确识别为需要澄清"
    assert "H-02" not in failed, "未知物料未被正确识别为需要澄清"


def test_alias_material_names_resolve(hard_report):
    """带别称与空格混用的物料名应能匹配到主数据。"""
    _, report = hard_report
    failed = {item["case_id"] for item in report.failures}
    assert "H-03" not in failed
    assert "H-04" not in failed


def test_large_and_urgent_orders_require_approval(hard_report):
    _, report = hard_report
    failed = {item["case_id"] for item in report.failures}
    assert "H-05" not in failed, "超大额订单未触发审批"
    assert "H-06" not in failed, "紧急大额订单未触发审批"


def test_hard_report_records_all_delegation_modes(hard_report):
    _, report = hard_report
    assert report.delegation_framework + report.delegation_fallback > 0


def test_single_viable_supplier_escalates_instead_of_failing(hard_report):
    """只剩一家可用供应商时，应按配置转人工审批，而不是让任务直接失败。"""
    _, report = hard_report
    failed = {item["case_id"] for item in report.failures}
    assert "H-10" not in failed, "唯一可用报价场景未按审批策略处理"
    assert report.intervention_count >= 2
