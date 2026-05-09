"""GitService 단위 테스트 (무인 커밋 Week 5 5-1-1)."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from config import Settings
from services.git_service import GitOperationError, GitService, commit_result_as_dict


def _git_init(repo: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture
def svc() -> GitService:
    return GitService(
        Settings(
            git_author_name="Harness Tester",
            git_author_email="harness@test.local",
        ),
    )


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git_init(r)
    return r


@pytest.mark.asyncio
async def test_commit_basic(svc: GitService, empty_repo: Path) -> None:
    (empty_repo / "readme.txt").write_text("hello", encoding="utf-8")
    res = await svc.commit(empty_repo, "feat: hello", ["readme.txt"])
    assert res.ok and res.commit_sha
    assert not res.skipped_no_changes
    body = commit_result_as_dict(res)
    assert body["committed"]


@pytest.mark.asyncio
async def test_skip_when_no_changes(svc: GitService, empty_repo: Path) -> None:
    (empty_repo / "readme.txt").write_text("same", encoding="utf-8")
    await svc.commit(empty_repo, "feat: same", ["readme.txt"])
    res = await svc.commit(empty_repo, "feat: noop", ["readme.txt"])
    assert res.skipped_no_changes


@pytest.mark.asyncio
async def test_write_generated_snippet_relative(svc: GitService, empty_repo: Path) -> None:
    relative = await svc.write_generated_snippet(empty_repo, "tid-111", "# code", "python")
    assert relative.startswith("generated/snippets/")
    assert relative.endswith(".py")


@pytest.mark.asyncio
async def test_create_branch(svc: GitService, empty_repo: Path) -> None:
    (empty_repo / "README.md").write_text("# x", encoding="utf-8")
    await asyncio.wait_for(svc.commit(empty_repo, "init", ["README.md"]), timeout=60)
    br = await asyncio.wait_for(svc.create_branch(empty_repo, "feat/autogen-1"), timeout=60)
    assert br.ok
    out = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=empty_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip() == "feat-autogen-1"


@pytest.mark.asyncio
async def test_push_without_remote_returns_fail(svc: GitService, empty_repo: Path) -> None:
    pushed = await svc.push(empty_repo)
    assert pushed.ok is False


@pytest.mark.asyncio
async def test_git_add_invalid_path_raises(svc: GitService, empty_repo: Path) -> None:
    with pytest.raises(GitOperationError):
        await svc.commit(empty_repo, "x", ["nope.notexists"])


def test_create_pr_description_lists_paths() -> None:
    md = GitService.create_pr_description(
        [{"path": "a.py", "status": "modified", "summary": "타입 보강"}],
    )
    assert "a.py" in md
    assert "### 변경 파일" in md

