# AutoNoGaDa-ADK

코드 자동화 서비스 — **shared-libraries** 의 `Orchestrator(PIPELINE)` + `OntologyValidator(SOFTWARE)` 를 FastAPI 로 노출합니다.

## 로컬 개발 (Docker)

`projects/docker-compose.dev.yml` 에서 **포트 8002 (호스트) → 8000 (컨테이너)** 로 매핑됩니다.

```bash
cd projects
docker compose -f docker-compose.dev.yml up -d autonaogada-api
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

## 데이터베이스

개발 편의상 **MEDI-IOT와 동일 PostgreSQL(`mediiot`)** 에 `software_*` 테이블을 생성합니다 (`create_all`).

운영 시 전용 DB/스키마 분리 권장.

## 환경 변수

`x-llm-env` / `x-db-env` 는 `docker-compose.dev.yml` 에서 MEDI-IOT 와 동일하게 주입됩니다  
(`LOCAL_BASE_URL` → host.docker.internal LM Studio).

## Git 원격 (Submodule)

상위 `projects` 레포에서는 본 디렉터리를 Git submodule 로 등록합니다.  
원격 저장소: `https://github.com/sangkny/AutoNoGaDa-ADK`
