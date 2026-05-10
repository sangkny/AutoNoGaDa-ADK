"""폴리glot 코드 생성·검증 — Python / TypeScript / Rust (Phase 2 W4)."""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass

import httpx

from llm.base import ModelRole
from llm.client import LLMClient
from ontology.validator import OntologyValidator

log = logging.getLogger("services.polyglot_executor")


SUPPORTED_LANGUAGES = frozenset({"python", "typescript", "rust"})


@dataclass
class SyntaxValidationOutcome:
    valid: bool
    syntax_errors: list[str]
    style_warnings: list[str]


POLYGLOT_LANGUAGE_ALIASES: dict[str, str] = {
    "py":       "python",
    "python3": "python",
    "ts":      "typescript",
    "tsx":     "typescript",
    "javascript": "typescript",
    "js":       "typescript",
    "rs":       "rust",
}


def normalize_language(language: str) -> str:
    """pipeline language → polyglot ontology 키."""
    k = (language or "python").lower().strip()
    return POLYGLOT_LANGUAGE_ALIASES.get(k, k)


def extract_fenced_code(raw_output: str, lang: str) -> str:
    """LLM 출력에서 펜스 코드 우선 추출."""
    text = (raw_output or "").strip()
    l = normalize_language(lang)
    langs: list[str]
    if l == "typescript":
        langs = ["typescript", "ts"]
    elif l == "rust":
        langs = ["rust", "rs"]
    else:
        langs = ["python", "py"]
    for cand in langs:
        m = re.search(
            rf"```(?:{re.escape(cand)})\s*\n([\s\S]*?)```",
            text,
            re.I,
        )
        if m:
            return m.group(1).strip()
    fb = re.search(r"```\s*\n([\s\S]*?)```", text)
    if fb:
        return fb.group(1).strip()
    return text


def infer_function_name(code: str, lang: str) -> str:
    """POLYGLOT Ontology 의 function_name 근삿값."""
    l = normalize_language(lang)
    if l == "typescript":
        m = re.search(
            r"(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9]*)",
            code,
        )
        if m:
            return m.group(1)
        m = re.search(
            r"const\s+([a-z][a-zA-Z0-9]*)\s*=\s*(?:async\s*)?\(",
            code,
        )
        return m.group(1) if m else "snippet"
    if l == "rust":
        m = re.search(r"fn\s+([a-z_][a-z0-9_]*)", code)
        return m.group(1) if m else "snippet"
    m = re.search(r"def\s+([a-z_][a-z0-9_]*)", code)
    return m.group(1) if m else "snippet"


def framework_hint(language: str, framework: str | None) -> str:
    fw = (framework or "").strip().lower()
    if not fw:
        return ""
    l = normalize_language(language)
    hints: dict[str, dict[str, str]] = {
        "typescript": {
            "express": "(Express 라우팅 패턴 허용) ",
            "fastify": "(Fastify 스타일) ",
            "axum":    "(Rust axum 과 유사 타입 패턴 허용) ",
        },
        "rust": {
            "axum":    "(Rust async·tower 흔들림 없는 서명) ",
            "actix":   "(actix-web 관례 존중) ",
            "tokio":   "(Tokio 비동기) ",
        },
        "python": {
            "fastapi": "(FastAPI 관례, 타입 힌트 준수) ",
            "django": "(Django 헬퍼 스타일) ",
            "flask":  "(플라스크 앱 패턴 간접 허용) ",
        },
    }
    bucket = hints.get(l, {})
    return bucket.get(fw, "")


class PolyglotExecutor:
    """외부 sandbox URL + 로컬 Python AST 검증."""

    def __init__(self, sandbox_url: str | None = None, timeout_sec: float = 45.0) -> None:
        self._sandbox_url = (sandbox_url or "").rstrip("/")
        self._timeout = timeout_sec

    def build_system_addon(self, language: str, framework: str | None = None) -> str:
        l = normalize_language(language)
        if l not in SUPPORTED_LANGUAGES:
            return ""
        fw = framework_hint(language, framework)
        if l == "python":
            return (
                f"{fw}Python 3.11, snake_case 함수명, 타입 힌트·docstring. "
                "eval/exec/os.system 금지. 코드만 출력."
            )
        if l == "typescript":
            return (
                f"{fw}TypeScript strict 의미를 따르세요. 함수명 camelCase. "
                "`any` 타입 및 `as any` 금지. 코드만 출력."
            )
        return (
            f"{fw}Rust edition 2021, snake_case. `.unwrap()` 는 3회 이내. "
            "코드만 출력."
        )

    def build_pipeline_user_prompt(self, description: str, language: str) -> str:
        l = normalize_language(language)
        return (
            f"{l} 로 다음 요구를 만족하는 **단일 함수(또는 단일 라이브러리 항목)** 만 작성하세요.\n"
            f"설명: {description}\n"
            "코드만 출력하고 마크다운 설명은 최소화합니다 (펜스로 감싸도 됨)."
        )

    async def validate_syntax(self, code: str, language: str) -> SyntaxValidationOutcome:
        lang = normalize_language(language)
        if lang == "python":
            try:
                ast.parse(code)
            except SyntaxError as e:
                return SyntaxValidationOutcome(
                    valid=False,
                    syntax_errors=[f"{e.msg} (line {e.lineno})"],
                    style_warnings=[],
                )
            return SyntaxValidationOutcome(valid=True, syntax_errors=[], style_warnings=[])

        if not self._sandbox_url:
            return SyntaxValidationOutcome(
                valid=False,
                syntax_errors=[f"sandbox_unreachable: CODE_SANDBOX_URL 미설정 ({lang})"],
                style_warnings=["TypeScript/Rust 검증에는 code-sandbox 서비스 필요"],
            )

        url = f"{self._sandbox_url}/validate"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(
                    url,
                    json={"code": code, "language": lang},
                )
                r.raise_for_status()
                j = r.json()
        except Exception as e:
            log.warning("sandbox 호출 실패: %s", e)
            return SyntaxValidationOutcome(
                valid=False,
                syntax_errors=[f"sandbox_http_error:{e!s}"],
                style_warnings=[],
            )

        return SyntaxValidationOutcome(
            valid=bool(j.get("valid")),
            syntax_errors=list(j.get("syntax_errors") or []),
            style_warnings=list(j.get("style_warnings") or []),
        )

    async def validate_polyglot_ontology(self, code: str, language: str) -> object:
        lang = normalize_language(language)
        if lang not in SUPPORTED_LANGUAGES:
            lang = "python"
        payload = {"code": code, "function_name": infer_function_name(code, lang)}
        v = OntologyValidator.for_polyglot(lang)
        return await v.validate(payload)

    async def generate_code(
        self,
        task: str,
        language: str,
        framework: str | None = None,
    ) -> str:
        """LLM 직접 호출로 스니펫 생성 (Ontology 적용 전)."""
        l = normalize_language(language)
        if l not in SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported language: {language}")
        system = (
            "You are an expert programmer. Respond with code only unless asked. "
            + self.build_system_addon(language, framework)
        )
        prompt = (
            self.build_pipeline_user_prompt(task, language)
        )
        client = LLMClient()
        res = await client.chat(
            prompt,
            role=ModelRole.FAST,
            system=system,
            max_tokens=4096,
            temperature=0.35,
        )
        return (res.content or "").strip()


LANGUAGE_CATALOG: list[dict[str, object]] = [
    {
        "id": "python",
        "label": "Python",
        "frameworks": ["fastapi", "django", "flask"],
        "validator": "ast.parse + Ontology SOFTWARE / POLYGLOT",
        "example_task": "두 정수의 최대공약수를 구하는 gcd(a,b) 함수",
    },
    {
        "id": "typescript",
        "label": "TypeScript",
        "frameworks": ["express", "fastify"],
        "validator": "tsc --noEmit (code-sandbox) + Ontology POLYGLOT",
        "example_task": "문자열이 비어있지 않으면 true를 반환하는 isNonEmpty(s: string): boolean",
    },
    {
        "id": "rust",
        "label": "Rust",
        "frameworks": ["axum", "actix", "tokio"],
        "validator": "rustc --crate-type lib (sandbox) + Ontology POLYGLOT",
        "example_task": "i32 두 개 중 큰 값을 반환하는 max_i32",
    },
]


def list_supported_languages() -> dict[str, object]:
    return {
        "languages": [x["id"] for x in LANGUAGE_CATALOG],
        "catalog": LANGUAGE_CATALOG,
        "sandbox_required": sorted(SUPPORTED_LANGUAGES - {"python"}),
    }
