# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SSL Certificate Monitoring Dashboard - 웹사이트 SSL 인증서 모니터링 및 만료 알림 시스템입니다.

**Tech Stack**: Python 3.11+ (FastAPI), SQLAlchemy ORM, PostgreSQL/SQLite, 바닐라 JavaScript

## Common Development Commands

### Backend Development
```bash
# 개발 서버 실행
cd backend && python -m src.main

# 또는 uvicorn 직접 실행
uvicorn backend.src.main:app --host 0.0.0.0 --port 8000 --reload

# 데이터베이스 초기화 (개발용)
python -c "from backend.src.database import init_db; import asyncio; asyncio.run(init_db())"
```

### Code Quality
```bash
# 코드 포맷팅 (Black + Ruff)
black backend/src tests/
ruff check backend/src tests/ --fix

# 타입 체크
mypy backend/src

# 모든 테스트 실행
pytest tests/ -v

# 특정 테스트 파일 실행
pytest tests/integration/test_add_website_flow.py -v

# 커버리지 포함 테스트
pytest tests/ --cov=backend.src --cov-report=html
```

### Database Operations
```bash
# 마이그레이션 생성 (Alembic)
alembic revision --autogenerate -m "migration description"

# 마이그레이션 적용
alembic upgrade head

# 마이그레이션 롤백
alembic downgrade -1
```

## Application Architecture

### Core Architecture Pattern
이 프로젝트는 **Library-First Architecture**를 따릅니다:
- 핵심 비즈니스 로직은 `backend/src/lib/`에 독립적인 라이브러리로 구현
- FastAPI 레이어(`backend/src/api/`)는 얇은 웹 인터페이스 역할
- 서비스 레이어(`backend/src/services/`)에서 라이브러리들을 조합하여 복합 비즈니스 로직 처리

### Key Components

**Models Layer** (`backend/src/models/`):
- `Website`: 모니터링 대상 웹사이트 엔티티 (HTTPS 전용, UUID 기반)
- `SSLCertificate`: SSL 인증서 정보 및 히스토리 관리

**Library Layer** (`backend/src/lib/`):
- `ssl_checker.py`: SSL 인증서 정보 수집 및 검증 (cryptography 기반)
- `website_manager.py`: 웹사이트 CRUD 및 상태 관리
- `notification_service.py`: Microsoft Teams 웹훅 알림 처리

**Service Layer** (`backend/src/services/`):
- `website_service.py`: 웹사이트 + SSL 체크 통합 서비스
- 라이브러리들을 조합하여 복합 워크플로우 처리

**API Layer** (`backend/src/api/`):
- RESTful API 엔드포인트 제공 (`/api/websites`, `/api/ssl`, `/api/health`)
- Pydantic 기반 요청/응답 모델 검증

### Database Design
- **Primary Database**: PostgreSQL (운영), SQLite (개발/테스트)
- **ORM**: SQLAlchemy with async support (AsyncSession)
- **Migration**: Alembic
- **Key Relationships**: Website -> SSLCertificate (1:N, CASCADE DELETE)

### Test Architecture
- **Contract Tests** (`tests/contract/`): API 스펙 계약 검증
- **Integration Tests** (`tests/integration/`): 전체 사용자 워크플로우 테스트
- **Unit Tests** (`tests/unit/`): 개별 라이브러리 단위 테스트

각 라이브러리는 CLI 인터페이스를 제공하여 독립적으로 테스트 가능합니다.

## Development Guidelines

### URL Validation Rules
웹사이트 URL은 엄격한 검증을 거칩니다:
- HTTPS 프로토콜만 허용
- 루트 도메인만 허용 (경로 포함 불가)
- 포트 번호는 허용 (예: `https://example.com:8443`)

### SSL Check Process
SSL 체크는 다음 단계로 진행됩니다:
1. TCP 연결 설정 (timeout: 10초)
2. TLS 핸드셰이크 및 인증서 체인 수집
3. 인증서 정보 파싱 및 검증
4. 데이터베이스 저장 및 히스토리 관리

### Error Handling Strategy
- 라이브러리 레벨: 구체적인 예외 클래스 정의 (`SSLCheckError`, `WebsiteManagerError`)
- 서비스 레벨: `WebsiteServiceError`로 통합
- API 레벨: HTTPException으로 변환 후 JSON 응답

### Async Pattern
모든 I/O 작업은 비동기로 처리:
- 데이터베이스: AsyncSession 사용
- HTTP 요청: httpx 라이브러리 사용
- SSL 체크: asyncio-based 구현

## Environment Configuration

주요 환경 변수 (.env.example 참조):
- `DATABASE_URL`: 데이터베이스 연결 문자열
- `TEAMS_WEBHOOK_URL`: Teams 알림용 웹훅 URL
- `SSL_TIMEOUT_SECONDS`: SSL 체크 타임아웃 (기본: 10초)
- `MAX_CONCURRENT_CHECKS`: 동시 SSL 체크 수 (기본: 5개)

## Performance Considerations

- **Concurrent SSL Checks**: 최대 5개 사이트 동시 체크로 성능 최적화
- **Database Indexing**: 활성 사이트 + 만료일 복합 인덱스 구성
- **Connection Pooling**: SQLAlchemy 연결 풀 설정 (pool_size=5, max_overflow=10)

## Deployment Notes

프로젝트는 Docker + Kubernetes 배포를 위해 설계됨:
- `deployment/docker/`: Docker Compose 설정
- `deployment/k8s/`: Kubernetes 매니페스트
- Health check endpoint: `/api/health`
- Graceful shutdown 지원 (lifespan 이벤트)