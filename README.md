# SSL Certificate Monitoring Dashboard

웹사이트 SSL 인증서 모니터링 및 만료 알림 시스템입니다.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ 주요 기능

- 🔒 **SSL 인증서 모니터링**: 웹사이트 SSL 인증서 자동 체크 및 상태 추적
- ⏰ **자동화된 스케줄링**: 주간 SSL 체크 및 만료 알림 자동화
- 📊 **실시간 대시보드**: 웹 기반 모니터링 및 관리 인터페이스
- 🔔 **Teams 알림**: Microsoft Teams 웹훅을 통한 만료 임박 알림
- 📈 **통계 및 분석**: SSL 인증서 상태 분포 및 만료 예정 통계
- 🎯 **일괄 작업**: 다중 웹사이트 SSL 인증서 일괄 체크
- 📱 **반응형 UI**: 모바일부터 데스크톱까지 완벽 대응

## 🏗️ 아키텍처

### Library-First Architecture
```
backend/src/
├── lib/                    # 핵심 비즈니스 로직 라이브러리
│   ├── ssl_checker.py      # SSL 인증서 체크 엔진
│   ├── website_manager.py  # 웹사이트 관리
│   └── notification_service.py # Teams 알림 서비스
├── services/              # 비즈니스 서비스 계층
├── api/                   # REST API 엔드포인트
├── models/                # 데이터베이스 모델
├── scheduler.py           # APScheduler 작업 스케줄링
└── background.py          # 백그라운드 작업 실행기
```

### 기술 스택
- **Backend**: Python 3.11+ (FastAPI, SQLAlchemy, APScheduler)
- **Frontend**: 바닐라 JavaScript + Tailwind CSS
- **Database**: PostgreSQL (운영) / SQLite (개발)
- **Deployment**: Docker + Kubernetes

## 🚀 빠른 시작

### 필수 요구사항
- Python 3.11+
- uv (Python 패키지 관리자)

### 설치 및 실행

1. **저장소 클론**
   ```bash
   git clone <repository-url>
   cd ssl-certificate-monitor
   ```

2. **의존성 설치**
   ```bash
   # 기본 의존성
   uv sync

   # 개발 의존성 포함
   uv sync --extra dev
   ```

3. **환경 변수 설정**
   ```bash
   cp .env.example .env
   # .env 파일을 편집하여 필요한 설정값 입력
   ```

4. **데이터베이스 초기화**
   ```bash
   python -c "from backend.src.database import init_db; import asyncio; asyncio.run(init_db())"
   ```

5. **개발 서버 실행**
   ```bash
   # FastAPI 서버 시작
   uvicorn backend.src.main:app --host 0.0.0.0 --port 8000 --reload
   ```

6. **웹 대시보드 접근**
   - http://localhost:8000 - 메인 대시보드
   - http://localhost:8000/api/docs - API 문서

## 📖 API 문서

### 주요 엔드포인트

#### 웹사이트 관리
- `POST /api/websites` - 웹사이트 추가
- `GET /api/websites` - 웹사이트 목록 조회
- `PUT /api/websites/{id}` - 웹사이트 수정
- `DELETE /api/websites/{id}` - 웹사이트 삭제
- `POST /api/websites/{id}/ssl-check` - 수동 SSL 체크

#### SSL 모니터링
- `GET /api/ssl/status` - SSL 상태 요약
- `GET /api/ssl/certificates` - SSL 인증서 목록
- `GET /api/ssl/history/{website_id}` - SSL 히스토리
- `POST /api/ssl/quick-check` - 빠른 SSL 체크

#### 작업 관리
- `GET /api/tasks/scheduler/status` - 스케줄러 상태
- `POST /api/tasks/background/ssl-check` - SSL 체크 작업 제출
- `GET /api/tasks/background/tasks` - 백그라운드 작업 목록

#### 헬스체크
- `GET /api/health` - 전체 시스템 상태
- `GET /api/health/liveness` - 라이브니스 체크
- `GET /api/health/readiness` - 레디니스 체크

## ⚙️ 환경 설정

### 필수 환경 변수

```env
# 데이터베이스 설정
DATABASE_URL=postgresql://user:password@localhost/ssl_monitor

# Teams 웹훅 (선택사항)
TEAMS_WEBHOOK_URL=https://your-organization.webhook.office.com/...

# SSL 체크 설정
SSL_TIMEOUT_SECONDS=10
MAX_CONCURRENT_CHECKS=5

# 스케줄러 설정 (선택사항)
SCHEDULER_WEEKLY_DAY=1    # 0=월요일, 6=일요일
SCHEDULER_WEEKLY_TIME=09:00
```

## 🛠️ 개발

### 개발 명령어

```bash
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
alembic revision --autogenerate -m "migration description"
alembic upgrade head
```

### 프로젝트 구조

```
ssl-certificate-monitor/
├── backend/                # 백엔드 애플리케이션
│   ├── src/
│   │   ├── api/           # REST API 엔드포인트
│   │   ├── lib/           # 핵심 라이브러리
│   │   ├── models/        # 데이터베이스 모델
│   │   ├── services/      # 비즈니스 서비스
│   │   ├── main.py        # FastAPI 애플리케이션
│   │   ├── database.py    # 데이터베이스 설정
│   │   ├── scheduler.py   # 작업 스케줄러
│   │   └── background.py  # 백그라운드 작업
│   └── requirements.txt
├── frontend/              # 프론트엔드 대시보드
│   └── src/
│       ├── index.html     # 메인 대시보드
│       └── js/
│           └── api.js     # API 클라이언트
├── tests/                 # 테스트 코드
│   ├── unit/             # 단위 테스트
│   ├── integration/      # 통합 테스트
│   └── contract/         # 계약 테스트
├── deployment/           # 배포 설정
│   ├── docker/          # Docker 설정
│   └── k8s/             # Kubernetes 매니페스트
└── specs/               # 기능 명세서
```

## 📋 테스트

### 테스트 실행
```bash
# 모든 테스트
pytest tests/ -v

# 단위 테스트만
pytest tests/unit/ -v

# 통합 테스트만
pytest tests/integration/ -v

# 특정 테스트 파일
pytest tests/integration/test_add_website_flow.py -v

# 커버리지 리포트
pytest tests/ --cov=backend.src --cov-report=html
```

### 테스트 범위
- **Unit Tests**: 개별 라이브러리 및 함수 테스트
- **Integration Tests**: 전체 워크플로우 테스트
- **Contract Tests**: API 스펙 계약 검증

## 🐳 Docker 배포

### 개발 환경
```bash
# Docker Compose로 전체 스택 실행
docker-compose -f deployment/docker/docker-compose.dev.yml up
```

### 운영 환경
```bash
# Kubernetes 배포
kubectl apply -f deployment/k8s/
```

## 🔧 CLI 도구

각 라이브러리는 독립적인 CLI 인터페이스를 제공합니다:

```bash
# SSL 체크
python -m backend.src.lib.ssl_checker https://example.com

# 웹사이트 관리
python -m backend.src.lib.website_manager list

# 알림 발송
python -m backend.src.lib.notification_service test
```

## 📊 모니터링

### 스케줄러 작업
- **주간 SSL 체크**: 매주 월요일 09:00 (한국 시간)
- **만료 알림**: 24시간마다 (30, 14, 7, 3, 1일 전 알림)
- **헬스체크**: 1시간마다

### 메트릭
- SSL 인증서 상태 분포
- 만료 임박 통계
- 시스템 리소스 사용량
- 백그라운드 작업 상태

## 🤝 기여하기

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 라이센스

이 프로젝트는 MIT 라이센스 하에 배포됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 🆘 지원

- **이슈 리포트**: GitHub Issues를 통해 버그 리포트 및 기능 요청
- **문서**: [API Documentation](http://localhost:8000/api/docs)
- **예제**: `examples/` 디렉토리 참조

## 🎯 로드맵

- [ ] SAML/OAuth 인증 지원
- [ ] 다중 알림 채널 (Slack, Email)
- [ ] 인증서 자동 갱신 알림
- [ ] 대시보드 차트 및 분석 기능
- [ ] API 키 기반 인증
- [ ] 웹훅 이벤트 시스템

---

**SSL Certificate Monitoring Dashboard** - 안전하고 신뢰할 수 있는 웹 서비스를 위한 SSL 인증서 관리 솔루션