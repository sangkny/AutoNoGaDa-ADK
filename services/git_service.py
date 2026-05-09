"""Git 자동 커밋 유틸 (Week 5 5-1-1).

컨테이너에서는 `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`(및 선택적 커미터 변수) 로
무인 커밋 작성자 정보를 줄 수 있습니다 (`git cli` 규격).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import Settings, get_settings

log = logging.getLogger("services.git_service")


class GitOperationError(Exception):
    """git 명령 실패 또는 저장소 무결성 오류"""


@dataclass
class GitCommitResult:
    ok:                    bool
    commit_sha:            str | None
    stderr:                str                             = ""
    files_committed:       list[str]                     = field(default_factory=list)
    skipped_no_changes:    bool                           = False


@dataclass
class GitPushResult:
    ok:     bool
    stderr: str = ""


@dataclass
class GitBranchResult:
    ok:     bool
    branch: str
    stderr: str = ""


def _sanitize_task_id_fragment(task_id: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", task_id.strip())[:32]
    return cleaned or "snippet"


class GitService:
    """
    저장소 로컬 git 작업 (add / commit / branch / push).
    모든 경로는 `repo_path` 아래 상대경로 문자열 또는 Path 로 전달합니다.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()

    def _repo_root(self, repo_path: str | Path) -> Path:
        root = Path(repo_path).expanduser().resolve()
        if not (root / ".git").exists():
            raise GitOperationError(f"git 저장소 아님: {root}")
        return root

    def _git_env(self) -> dict[str, str]:
        env                 = dict(os.environ)
        name                = self._s.git_author_name.strip()
        email               = self._s.git_author_email.strip()
        env["GIT_AUTHOR_NAME"]     = name
        env["GIT_AUTHOR_EMAIL"]    = email
        env["GIT_COMMITTER_NAME"]  = self._s.git_committer_name.strip() or name
        env["GIT_COMMITTER_EMAIL"] = self._s.git_committer_email.strip() or email
        return env

    async def _run_git(
        self,
        cwd: Path,
        *args: str,
    ) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            env=self._git_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await proc.communicate()
        return proc.returncode, out_b.decode(errors="replace"), err_b.decode(errors="replace")

    def snippet_file_path(self, repo_path: str | Path, task_id: str, language: str) -> tuple[Path, str]:
        """생성물 파일 절대 경로 및 repo 상대 POSIX 경로 문자열 반환."""
        root = self._repo_root(repo_path)
        slug = _sanitize_task_id_fragment(task_id)
        ext = (language or "python").lower().split(".")[-1]
        if ext not in ("py", "ts", "js", "tsx", "jsx", "md", "json"):
            ext = "py"
        rel = Path(self._s.git_generated_prefix) / f"autonogada_{slug}.{ext}"
        abs_path = root / rel
        return abs_path, rel.as_posix()

    async def write_generated_snippet(
        self,
        repo_path: str | Path,
        task_id: str,
        code: str,
        language: str,
    ) -> str:
        abs_path, rel = self.snippet_file_path(repo_path, task_id, language)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(code, encoding="utf-8")
        log.info("snippet 저장 repo=%s path=%s", repo_path, rel)
        return rel

    async def commit(
        self,
        repo_path: str | Path,
        message: str,
        files: list[str],
    ) -> GitCommitResult:
        root = self._repo_root(repo_path)
        msg  = message.strip() or "chore: autonogada codegen"
        for f in files:
            code, _, err = await self._run_git(root, "add", "--", f)
            if code != 0:
                raise GitOperationError(f"git add 실패 [{f}]: {err}")

        code, stdout, stderr = await self._run_git(
            root, "diff", "--cached", "--quiet",
        )
        if code == 0:
            return GitCommitResult(
                ok=True,
                commit_sha=None,
                stderr=stderr,
                files_committed=[],
                skipped_no_changes=True,
            )

        code, out_rev, stderr = await self._run_git(
            root, "commit", "-m", msg,
        )
        if code != 0:
            if "nothing to commit" in (stderr.lower() + out_rev.lower()):
                return GitCommitResult(
                    ok=True,
                    commit_sha=None,
                    stderr=stderr,
                    files_committed=[],
                    skipped_no_changes=True,
                )
            raise GitOperationError(f"git commit 실패: {stderr or out_rev}")

        code, sha_raw, stderr2 = await self._run_git(root, "rev-parse", "HEAD")
        sha = sha_raw.strip() if code == 0 else None
        if stderr2:
            stderr = f"{stderr}\n{stderr2}".strip()

        log.info("git commit ok sha=%s files=%s", sha, files)
        return GitCommitResult(ok=True, commit_sha=sha, stderr=stderr, files_committed=list(files))

    async def push(self, repo_path: str | Path, remote: str | None = None) -> GitPushResult:
        root       = self._repo_root(repo_path)
        upstream   = remote or self._s.git_default_remote
        code, _, err = await self._run_git(root, "push", upstream, "HEAD")
        ok = code == 0
        return GitPushResult(ok=ok, stderr=err)

    async def create_branch(self, repo_path: str | Path, branch_name: str) -> GitBranchResult:
        root = self._repo_root(repo_path)
        bn   = branch_name.strip().replace("/", "-")
        if not bn:
            return GitBranchResult(ok=False, branch=bn, stderr="branch_name 비어 있음")

        code, stdout, stderr = await self._run_git(root, "switch", "-c", bn)
        if code != 0:
            code2, stdout2, stderr2 = await self._run_git(root, "checkout", "-b", bn)
            merged_err = (stderr + stderr2).strip()
            if code2 != 0:
                return GitBranchResult(ok=False, branch=bn, stderr=merged_err or stdout2)
            return GitBranchResult(ok=True, branch=bn, stderr=merged_err)
        tail = stderr or stdout.strip()[:200]
        return GitBranchResult(ok=True, branch=bn, stderr=tail)

    @staticmethod
    def create_pr_description(changes: list[dict[str, Any]]) -> str:
        """간단한 PR 본문(Markdown) — changes: 각 dict 에 path 필수, status·summary 선택."""
        if not changes:
            return "## Auto-generated PR\n\n(변경 항목 없음)\n"

        lines = ["## AutoNoGaDa — codegen PR", "", "### 변경 파일", ""]
        for c in changes:
            path = c.get("path", "?")
            st   = c.get("status", "")
            hint = c.get("summary", "")
            row  = f"- `{path}`"
            if st:
                row += f" ({st})"
            if hint:
                row += f" — {hint}"
            lines.append(row)
        lines.extend(
            ["", "---", "`GitService.create_pr_description` 자동 생성"],
        )
        return "\n".join(lines)


def commit_result_as_dict(result: GitCommitResult) -> dict[str, Any]:
    committed = (
        result.ok and not result.skipped_no_changes and bool(result.commit_sha)
    )
    return {
        "committed":           committed,
        "skipped_no_changes": result.skipped_no_changes,
        "commit_sha":          result.commit_sha,
        "files":               result.files_committed,
        "stderr_tail":        (result.stderr or "")[-600:],
    }
