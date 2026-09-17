from datetime import date

from procurement_agent.agents.dates import is_iso_date, parse_relative_date

# 2026-09-17 是星期四
TODAY = date(2026, 9, 17)


def test_iso_passthrough():
    assert parse_relative_date("2026-09-21", TODAY) == "2026-09-21"
    assert is_iso_date("2026-09-21") is True
    assert is_iso_date("下周一") is False


def test_today_tomorrow_day_after():
    assert parse_relative_date("今天到货", TODAY) == "2026-09-17"
    assert parse_relative_date("明天", TODAY) == "2026-09-18"
    assert parse_relative_date("后天", TODAY) == "2026-09-19"


def test_next_week_weekday():
    # 2026-09-17 是周四，下周一为 09-21
    assert parse_relative_date("下周一前到货", TODAY) == "2026-09-21"
    assert parse_relative_date("下周五", TODAY) == "2026-09-25"


def test_this_week_weekday():
    assert parse_relative_date("本周五", TODAY) == "2026-09-18"
    assert parse_relative_date("这周三", TODAY) == "2026-09-16"


def test_bare_weekday_already_passed_means_next_week():
    # 周四说的"周一"应指下周一
    assert parse_relative_date("周一送到", TODAY) == "2026-09-21"


def test_month_day_future_and_rollover():
    assert parse_relative_date("10月1日到货", TODAY) == "2026-10-01"
    assert parse_relative_date("1月5日到货", TODAY) == "2027-01-05"


def test_unparseable_returns_none():
    assert parse_relative_date("尽快", TODAY) is None
    assert parse_relative_date("", TODAY) is None
    assert parse_relative_date(None, TODAY) is None

