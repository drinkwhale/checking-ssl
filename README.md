# SSL Certificate Monitoring Dashboard

웹사이트 SSL 인증서 모니터링 및 만료 알림 시스템

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 📋 개요

SSL 인증서의 만료 상태를 자동으로 모니터링하고 Microsoft Teams로 알림을 보내는 웹 대시보드입니다.

**주요 기능**
- SSL 인증서 자동 모니터링 및 만료 알림
- 주간 스케줄링 및 백그라운드 작업 처리
- Microsoft Teams 웹훅 알림
- 웹 기반 실시간 대시보드

**기술 스택**
- Backend: Python 3.11+ (FastAPI, SQLAlchemy)
- Frontend: 바닐라 JavaScript + Tailwind CSS
- Database: PostgreSQL / SQLite
- Architecture: Library-First Pattern

![alt text](image.png)

## 🚀 빠른 시작

**필수 요구사항**: Python 3.11+, uv

```bash
# 1. 프로젝트 설정
git clone <repository-url>
cd ssl-certificate-monitor
uv sync

# 2. 환경 변수 설정
cp .env.example .env
# DATABASE_URL, TEAMS_WEBHOOK_URL 등 설정

# 3. 데이터베이스 초기화
python -c "from backend.src.database import init_db; import asyncio; asyncio.run(init_db())"

# 4. 서버 실행
uvicorn backend.src.main:app --host 0.0.0.0 --port 8000 --reload
```

**접속**
- 대시보드: http://localhost:8000
- API 문서: http://localhost:8000/api/docs

## 📖 API 엔드포인트

**웹사이트 관리**
- `POST/GET/PUT/DELETE /api/websites` - 웹사이트 CRUD
- `POST /api/websites/{id}/ssl-check` - 수동 SSL 체크

**SSL 모니터링**
- `GET /api/ssl/status` - SSL 상태 요약
- `GET /api/ssl/certificates` - 인증서 목록
- `POST /api/ssl/quick-check` - 빠른 SSL 체크

**시스템 관리**
- `GET /api/tasks/scheduler/status` - 스케줄러 상태
- `GET /api/health` - 시스템 헬스체크

## ⚙️ 환경 설정

**.env 파일**
```env
# 데이터베이스
DATABASE_URL=postgresql://user:password@localhost/ssl_monitor

# Teams 알림 설정
TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/your-webhook-url
NOTIFICATION_ENABLED=true
NOTIFICATION_DAYS_BEFORE=30,7,1  # 만료 30, 7, 1일 전 알림
NOTIFICATION_LANGUAGE=ko          # 알림 언어 (ko/en)
DASHBOARD_URL=https://ssl-checker.example.com  # 알림에 포함될 대시보드 링크

# 스케줄러 설정
ENABLE_SCHEDULER=true
SSL_CHECK_CRON=0 9 * * 1  # 매주 월요일 오전 9시

# SSL 체크 설정
SSL_TIMEOUT_SECONDS=10
MAX_CONCURRENT_CHECKS=5
```

### 알림 설정 방법

**1. Teams 웹훅 URL 생성**
- Teams 채널 → 커넥터 → "Incoming Webhook" 추가
- 또는 [Power Automate](https://flow.microsoft.com)에서 HTTP 요청 트리거 생성

**2. 알림 발송 일수 설정**
```env
NOTIFICATION_DAYS_BEFORE=30,14,7,3,1
```
- 설정된 일수에 정확히 해당하는 인증서만 알림 발송
- 예: 30일 전, 7일 전, 1일 전에 각각 알림

**3. 동적 설정 변경 (API 사용)**
```bash
# 설정 조회
GET /api/settings

# 설정 업데이트 (재시작 없이 즉시 적용)
PUT /api/settings
{
  "webhook_url": "https://outlook.office.com/webhook/...",
  "notification_enabled": true,
  "notification_days_before": "30,7,1",
  "notification_language": "ko"
}
```

**4. 알림 테스트**
```bash
# CLI로 테스트 알림 발송
python -m backend.src.lib.notification_service test

# API로 테스트
POST /api/notifications/test
```

## 🛠️ 개발

**핵심 명령어**
```bash
# 개발 서버
uvicorn backend.src.main:app --reload

# 코드 품질
black backend/src tests/
ruff check backend/src tests/ --fix
mypy backend/src

# 테스트
pytest tests/ -v
pytest tests/ --cov=backend.src --cov-report=html

# 데이터베이스 마이그레이션
alembic revision --autogenerate -m "description"
alembic upgrade head
```

**프로젝트 구조**
```
backend/src/
├── lib/          # 핵심 라이브러리 (ssl_checker, website_manager)
├── api/          # REST API 엔드포인트
├── services/     # 비즈니스 서비스 계층
├── models/       # 데이터베이스 모델
└── scheduler.py  # 스케줄링 작업
```

## 🐳 배포

**Docker**
```bash
docker-compose -f deployment/docker/docker-compose.dev.yml up
```

**Kubernetes**
```bash
kubectl apply -f deployment/k8s/
```

## 📋 핵심 특징

- **Library-First Architecture**: 독립적인 라이브러리 모듈로 구성
- **자동 스케줄링**: 주간 SSL 체크 및 만료 알림
- **Teams 알림**: 만료 임박 시 Microsoft Teams 웹훅 발송
- **CLI 도구**: 각 라이브러리별 독립 실행 가능

## 📄 라이센스

MIT License - 자세한 내용은 [LICENSE](LICENSE) 파일 참조