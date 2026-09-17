from pathlib import Path

import pytest

from procurement_agent.vfs import PathEscapeError, VirtualFileSystem


def make_vfs(tmp_path: Path) -> VirtualFileSystem:
    workspace = tmp_path / "workspace"
    readonly = tmp_path / "readonly"
    readonly.mkdir(parents=True, exist_ok=True)
    (readonly / "data.txt").write_text("hello", encoding="utf-8")
    return VirtualFileSystem(workspace=workspace, readonly_aliases={"readonly": readonly})


def test_write_inside_workspace(tmp_path):
    vfs = make_vfs(tmp_path)
    vfs.write_text("notes/a.txt", "content")
    target = tmp_path / "workspace" / "notes" / "a.txt"
    assert target.read_text(encoding="utf-8") == "content"


def test_read_back_what_was_written(tmp_path):
    vfs = make_vfs(tmp_path)
    vfs.write_text("a.txt", "内容")
    assert vfs.read_text("a.txt") == "内容"


def test_dotdot_escape_rejected(tmp_path):
    vfs = make_vfs(tmp_path)
    with pytest.raises(PathEscapeError) as exc:
        vfs.write_text("../outside.txt", "bad")
    assert exc.value.original == "../outside.txt"


def test_nested_dotdot_escape_rejected(tmp_path):
    vfs = make_vfs(tmp_path)
    with pytest.raises(PathEscapeError):
        vfs.read_text("a/../../etc/passwd")


def test_absolute_path_rejected(tmp_path):
    vfs = make_vfs(tmp_path)
    with pytest.raises(PathEscapeError):
        vfs.write_text(str(tmp_path / "workspace" / "abs.txt"), "bad")


def test_readonly_write_rejected(tmp_path):
    vfs = make_vfs(tmp_path)
    with pytest.raises(PathEscapeError) as exc:
        vfs.write_text("readonly/data.txt", "bad")
    assert "只读" in exc.value.reason
    assert (tmp_path / "readonly" / "data.txt").read_text(encoding="utf-8") == "hello"


def test_readonly_read_allowed(tmp_path):
    vfs = make_vfs(tmp_path)
    assert vfs.read_text("readonly/data.txt") == "hello"


def test_list_dir_stays_inside_workspace(tmp_path):
    vfs = make_vfs(tmp_path)
    vfs.write_text("a.txt", "1")
    vfs.write_text("b.txt", "2")
    assert vfs.list_dir(".") == ["a.txt", "b.txt"]


def test_unknown_alias_is_treated_as_workspace_path(tmp_path):
    vfs = make_vfs(tmp_path)
    vfs.write_text("other/x.txt", "ok")
    assert (tmp_path / "workspace" / "other" / "x.txt").exists()

