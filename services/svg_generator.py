"""SVG 자동 생성 — LLM(FAST) + OntologyValidator(SVG 도메인) + Redis 캐시.

관측(Phase 2 Month 3 — book §16.10.3 / §16.12 Step 3-b): LLM ``chat`` 호출
직전에 ``analyze_prompt_for_model`` + ``chunking_metrics_snapshot`` 으로
입력 토큰 추정·청크 권장값을 한 줄 구조화 로그(``adk_svg_context``)로 흘린다.
거동 변경은 없으며, 이 로그는 Prometheus exporter(§16.12 중기)의 입력이 된다.
MEDI/CoOps 와 동일 키 집합. (참고: SVG 생성은 단일 호출이라 청크 분할은
권장되지 않고, fits_context=false 시 호출자가 description 을 줄여야 한다.)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.context_chunking import (
    analyze_prompt_for_model,
    chunk_prompt_for_model,
    chunking_metrics_snapshot,
)
from llm.base import ModelRole
from llm.client import LLMClient
from observability.prom_metrics import observe_chunking_snapshot
from ontology.validator import OntologyValidator

from config import get_settings

log = logging.getLogger("services.svg_generator")

SVG_NS = "http://www.w3.org/2000/svg"

# Ontology `constraints.enums.svg_type` 과 일치 (6종)
SVG_TYPES: tuple[str, ...] = (
    "flowchart",
    "architecture",
    "sequence",
    "er_diagram",
    "medical_report",
    "business_process",
)

# 기본 템플릿 매핑 + style.variant / style.template 로 교체 가능
_DEFAULT_TEMPLATE: dict[str, str] = {
    "flowchart": "flowchart_basic.svg",
    "architecture": "architecture_3tier.svg",
    "sequence": "sequence_api_call.svg",
    "er_diagram": "er_diagram_basic.svg",
    "medical_report": "medical_eye_report.svg",
    "business_process": "business_approval.svg",
}

_TEMPLATES_ROOT = Path(__file__).resolve().parent / "svg_templates"

# 물리 템플릿 파일 (API /for_svg 회귀 테스트 대상) — Phase 2 W2: 20개
TEMPLATE_FILES: tuple[str, ...] = (
    "flowchart_basic.svg",
    "flowchart_decision.svg",
    "flowchart_parallel.svg",
    "flowchart_loop.svg",
    "flowchart_swimlane.svg",
    "flowchart_data_flow.svg",
    "architecture_3tier.svg",
    "architecture_microservice.svg",
    "architecture_event_driven.svg",
    "architecture_serverless.svg",
    "architecture_ai_pipeline.svg",
    "medical_eye_report.svg",
    "medical_diagnosis_flow.svg",
    "business_approval.svg",
    "business_contract_flow.svg",
    "business_kpi_dashboard.svg",
    "sequence_api_call.svg",
    "sequence_auth_flow.svg",
    "er_diagram_basic.svg",
    "er_diagram_medical.svg",
)


@dataclass
class SVGResult:
    svg_content: str
    svg_type: str
    cached: bool
    latency_ms: float
    ontology_passed: bool
    ontology_summary: str | None = None


class SVGGeneratorService:
    """
    LLM → 구조화된 SVG 자동 생성 (FAST 모델, gemma-4-e4b 등).
    - Redis 캐시 7일 TTL
    - XML 파싱 + SVG 루브트 + viewBox
    - OntologyValidator.for_svg() (XSS·용량·타입별 규칙)
    """

    CACHE_PREFIX = "autonogada:svg:"
    CACHE_TTL_SEC = 7 * 24 * 3600

    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm = LLMClient()
        self._ontology = OntologyValidator.for_svg()

    def _template_path(self, svg_type: str, style: dict[str, Any] | None) -> Path:
        style = style or {}
        tpl = style.get("template")
        if isinstance(tpl, str) and tpl.endswith(".svg") and tpl in TEMPLATE_FILES:
            return _TEMPLATES_ROOT / tpl

        name = _DEFAULT_TEMPLATE.get(svg_type, "flowchart_basic.svg")
        if svg_type == "architecture" and style.get("variant") == "microservice":
            name = "architecture_microservice.svg"
        if svg_type == "flowchart" and style.get("variant") == "decision":
            name = "flowchart_decision.svg"
        return _TEMPLATES_ROOT / name

    def _load_template(self, svg_type: str, style: dict[str, Any] | None) -> str:
        path = self._template_path(svg_type, style)
        if not path.is_file():
            log.warning("템플릿 없음 — fallback: flowchart_basic (%s)", path)
            path = _TEMPLATES_ROOT / "flowchart_basic.svg"
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _cache_key(description: str, svg_type: str, style: dict[str, Any] | None) -> str:
        raw = json.dumps(
            {"d": description, "t": svg_type, "s": style or {}},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _redis_get(self, key: str) -> str | None:
        rurl = (self._settings.redis_url or "").strip()
        if not rurl:
            return None
        try:
            import redis.asyncio as redis

            client = redis.from_url(rurl, decode_responses=True)
            try:
                return await client.get(key)
            finally:
                await client.aclose()
        except Exception as e:
            log.warning("Redis GET 실패 — 캐시 미스 처리: %s", e)
            return None

    async def _redis_set(self, key: str, value: str) -> None:
        rurl = (self._settings.redis_url or "").strip()
        if not rurl:
            return
        try:
            import redis.asyncio as redis

            client = redis.from_url(rurl, decode_responses=True)
            try:
                await client.set(key, value, ex=self.CACHE_TTL_SEC)
            finally:
                await client.aclose()
        except Exception as e:
            log.warning("Redis SET 실패: %s", e)

    @staticmethod
    def extract_svg_xml(text: str) -> str:
        block = text.strip()
        m = re.search(r"<svg[\s\S]*?</svg>", block, re.IGNORECASE)
        if m:
            return m.group(0).strip()
        return block

    async def _call_llm(self, description: str, svg_type: str, template: str) -> str:
        system = (
            "당신은 SVG 1.1 전문가입니다. 반드시 유효한 XML 단일 <svg>...</svg> 만 출력하세요. "
            "<script>, 외부 http(s) 링크, javascript: 금지. "
            "viewBox와 xmlns를 포함하세요."
        )
        prompt = (
            f"다음 설명에 맞는 SVG를 작성하세요.\n"
            f"[타입] {svg_type}\n"
            f"[설명] {description}\n\n"
            "[참고 템플릿 — 변수 플레이스홀더를 채우거나 구조를 재사용]\n"
            f"{template[:12000]}\n"
        )

        # ── 컨텍스트 청킹 메트릭 관측 (book §16.10.3 / §16.12 Step 3-b) ────────
        # 거동은 바꾸지 않고, 한 번의 호출에 대해 ``chunking_*`` 표준 11종 키를
        # 한 줄 로그로 흘린다. FAST 모델 라벨 + svg_type 메타를 ``extra`` 로 병합.
        # MEDI/CoOps 의 동명 헬퍼들과 키 집합 1:1 일치.
        try:
            _model_label = os.getenv("LOCAL_FAST_MODEL", "google/gemma-4-e4b")
            _analysis = analyze_prompt_for_model(prompt, model=_model_label, system=system)
            _chunks = (
                chunk_prompt_for_model(prompt, model=_model_label)
                if not _analysis.fits_context
                else []
            )
            _snap = chunking_metrics_snapshot(
                _analysis,
                _chunks,
                extra={
                    "flow": "adk_svg_generation",
                    "svg_type": svg_type,
                    "template_chars": len(template[:12000]),
                    "role": "fast",
                },
            )
            log.info("adk_svg_context", extra=_snap)
            # Step 4 — Prometheus 텍스트 포맷 export (best-effort, 거동 영향 0)
            observe_chunking_snapshot(
                _snap,
                service="adk_svg",
                flow="adk_svg_generation",
                strategy="fastest",
                domain="svg",
            )
        except Exception as _ctxe:
            log.debug("[chunking_metrics] 관측 한 줄 로깅 실패(무시): %s", _ctxe)

        res = await self._llm.chat(
            prompt,
            role=ModelRole.FAST,
            system=system,
            max_tokens=4096,
            temperature=0.35,
        )
        return self.extract_svg_xml(res.content or "")

    def structural_check(self, svg_content: str) -> tuple[bool, list[str]]:
        """XML 파싱, 루트 <svg>, viewBox 권고, 태그 수."""
        errs: list[str] = []
        try:
            root = ET.fromstring(svg_content)
        except ET.ParseError as e:
            return False, [f"XML_PARSE: {e}"]
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        if tag.lower() != "svg":
            errs.append("ROOT_NOT_SVG")
        vb = root.attrib.get("viewBox") or root.attrib.get("viewbox")
        if not vb or not vb.strip():
            errs.append("MISSING_VIEWBOX")
        open_tags = len(re.findall(r"<[^/!?][^>]*>", svg_content))
        if open_tags > 1000:
            errs.append(f"TOO_MANY_ELEMENTS:{open_tags}")
        w = root.attrib.get("width", "1")
        h = root.attrib.get("height", "1")
        try:
            wi = float(re.sub(r"[^\d.]", "", w) or "1")
            hi = float(re.sub(r"[^\d.]", "", h) or "1")
            if wi <= 0 or hi <= 0:
                errs.append("INVALID_DIMENSIONS")
        except ValueError:
            pass
        return len(errs) == 0, errs

    async def validate(self, svg_content: str) -> bool:
        ok, _ = self.structural_check(svg_content)
        return ok

    async def validate_full(self, svg_content: str, svg_type: str) -> Any:
        """OntologyValidator 포함 전체 검증 결과."""
        payload: dict[str, Any] = {"svg_content": svg_content, "svg_type": svg_type}
        if svg_type == "medical_report":
            payload["no_pii"] = True
        return await self._ontology.validate(payload)

    async def generate(
        self,
        description: str,
        svg_type: str,
        style: dict[str, Any] | None = None,
        *,
        use_cache: bool = True,
    ) -> SVGResult:
        if svg_type not in SVG_TYPES:
            raise ValueError(f"지원하지 않는 svg_type: {svg_type}")

        t0 = time.perf_counter()
        style = style or {}
        cache_key = self.CACHE_PREFIX + self._cache_key(description, svg_type, style)

        if use_cache:
            cached = await self._redis_get(cache_key)
            if cached:
                lat = (time.perf_counter() - t0) * 1000.0
                ov = await self.validate_full(cached, svg_type)
                return SVGResult(
                    svg_content=cached,
                    svg_type=svg_type,
                    cached=True,
                    latency_ms=lat,
                    ontology_passed=bool(ov.passed),
                    ontology_summary=ov.summary,
                )

        template = self._load_template(svg_type, style)
        svg_xml = await self._call_llm(description, svg_type, template)
        struct_ok, s_errs = self.structural_check(svg_xml)
        if not struct_ok:
            log.warning("LLM SVG 구조 검증 실패 — 템플릿 기반 최소 SVG로 대체: %s", s_errs)
            svg_xml = self._minimal_svg_from_template(template, description, svg_type)

        ont = await self.validate_full(svg_xml, svg_type)
        lat = (time.perf_counter() - t0) * 1000.0

        if use_cache and ont.passed:
            await self._redis_set(cache_key, svg_xml)

        return SVGResult(
            svg_content=svg_xml,
            svg_type=svg_type,
            cached=False,
            latency_ms=lat,
            ontology_passed=bool(ont.passed),
            ontology_summary=ont.summary,
        )

    @staticmethod
    def _minimal_svg_from_template(template: str, description: str, svg_type: str) -> str:
        """LLM 출력이 깨졌을 때 플레이스홀더 치환만 수행한 안전한 SVG."""
        safe_desc = (
            description.replace("&", "&amp;")
            .replace("<", "")
            .replace(">", "")[:200]
        )
        body = template
        for key in ("title", "subtitle", "label", "body", "caption"):
            body = body.replace("{" + key + "}", safe_desc)
        body = re.sub(r"\{[a-zA-Z0-9_]+\}", safe_desc, body)
        if "<svg" not in body.lower():
            return (
                f'<svg xmlns="{SVG_NS}" viewBox="0 0 400 120" width="400" height="120">'
                f'<rect fill="#f0f0f0" width="400" height="120" stroke="#333"/>'
                f'<text x="20" y="70" font-size="14" font-family="sans-serif">{safe_desc}</text>'
                f"</svg>"
            )
        return body
