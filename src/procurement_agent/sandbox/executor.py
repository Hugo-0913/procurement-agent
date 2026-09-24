from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from procurement_agent.vfs import VirtualFileSystem

DANGEROUS_COMMANDS = frozenset(
    {
        "rm",
        "rmdir",
        "del",
        "erase",
        "format",
        "mkfs",
        "curl",
        "wget",
        "nc",
        "powershell",
        "pwsh",
        "cmd",
        "shutdown",
        "reg",
        "regedit",
        "sc",
        "netsh",
        "schtasks",
    }
)

# Windows 下子进程需要 SYSTEMROOT/PATHEXT 才能启动解释器，因此列入白名单。
DEFAULT_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "PATHEXT", "TEMP", "TMP", "COMSPEC")

TRUNCATED_MARK = "...[truncated]"


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    denied_reason: str | None = None


class SandboxExecutor:
    """沙箱层二：受限子进程执行。"""

    def __init__(
        self,
        workspace: Path | str,
        vfs: VirtualFileSystem,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
        env_allowlist: tuple[str, ...] = DEFAULT_ENV_ALLOWLIST,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.vfs = vfs
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.env_allowlist = env_allowlist

    def _check_command(self, argv: list[str]) -> str | None:
        if not argv:
            return "空命令"
        name = os.path.basename(str(argv[0])).lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name in DANGEROUS_COMMANDS:
            return f"命令 {name} 在禁止清单中"
        return None

    def _env(self) -> dict[str, str]:
        return {key: os.environ[key] for key in self.env_allowlist if key in os.environ}

    def _truncate(self, text: str) -> str:
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) <= self.max_output_bytes:
            return text
        return encoded[: self.max_output_bytes].decode("utf-8", errors="ignore") + TRUNCATED_MARK

    def run(self, argv: list[str], cwd: str = ".") -> ExecutionResult:
        denial = self._check_command(argv)
        if denial is not None:
            return ExecutionResult(ok=False, denied_reason=denial)

        working_dir = self.vfs.resolve(cwd, mode="write")
        try:
            completed = subprocess.run(  # noqa: S603
                [str(item) for item in argv],
                cwd=str(working_dir),
                env=self._env(),
                timeout=self.timeout_seconds,
                capture_output=True,
                text=True,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(ok=False, denied_reason="执行超时")
        except FileNotFoundError as exc:
            return ExecutionResult(ok=False, denied_reason=f"命令不存在: {exc}")

        return ExecutionResult(
            ok=completed.returncode == 0,
            stdout=self._truncate(completed.stdout or ""),
            stderr=self._truncate(completed.stderr or ""),
            exit_code=completed.returncode,
        )
