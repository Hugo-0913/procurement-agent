"""把中文相对日期表达式换算成 ISO 日期。

模型经常直接返回"下周一"这类字面量，而不是技能文件要求的 ISO 日期。与其反复加强提示词，
不如用确定性代码兜底——这与 ADR-002 的原则一致：可计算的规则不交给模型。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

WEEKDAY_INDEX = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
ISO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WEEK_PATTERN = re.compile(r"(下{1,}|本|这)?(?:周|星期)([一二三四五六日天])")
MONTH_DAY_PATTERN = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")


def is_iso_date(text: str | None) -> bool:
    if not text or not ISO_PATTERN.match(str(text).strip()):
        return False
    try:
        date.fromisoformat(str(text).strip())
    except ValueError:
        return False
    return True


def parse_relative_date(text: str | None, today: date | None = None) -> str | None:
    """从文本中解析相对日期，返回 ISO 字符串；无法识别时返回 None。"""
    if not text:
        return None
    raw = str(text)
    if is_iso_date(raw):
        return raw.strip()

    base = today or date.today()
    if "今天" in raw or "今日" in raw:
        return base.isoformat()
    if "明天" in raw or "明日" in raw:
        return (base + timedelta(days=1)).isoformat()
    if "后天" in raw:
        return (base + timedelta(days=2)).isoformat()

    week_match = WEEK_PATTERN.search(raw)
    if week_match:
        prefix = week_match.group(1) or ""
        target_index = WEEKDAY_INDEX[week_match.group(2)]
        # 以周一为一周起点计算偏移
        current_index = base.weekday()
        delta = target_index - current_index
        if prefix.startswith("下"):
            delta += 7 * len(prefix)
        elif delta < 0 and "本" not in prefix and "这" not in prefix:
            # 未指明周次且该日期已过，视为下周
            delta += 7
        return (base + timedelta(days=delta)).isoformat()

    month_day = MONTH_DAY_PATTERN.search(raw)
    if month_day:
        month, day = int(month_day.group(1)), int(month_day.group(2))
        candidate = date(base.year, month, day)
        if candidate < base:
            candidate = date(base.year + 1, month, day)
        return candidate.isoformat()
    return None

