# AutoNoGaDa-ADK

코드 자동화 서비스 — **shared-libraries** 의 `Orchestrator(PIPELINE)` + `OntologyValidator(SOFTWARE)` 를 FastAPI 로 노출합니다.

## 로컬 개발 (Docker)

`projects/docker-compose.dev.yml` 에서 **포트 8002 (호스트) → 8000 (컨테이너)** 로 매핑됩니다.

```bash
cd projects
docker compose -f docker-compose.dev.yml up -d autonogada-api
curl http://localhost:8002/health
curl http://localhost:8002/docs
```

## API 요약

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | DB 연결 포함 헬스 |
| POST | `/api/v1/tasks/` | 코드 작업 등록 |
| GET | `/api/v1/tasks/{id}` | 작업 조회 |
| GET | `/api/v1/tasks/` | 최근 작업 목록 |
| POST | `/api/v1/pipeline/run` | `{ "task_id": "..." }` 로 PIPELINE 실행 |
| POST | `/api/v1/pipeline/run-inline` | 설명만으로 바로 실행(데모) |
| POST | `/api/v1/pipeline/generate` | 코드 생성 (`auto_commit=true` 쿼리 시 스니펫 + Git 커밋) |
| POST | `/api/v1/pipeline/review` | 리뷰 |
| POST | `/api/v1/pipeline/fix` | 자동 수정 |

## 데이터베이스

개발 편의상 **MEDI-IOT와 동일 PostgreSQL(`mediiot`)** 에 `software_*` 테이블을 둡니다. 스키마는 **`alembic upgrade head`** (버전 테이블: `alembic_version_autonogada`)로 관리합니다.

이전 버전 테이블 `alembic_version_autonaogada` 를 쓰던 DB는 Postgres에서 `ALTER TABLE ... RENAME TO alembic_version_autonogada` 로 맞춘 뒤 `alembic upgrade head` 하세요.

운영 시 전용 DB/스키마 분리 권장.

## 환경 변수

`x-llm-env` / `x-db-env` 는 `docker-compose.dev.yml` 에서 MEDI-IOT 와 동일하게 주입됩니다  
(`LOCAL_BASE_URL` → host.docker.internal LM Studio).

## Git 무인 커밋 (Week 5)

- Compose 기본값: `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL` (이미지 `ENV` 에도 폴백)
- 생성 시 `generated/snippets/autonogada_{task_prefix}.py` 에 저장 후 해당 경로만 `git add`
- 원격 **`git push`** 는 `GitService.push` 로 **별도 호출** (기본 생성 플로우에는 포함 안 함)

```bash
curl -s -X POST "http://localhost:8002/api/v1/pipeline/generate?auto_commit=true" \\
  -H "Content-Type: application/json" \\
  -d '{"task":"add(a,b) 헬퍼","language":"python"}' | jq .git
```

## Git 저장소

- 독립 저장소: `git@github.com:sangkny/AutoNoGaDa-ADK.git` (브랜치 `main`, 초기 커밋 `c074b36` 기준 동기화됨)
- 상위 `projects` 레포에도 동일 소스 디렉터리가 포함되어 있습니다(`docker-compose` 빌드 컨텍스트). Git submodule 전환은 선택 사항입니다.
