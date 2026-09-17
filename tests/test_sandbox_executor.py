import sys

import pytest

from procurement_agent.sandbox.executor import (
    DEFAULT_ENV_ALLOWLIST,
    TRUNCATED_MARK,
    SandboxExecutor,
)
from procurement_agent.vfs import PathEscapeError, VirtualFileSystem


def make_executor(tmp_path, **kwargs) -> SandboxExecutor:
    workspace = tmp_path / "workspace"
    vfs = VirtualFileSystem(workspace=workspace, readonly_aliases={})
    return SandboxExecutor(workspace=workspace, vfs=vfs, **kwargs)


def test_allowed_command_runs(tmp_path):
    executor = make_executor(tmp_path)
    result = executor.run([sys.executable, "-c", "print('ok')"])
    assert result.ok is True
    assert "ok" in result.stdout
    assert result.denied_reason is None


@pytest.mark.parametrize("command", ["rm", "del", "curl", "wget", "shutdown", "powershell"])
def test_dangerous_commands_denied(tmp_path, command):
    executor = make_executor(tmp_path)
    result = executor.run([command, "-rf", "/"])
    assert result.ok is False
    assert result.denied_reason
    assert command in result.denied_reason


def test_empty_command_denied(tmp_path):
    executor = make_executor(tmp_path)
    result = executor.run([])
    assert result.ok is False
    assert result.denied_reason == "空命令"


def test_timeout_is_reported(tmp_path):
    executor = make_executor(tmp_path, timeout_seconds=0.5)
    result = executor.run([sys.executable, "-c", "import time; time.sleep(10)"])
    assert result.ok is False
    assert result.denied_reason == "执行超时"


def test_large_output_is_truncated(tmp_path):
    executor = make_executor(tmp_path, max_output_bytes=100)
    result = executor.run([sys.executable, "-c", "print('x' * 2000)"])
    assert result.stdout.endswith(TRUNCATED_MARK)
    assert len(result.stdout.encode("utf-8")) <= 200


def test_child_env_only_contains_allowlist(tmp_path):
    executor = make_executor(tmp_path)
    script = "import os; print(sorted(os.environ.keys()))"
    result = executor.run([sys.executable, "-c", script])
    assert result.ok is True
    allowed = set(DEFAULT_ENV_ALLOWLIST)
    reported = eval(result.stdout.strip())  # noqa: S307 - 子进程输出由测试自行构造
    assert set(reported) <= allowed


def test_cwd_escape_raises(tmp_path):
    executor = make_executor(tmp_path)
    with pytest.raises(PathEscapeError):
        executor.run([sys.executable, "-c", "print(1)"], cwd="../../")


def test_missing_command_reported(tmp_path):
    executor = make_executor(tmp_path)
    result = executor.run(["definitely-not-a-real-binary-xyz"])
    assert result.ok is False
    assert result.denied_reason

