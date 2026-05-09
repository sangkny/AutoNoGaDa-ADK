"""코드 구조 → SOFTWARE Ontology 입력 dict (경량 휴리스틱)."""
from __future__ import annotations

import ast
import re

from ontology.validator import OntologyValidator


class CodeAnalyzer:
    """
    생성된 소스 문자열을 분석해 OntologyValidator(SOFTWARE)에 넣을
    구조화 dict 를 만듭니다.

    본 단계에서는 AST 기반 근삿값이며, 향후 정적 분석기로 대체 가능합니다.
    """

    def __init__(self) -> None:
        self._validator = OntologyValidator.for_software()

    async def validate_snippet(self, code: str, language: str) -> object:
        """코드 문자열 검증 결과(ValidationResult)."""
        payload = self._snippet_to_payload(code, language)
        return await self._validator.validate(payload)

    def _snippet_to_payload(self, code: str, language: str) -> dict:
        lang = (language or "python").lower()
        if lang != "python":
            return self._fallback_payload(code, language)

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._fallback_payload(code, language)

        funcs = [
            n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        fn = funcs[0] if funcs else None
        if fn is None:
            return self._fallback_payload(code, language)

        lines = max(1, len(code.splitlines()))
        params = [a.arg for a in fn.args.args]
        has_ret = any(
            isinstance(n, ast.Return) and n.value is not None
            for n in ast.walk(fn)
        )
        is_async = isinstance(fn, ast.AsyncFunctionDef)
        has_await = any(isinstance(n, ast.Await) for n in ast.walk(fn)) if is_async else None

        complexity = min(10, max(1, lines // 5))

        return {
            "function_name":   fn.name,
            "parameters":      params,
            "return_type":     "Any" if has_ret else "None",
            "line_count":      min(lines, 50),
            "complexity":      complexity,
            "parameter_count": len(params),
            "nesting_depth":   2,
            "language":        "python",
            "is_async":        is_async,
            "has_await":       has_await,
            "has_return_value": has_ret,
        }

    @staticmethod
    def _fallback_payload(code: str, language: str) -> dict:
        lines = max(1, len(code.splitlines()))
        m = re.search(r"def\s+([a-zA-Z_]\w*)\s*\(", code)
        name = m.group(1) if m else "generated_fn"
        return {
            "function_name":    name,
            "parameters":       [],
            "return_type":      "str",
            "line_count":       min(lines, 40),
            "complexity":       4,
            "parameter_count":  0,
            "nesting_depth":    2,
            "language":         language or "python",
            "is_async":         False,
            "has_return_value": True,
        }
