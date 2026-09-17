from __future__ import annotations

from pathlib import Path
from typing import Literal


class PathEscapeError(Exception):
    def __init__(self, original: str, resolved: str, reason: str) -> None:
        super().__init__(f"路径越界：输入 {original!r}，解析为 {resolved!r}（{reason}）")
        self.original = original
        self.resolved = resolved
        self.reason = reason


class VirtualFileSystem:
    """虚拟文件系统：所有读写先经过路径归一化与挂载点校验。

    挂载结构：
    - 工作区（可读写）挂在根路径下，例如 ``notes/a.txt``
    - 只读别名目录挂在别名前缀下，例如 ``readonly/data.txt``
    """

    def __init__(
        self,
        workspace: Path | str,
        readonly_aliases: dict[str, Path | str] | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.readonly_aliases = {
            alias: Path(root).resolve()
            for alias, root in (readonly_aliases or {}).items()
        }

    def _reject(self, original: str, resolved: Path, reason: str):
        raise PathEscapeError(original, str(resolved), reason)

    def resolve(self, path: str, mode: Literal["read", "write"] = "read") -> Path:
        raw = str(path)
        if raw in ("", ".", "./"):
            return self.workspace
        candidate = Path(raw)
        if candidate.is_absolute():
            self._reject(raw, candidate, "禁止绝对路径")

        parts = [part for part in candidate.parts if part not in ("", ".")]
        if not parts or any(part == ".." for part in parts):
            self._reject(raw, candidate, "禁止路径穿越")

        alias = parts[0]
        if alias in self.readonly_aliases:
            root = self.readonly_aliases[alias]
            target = (root / Path(*parts[1:])).resolve()
            if not target.is_relative_to(root):
                self._reject(raw, target, "越出只读挂载点")
            if mode == "write":
                self._reject(raw, target, "只读目录不允许写入")
            return target

        target = (self.workspace / Path(*parts)).resolve()
        if not target.is_relative_to(self.workspace):
            self._reject(raw, target, "越出工作区")
        return target

    def read_text(self, path: str) -> str:
        return self.resolve(path, mode="read").read_text(encoding="utf-8")

    def write_text(self, path: str, content: str) -> None:
        target = self.resolve(path, mode="write")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def list_dir(self, path: str = ".") -> list[str]:
        target = self.resolve(path, mode="read") if path != "." else self.workspace
        if not target.exists():
            return []
        return sorted(item.name for item in target.iterdir())
