# SSL Certificate Monitoring Dashboard

웹사이트 SSL 인증서 모니터링 및 만료 알림 시스템

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 📋 개요

SSL 인증서의 만료 상태를 자동으로 모니터링하고 Microsoft Teams로 알림을 보내는 웹 대시보드입니다.

### 주요 기능
- **SSL 인증서 자동 모니터링**: 등록된 웹사이트의 SSL 인증서 상태를 자동으로 체크
- **만료 알림**: Microsoft Teams 웹훅을 통한 만료 임박 알림 (설정된 일수 이하)
- **주간 스케줄링**: Cron 기반 자동 SSL 체크 및 알림 발송
- **실시간 대시보드**: 웹 기반 UI에서 모든 인증서 상태 확인
- **동적 설정 관리**: API를 통한 실시간 설정 변경 (재시작 불필요)

### 기술 스택
- **Backend**: Python 3.11+ (FastAPI, SQLAlchemy 2.0)
- **Frontend**: 바닐라 JavaScript + Tailwind CSS
- **Database**: PostgreSQL (운영) / SQLite (개발)
- **Scheduler**: APScheduler (Cron 기반)
- **Architecture**: Library-First Pattern

![SSL Monitoring Dashboard](image.png)

---

## 🚀 빠른 시작

### 필수 요구사항
- Python 3.11 이상
- pip 또는 uv (권장)

### 설치 및 실행

```bash
# 1. 저장소 클론
git clone <repository-url>
cd cheking-ssl

# 2. 의존성 설치 (uv 사용 권장)
pip install -e ".[dev]"
# 또는: uv sync

# 3. 환경 변수 설정
cp .env.example .env
# .env 파일을 편집하여 DATABASE_URL, TEAMS_WEBHOOK_URL 등 설정

# 4. 데이터베이스 초기화
python -c "from backend.src.database import init_db; import asyncio; asyncio.run(init_db())"

# 5. 서버 실행
uvicorn backend.src.main:app --host 0.0.0.0 --port 8000 --reload
```

### 접속 URL
- **웹 대시보드**: http://localhost:8000
- **API 문서 (Swagger)**: http://localhost:8000/api/docs
- **Health Check**: http://localhost:8000/api/health

---

## 📖 API 엔드포인트

### 웹사이트 관리
| 메서드 | 엔드포인트 | 설명 |
|--------|------------|------|
| `GET` | `/api/websites` | 등록된 웹사이트 목록 조회 |
| `POST` | `/api/websites` | 새 웹사이트 등록 (HTTPS 전용) |
| `PUT` | `/api/websites/{id}` | 웹사이트 정보 수정 |
| `DELETE` | `/api/websites/{id}` | 웹사이트 삭제 |
| `POST` | `/api/websites/{id}/ssl-check` | 특정 웹사이트 SSL 수동 체크 |

### SSL 모니터링
| 메서드 | 엔드포인트 | 설명 |
|--------|------------|------|
| `GET` | `/api/ssl/status` | SSL 상태 요약 (총 개수, 만료 임박 등) |
| `GET` | `/api/ssl/certificates` | 모든 인증서 상세 정보 조회 |
| `POST` | `/api/ssl/quick-check` | 등록되지 않은 URL의 빠른 SSL 체크 |
| `POST` | `/api/ssl/check-all` | 모든 활성 웹사이트 SSL 일괄 체크 |

### 설정 관리
| 메서드 | 엔드포인트 | 설명 |
|--------|------------|------|
| `GET` | `/api/settings` | 현재 시스템 설정 조회 |
| `PUT` | `/api/settings` | 설정 업데이트 (재시작 불필요) |

### 알림
| 메서드 | 엔드포인트 | 설명 |
|--------|------------|------|
| `POST` | `/api/notifications/test` | 테스트 알림 발송 |
| `POST` | `/api/notifications/send` | 만료 임박 인증서 알림 발송 |

### 스케줄러 & 시스템
| 메서드 | 엔드포인트 | 설명 |
|--------|------------|------|
| `GET` | `/api/tasks/scheduler/status` | 스케줄러 상태 및 다음 실행 시간 |
| `POST` | `/api/tasks/scheduler/trigger` | 수동으로 스케줄 작업 실행 |
| `GET` | `/api/health` | 시스템 헬스체크 |

---

## ⚙️ 환경 설정

### .env 파일 예시

```env
# 데이터베이스
DATABASE_URL=sqlite:///./ssl_checker.db
# 운영환경: postgresql://user:password@localhost:5432/ssl_checker

# FastAPI 설정
APP_NAME=SSL Certificate Monitor
APP_VERSION=1.0.0
DEBUG=true
LOG_LEVEL=info

# Teams 알림 설정
TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/your-webhook-url
NOTIFICATION_ENABLED=true
NOTIFICATION_DAYS_BEFORE=30,7,1  # 만료 30, 7, 1일 이하 알림
NOTIFICATION_LANGUAGE=ko          # 알림 언어 (ko/en)
DASHBOARD_URL=https://ssl-checker.example.com  # 대시보드 링크

# 스케줄러 설정
ENABLE_SCHEDULER=true
SSL_CHECK_CRON=0 9 * * 1  # 매주 월요일 오전 9시

# SSL 체크 설정
SSL_TIMEOUT_SECONDS=10
MAX_CONCURRENT_CHECKS=5

# 보안
SECRET_KEY=your-secret-key-here
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

### 알림 설정 방법

#### 1. Teams 웹훅 URL 생성

**방법 1: Incoming Webhook (기본)**
1. Teams 채널 → **커넥터** → **Incoming Webhook** 추가
2. 웹훅 이름 설정 후 URL 복사
3. `.env` 파일의 `TEAMS_WEBHOOK_URL`에 붙여넣기

**방법 2: Power Automate (고급)**
1. [Power Automate](https://flow.microsoft.com) 접속
2. "HTTP 요청을 받는 경우" 트리거로 새 흐름 생성
3. Teams 메시지 전송 액션 추가
4. HTTP POST URL을 `TEAMS_WEBHOOK_URL`에 설정

#### 2. 알림 발송 일수 설정

> **중요**: 2025-10-17 기준, 알림 로직이 **"이하 방식"**으로 변경되었습니다.

```env
# 예: 만료까지 30일 이하인 인증서 모두 알림
NOTIFICATION_DAYS_BEFORE=30,7,1
```

**동작 방식**:
- `30`: 만료까지 **30일 이하**인 모든 인증서에 알림 발송
- `7`: 만료까지 **7일 이하**인 모든 인증서에 알림 발송
- `1`: 만료까지 **1일 이하**인 모든 인증서에 알림 발송

**변경 내역**:
- **이전**: 정확히 30일, 7일, 1일인 경우만 알림
- **현재**: 30일 이하, 7일 이하, 1일 이하 **모두** 알림

#### 3. 동적 설정 변경 (API 사용)

재시작 없이 설정을 변경할 수 있습니다.

```bash
# 현재 설정 조회
curl http://localhost:8000/api/settings

# 설정 업데이트
curl -X PUT http://localhost:8000/api/settings \
  -H "Content-Type: application/json" \
  -d '{
    "webhook_url": "https://outlook.office.com/webhook/...",
    "notification_enabled": true,
    "notification_days_before": "30,14,7,3,1",
    "notification_language": "ko",
    "dashboard_url": "https://ssl-checker.example.com"
  }'
```

#### 4. 알림 테스트

```bash
# API를 통한 테스트 알림
curl -X POST http://localhost:8000/api/notifications/test

# CLI를 통한 테스트
python -m backend.src.lib.notification_service test
```

---

## 🛠️ 개발

### 핵심 명령어

```bash
# 개발 서버 실행
uvicorn backend.src.main:app --reload

# 코드 포맷팅
black backend/src tests/
ruff check backend/src tests/ --fix

# 타입 체크
mypy backend/src

# 테스트 실행
pytest tests/ -v

# 커버리지 포함 테스트
pytest tests/ --cov=backend.src --cov-report=html

# 데이터베이스 마이그레이션
alembic revision --autogenerate -m "description"
alembic upgrade head
```

### 프로젝트 구조

```
cheking-ssl/
├── backend/
│   └── src/
│       ├── lib/                    # 핵심 라이브러리 (독립 실행 가능)
│       │   ├── ssl_checker.py      # SSL 인증서 체크 로직
│       │   ├── website_manager.py  # 웹사이트 CRUD 관리
│       │   ├── notification_service.py  # Teams 알림 발송
│       │   └── settings_manager.py # 설정 관리
│       ├── models/                 # SQLAlchemy ORM 모델
│       │   ├── website.py          # Website 엔티티
│       │   ├── ssl_certificate.py  # SSLCertificate 엔티티
│       │   └── settings.py         # Settings 엔티티
│       ├── services/               # 비즈니스 서비스 계층
│       │   ├── website_service.py  # 웹사이트 + SSL 통합
│       │   ├── ssl_service.py      # SSL 관련 서비스
│       │   └── notification_service.py  # 알림 서비스
│       ├── api/                    # FastAPI 라우터
│       │   ├── websites.py         # 웹사이트 API
│       │   ├── ssl.py              # SSL API
│       │   ├── settings.py         # 설정 API
│       │   ├── tasks.py            # 스케줄러 API
│       │   └── health.py           # Health Check
│       ├── scheduler.py            # APScheduler 스케줄링
│       ├── background.py           # 백그라운드 작업
│       ├── database.py             # DB 연결 및 세션 관리
│       └── main.py                 # FastAPI 앱 진입점
├── frontend/                       # 웹 UI (정적 파일)
├── tests/                          # 테스트 코드
│   ├── unit/                       # 단위 테스트
│   ├── integration/                # 통합 테스트
│   └── contract/                   # API 계약 테스트
├── deployment/                     # 배포 설정
│   ├── docker/                     # Docker Compose
│   └── k8s/                        # Kubernetes
├── .env.example                    # 환경 변수 예시
├── pyproject.toml                  # Python 프로젝트 설정
└── README.md
```

### Architecture: Library-First Pattern

이 프로젝트는 **Library-First Architecture**를 따릅니다:

1. **Library Layer** (`backend/src/lib/`)
   - 핵심 비즈니스 로직을 독립적인 라이브러리로 구현
   - 각 라이브러리는 CLI 인터페이스 제공 (독립 실행 가능)
   - 외부 의존성 최소화 (테스트 용이)

2. **Service Layer** (`backend/src/services/`)
   - 라이브러리들을 조합하여 복합 비즈니스 로직 처리
   - 트랜잭션 관리 및 오케스트레이션

3. **API Layer** (`backend/src/api/`)
   - 얇은 웹 인터페이스 레이어
   - 요청/응답 변환 및 HTTP 처리만 담당

---

## 🐳 배포

### Docker

```bash
# 개발 환경
docker-compose -f deployment/docker/docker-compose.dev.yml up

# 운영 환경
docker-compose -f deployment/docker/docker-compose.prod.yml up -d
```

### Kubernetes

```bash
# 네임스페이스 생성
kubectl create namespace ssl-monitor

# 배포
kubectl apply -f deployment/k8s/

# 상태 확인
kubectl get pods -n ssl-monitor
```

---

## 🔍 주요 특징

### 1. 엄격한 URL 검증
- **HTTPS 전용**: HTTP는 거부
- **루트 도메인만 허용**: 경로 포함 불가
- **포트 번호 허용**: `https://example.com:8443` 가능

### 2. 비동기 SSL 체크
- **동시 체크 제한**: 최대 5개 사이트 동시 처리 (설정 가능)
- **타임아웃**: 10초 (설정 가능)
- **재시도 로직**: 네트워크 오류 시 자동 재시도

### 3. 알림 로직 (2025-10-17 업데이트)
- **"이하" 방식**: 설정된 일수 **이하**인 모든 인증서에 알림 발송
- **중복 방지**: 동일 인증서에 대해 하루 1회만 알림
- **다국어 지원**: 한국어/영어 메시지 템플릿

### 4. 스케줄링
- **Cron 기반**: 유연한 일정 설정 가능
- **기본값**: 매주 월요일 오전 9시 SSL 체크 및 알림
- **수동 트리거**: API를 통한 즉시 실행 가능

---

## 📚 CLI 도구

각 라이브러리는 독립 실행 가능한 CLI를 제공합니다.

### SSL Checker

```bash
# 단일 URL 체크
python -m backend.src.lib.ssl_checker check https://example.com

# 복수 URL 체크
python -m backend.src.lib.ssl_checker batch https://google.com https://github.com
```

### Website Manager

```bash
# 웹사이트 추가
python -m backend.src.lib.website_manager add https://example.com "My Site"

# 웹사이트 목록
python -m backend.src.lib.website_manager list

# 웹사이트 삭제
python -m backend.src.lib.website_manager delete <website-id>
```

### Notification Service

```bash
# 테스트 알림 발송
python -m backend.src.lib.notification_service test

# 만료 임박 알림 발송
python -m backend.src.lib.notification_service send
```

---

## 🧪 테스트

### 테스트 구조

- **Unit Tests** (`tests/unit/`): 개별 함수/클래스 테스트
- **Integration Tests** (`tests/integration/`): 전체 워크플로우 테스트
- **Contract Tests** (`tests/contract/`): API 스펙 검증

### 테스트 실행

```bash
# 전체 테스트
pytest tests/ -v

# 특정 카테고리
pytest tests/unit/ -v
pytest tests/integration/ -v

# 특정 테스트 파일
pytest tests/integration/test_add_website_flow.py -v

# 커버리지 리포트
pytest tests/ --cov=backend.src --cov-report=html
open htmlcov/index.html
```

---

## 🔒 보안 고려사항

- **HTTPS 전용**: SSL 인증서 체크는 HTTPS만 지원
- **Webhook URL 검증**: Teams 웹훅 URL은 환경 변수로 안전하게 관리
- **SQL Injection 방지**: SQLAlchemy ORM 사용으로 기본 방어
- **비밀키 관리**: `.env` 파일은 절대 커밋하지 않음 (`.gitignore` 포함)

---

## 📄 라이센스

MIT License - 자세한 내용은 [LICENSE](LICENSE) 파일 참조

---

## 🤝 기여

기여는 언제나 환영합니다! 다음 절차를 따라주세요:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📞 문의

프로젝트 관련 문의는 Issue를 통해 남겨주세요.
