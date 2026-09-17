from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_SKILLS_ROOT = Path("skills")
FRONTMATTER_KEYS = ("name", "description")


class SkillNotFound(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"技能不存在: {name}")
        self.name = name


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    path: Path


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()
    return result


def _read_head(path: Path, max_lines: int = 20) -> str:
    with path.open("r", encoding="utf-8") as handle:
        lines: list[str] = []
        for index, line in enumerate(handle):
            if index >= max_lines:
                break
            lines.append(line)
    return "".join(lines)


class SkillRegistry:
    """技能注册表：只暴露名称与描述，正文按需加载（渐进式加载）。"""

    def __init__(self, skills_root: Path | str = DEFAULT_SKILLS_ROOT) -> None:
        self.skills_root = Path(skills_root)
        self._loaded: set[str] = set()
        self._index: dict[str, SkillMeta] = {}
        self._refresh()

    def _refresh(self) -> None:
        index: dict[str, SkillMeta] = {}
        if self.skills_root.exists():
            for skill_file in sorted(self.skills_root.glob("*/SKILL.md")):
                front = _parse_frontmatter(_read_head(skill_file))
                name = front.get("name") or skill_file.parent.name
                index[name] = SkillMeta(
                    name=name,
                    description=front.get("description", ""),
                    path=skill_file,
                )
        self._index = index

    def list_metadata(self) -> list[SkillMeta]:
        return [self._index[name] for name in sorted(self._index)]

    def load(self, name: str) -> str:
        meta = self._index.get(name)
        if meta is None:
            raise SkillNotFound(name)
        body = meta.path.read_text(encoding="utf-8")
        self._loaded.add(name)
        return body

    @property
    def loaded_names(self) -> set[str]:
        return set(self._loaded)

    def metadata_only_names(self) -> set[str]:
        return set(self._index) - self._loaded

    def reset(self) -> None:
        self._loaded.clear()

    def render_index(self) -> str:
        """渲染进系统提示的技能索引（只有名称与描述）。"""
        lines = ["可用技能（需要时再加载正文）："]
        for meta in self.list_metadata():
            lines.append(f"- {meta.name}: {meta.description}")
        return "\n".join(lines)

