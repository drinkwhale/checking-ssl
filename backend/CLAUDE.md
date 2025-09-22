# Backend CLAUDE.md

## 모듈 개요
SSL Certificate Monitor의 백엔드 시스템 - Python 3.11+ FastAPI 기반 SSL 인증서 모니터링 API 서버입니다.

## 핵심 아키텍처

### Library-First Architecture
- **핵심 비즈니스 로직**: `src/lib/`에 독립적인 라이브러리로 구현
- **API 레이어**: `src/api/` - 얇은 웹 인터페이스 역할
- **서비스 레이어**: `src/services/` - 라이브러리들을 조합한 복합 비즈니스 로직

### 디렉토리 구조

```
src/
├── main.py              # FastAPI 애플리케이션 엔트리포인트
├── database.py          # 데이터베이스 설정 및 초기화
├── scheduler.py         # APScheduler 기반 정기 작업 스케줄러
├── background.py        # 백그라운드 작업 실행기
├── models/              # SQLAlchemy ORM 모델
│   ├── website.py       # Website 모델 (UUID 기반, HTTPS 전용)
│   └── ssl_certificate.py # SSLCertificate 모델 (1:N 관계)
├── lib/                 # 독립적인 비즈니스 로직 라이브러리
│   ├── ssl_checker.py   # SSL 인증서 검증 (cryptography 기반)
│   ├── website_manager.py # 웹사이트 CRUD 관리
│   └── notification_service.py # Teams 웹훅 알림
├── services/            # 복합 서비스 레이어
│   ├── website_service.py # 웹사이트 + SSL 통합 서비스
│   ├── ssl_service.py   # SSL 관련 서비스
│   └── notification_service.py # 알림 서비스
└── api/                 # FastAPI 라우터
    ├── websites.py      # /api/websites 엔드포인트
    ├── ssl.py          # /api/ssl 엔드포인트
    ├── health.py       # /api/health 헬스체크
    └── tasks.py        # /api/tasks 작업 관리
```

## 핵심 규칙

### URL 검증
- **HTTPS만 허용**: HTTP 프로토콜 불허
- **루트 도메인만**: 경로 포함 불가 (예: `/path` 금지)
- **포트 허용**: `https://example.com:8443` 가능

### 데이터베이스
- **Primary DB**: PostgreSQL (운영), SQLite (개발/테스트)
- **ORM**: SQLAlchemy + AsyncSession (비동기 처리)
- **Migration**: Alembic
- **Relationship**: Website → SSLCertificate (1:N, CASCADE DELETE)

### 오류 처리 전략
- **라이브러리 레벨**: 구체적 예외 (`SSLCheckError`, `WebsiteManagerError`)
- **서비스 레벨**: `WebsiteServiceError`로 통합
- **API 레벨**: HTTPException → JSON 응답

### 비동기 처리
- **모든 I/O 작업**: asyncio 기반
- **데이터베이스**: AsyncSession 사용
- **HTTP 요청**: httpx 라이브러리
- **SSL 체크**: 비동기 소켓 연결

## 주요 라이브러리 사용법

### SSL Checker (`lib/ssl_checker.py`)
```python
from backend.src.lib.ssl_checker import SSLChecker

checker = SSLChecker()
result = await checker.check_ssl_certificate("https://example.com")
```

### Website Manager (`lib/website_manager.py`)
```python
from backend.src.lib.website_manager import WebsiteManager

manager = WebsiteManager(session)
website = await manager.create_website("https://example.com", "My Site")
```

### Notification Service (`lib/notification_service.py`)
```python
from backend.src.lib.notification_service import NotificationService

notifier = NotificationService()
await notifier.send_expiry_notification(websites)
```

## 개발 명령어

### 서버 실행
```bash
# 개발 서버 (자동 리로드)
python -m backend.src.main

# 또는 uvicorn 직접 실행
uvicorn backend.src.main:app --host 0.0.0.0 --port 8000 --reload
```

### 데이터베이스
```bash
# 초기화
python -c "from backend.src.database import init_db; import asyncio; asyncio.run(init_db())"

# 마이그레이션 생성
alembic revision --autogenerate -m "description"

# 마이그레이션 적용
alembic upgrade head
```

### 테스트
```bash
# 전체 테스트
pytest tests/ -v

# 커버리지 포함
pytest tests/ --cov=backend.src --cov-report=html

# 특정 테스트
pytest tests/unit/test_ssl_checker.py -v
```

## 성능 최적화

### 동시성 제어
- **최대 동시 SSL 체크**: 5개 사이트
- **타임아웃**: 10초 (SSL 연결)
- **연결 풀**: pool_size=5, max_overflow=10

### 인덱스 설정
- **활성 사이트 + 만료일**: 복합 인덱스
- **UUID 기반 조회**: 자동 인덱스

## 환경 변수
- `DATABASE_URL`: 데이터베이스 연결 문자열
- `TEAMS_WEBHOOK_URL`: Teams 알림용 웹훅 URL
- `SSL_TIMEOUT_SECONDS`: SSL 체크 타임아웃 (기본: 10초)
- `MAX_CONCURRENT_CHECKS`: 동시 SSL 체크 수 (기본: 5개)

## API 응답 형식
모든 API는 일관된 JSON 응답 형식을 따릅니다:
```json
{
  "website": { /* Website 모델 */ },
  "ssl_certificate": { /* SSLCertificate 모델 */ }
}
```

## 백그라운드 작업
- **스케줄러**: APScheduler (매일 자정 SSL 체크)
- **실행기**: asyncio 기반 ThreadPoolExecutor
- **작업 큐**: 메모리 기반 (개발), Redis 권장 (운영)