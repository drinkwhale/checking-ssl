# 작업 목록: SSL Certificate Monitoring Dashboard

**입력**: `/specs/001-ssl/`에서 설계 문서 로드
**필수 조건**: plan.md (✅), data-model.md (✅)

## 실행 흐름 (main)
```
1. 기능 디렉토리에서 plan.md 로드 ✅
   → 기술 스택: Python 3.11+, FastAPI, SQLAlchemy, APScheduler
   → 구조: 웹 앱 (backend/, frontend/, deployment/)
2. 선택적 설계 문서 로드 ✅:
   → data-model.md: Website, SSLCertificate 엔티티
   → contracts/: 없음 (API 스펙은 계획에서 추론)
   → research.md: 없음
3. 카테고리별 작업 생성 ✅:
   → 설정: 프로젝트 구조, 의존성, Docker
   → 테스트: 사용자 스토리 기반 통합 테스트
   → 핵심: 2개 모델, 3개 서비스, 3개 CLI 라이브러리
   → 통합: 데이터베이스, 스케줄러, API 엔드포인트
   → 마무리: 단위 테스트, 문서, K8s 배포
4. 작업 규칙 적용 ✅:
   → 다른 파일 = [P]로 병렬 표시
   → 같은 파일 = 순차 (no [P])
   → 구현 전 테스트 (TDD)
5. 작업 순차 번호 부여: T001-T025
6. 의존성 그래프 매핑 완료
7. 병렬 실행 예제 제공
8. 검증: ✅ 모든 요구사항 커버
```

## 형식: `[ID] [P?] 설명`
- **[P]**: 병렬 실행 가능 (다른 파일, 의존성 없음)
- 웹 앱 구조 기준 파일 경로: backend/src/, frontend/src/

## 단계 3.1: 설정 & 인프라

- [ ] T001 웹 앱 프로젝트 구조 생성: backend/src/{models,services,api,lib}/, frontend/src/, deployment/{docker,k8s}/, tests/{integration,unit}/
- [ ] T002 Python 백엔드 초기화: requirements.txt (FastAPI, SQLAlchemy, APScheduler, cryptography, httpx, pytest)
- [ ] T003 [P] 개발 도구 설정: .env.example, pyproject.toml (black, ruff, mypy), .gitignore 업데이트
- [ ] T004 [P] Docker 설정: backend/Dockerfile (Python 3.11-alpine), docker-compose.dev.yml (PostgreSQL 포함)

## 단계 3.2: 테스트 우선 (TDD) ⚠️ 3.3 이전에 반드시 완료
**중요: 이 테스트들은 반드시 작성되어야 하고 구현 전에 실패해야 함**

### 통합 테스트 [P] - 사용자 스토리 검증
- [ ] T005 [P] 웹사이트 추가 및 SSL 체크 통합 테스트 (tests/integration/test_add_website_flow.py)
- [ ] T006 [P] 웹사이트 삭제 및 정리 통합 테스트 (tests/integration/test_delete_website_flow.py)
- [ ] T007 [P] 만료 인증서 Teams 알림 통합 테스트 (tests/integration/test_teams_notification.py)
- [ ] T008 [P] 주간 스케줄러 SSL 일괄 체크 통합 테스트 (tests/integration/test_weekly_scheduler.py)

## 단계 3.3: 핵심 구현 (테스트 실패 후에만)

### 데이터 모델 [P] - 데이터베이스 엔티티
- [ ] T009 [P] Website 모델 (backend/src/models/website.py) - SQLAlchemy, URL 검증, 유니크 제약
- [ ] T010 [P] SSLCertificate 모델 (backend/src/models/ssl_certificate.py) - Website 외래키, 인증서 필드
- [ ] T011 데이터베이스 설정 (backend/src/database.py) - SQLAlchemy 엔진, 세션 관리, 마이그레이션

### 핵심 라이브러리 [P] - 비즈니스 로직
- [ ] T012 [P] SSL 체커 라이브러리 (backend/src/lib/ssl_checker.py) - CLI 포함, 인증서 체크/정보 추출/오류 처리
- [ ] T013 [P] 웹사이트 관리자 라이브러리 (backend/src/lib/website_manager.py) - CLI 포함, CRUD 작업/검증
- [ ] T014 [P] Teams 알림 라이브러리 (backend/src/lib/notification_service.py) - CLI 포함, 웹훅 통합/메시지 포맷

### 서비스 계층 - 비즈니스 작업
- [ ] T015 웹사이트 서비스 (backend/src/services/website_service.py) - 비즈니스 로직, SSL 체크 통합
- [ ] T016 SSL 모니터링 서비스 (backend/src/services/ssl_service.py) - 일괄 체크, 만료 감지
- [ ] T017 알림 서비스 (backend/src/services/notification_service.py) - Teams 통합, 알림 로직

## 단계 3.4: API & 통합

### API 엔드포인트 - REST 구현
- [ ] T018 웹사이트 관리 엔드포인트 (backend/src/api/websites.py) - CRUD 작업, 검증
- [ ] T019 SSL 모니터링 엔드포인트 (backend/src/api/ssl.py) - 상태 조회, 수동 체크, 히스토리
- [ ] T020 헬스체크 엔드포인트 (backend/src/api/health.py) - liveness, readiness, metrics
- [ ] T021 FastAPI 앱 설정 (backend/src/main.py) - 라우터 등록, 미들웨어, CORS

### 스케줄러 & 백그라운드 작업
- [ ] T022 APScheduler 설정 (backend/src/scheduler.py) - 주간 SSL 체크, 작업 관리
- [ ] T023 백그라운드 작업 실행기 (backend/src/background.py) - 비동기 작업 실행, 오류 처리

## 단계 3.5: 프론트엔드 & 배포

### 프론트엔드 대시보드 [P]
- [ ] T024 [P] HTML 대시보드 (frontend/src/index.html) - 웹사이트 목록, SSL 상태 표시, 폼
- [ ] T025 [P] JavaScript API 클라이언트 (frontend/src/js/api.js) - REST 호출, 오류 처리, UI 업데이트

## 의존성

### 중요 의존성 (TDD)
- **테스트 (T005-T008) 반드시 구현 (T009-T025) 이전에 완료**
- T003, T004는 T005-T008 이전 완료 (테스트 환경 설정)

### 구현 의존성
- T009, T010 (모델) → T011 (데이터베이스) → T015, T016 (서비스)
- T012, T013, T014 (라이브러리)는 모델과 병렬 실행 가능
- T015, T016, T017 (서비스) → T018, T019, T020 (API 엔드포인트)
- T018-T021 (API) → T022, T023 (스케줄러)
- T024-T025 (프론트엔드)는 백엔드 T018-T023과 병렬 실행 가능

### 병렬 실행 안전 (의존성 없음)
- T003, T004는 T001, T002와 함께 실행 가능
- T005-T008은 모두 함께 실행 가능 (설정 후)
- T009, T010은 함께 실행 가능 (다른 파일)
- T012, T013, T014는 함께 실행 가능 (다른 라이브러리)
- T024, T025는 함께 실행 가능 (다른 프론트엔드 파일)

## 병렬 실행 예제

### 설정 단계 (병렬)
```bash
# T003-T004를 T001-T002 후 함께 실행:
Task: "개발 도구 설정: .env.example, pyproject.toml, .gitignore"
Task: "Docker 설정: Dockerfile, docker-compose.dev.yml (PostgreSQL 포함)"
```

### 테스트 단계 (모든 병렬)
```bash
# T005-T008을 함께 실행:
Task: "웹사이트 추가 및 SSL 체크 통합 테스트 (tests/integration/test_add_website_flow.py)"
Task: "웹사이트 삭제 및 정리 통합 테스트 (tests/integration/test_delete_website_flow.py)"
Task: "만료 인증서 Teams 알림 통합 테스트 (tests/integration/test_teams_notification.py)"
Task: "주간 스케줄러 SSL 일괄 체크 통합 테스트 (tests/integration/test_weekly_scheduler.py)"
```

### 핵심 라이브러리 (모든 병렬)
```bash
# T012-T014를 함께 실행:
Task: "SSL 체커 라이브러리 (backend/src/lib/ssl_checker.py) - CLI 포함"
Task: "웹사이트 관리자 라이브러리 (backend/src/lib/website_manager.py) - CLI 포함"
Task: "Teams 알림 라이브러리 (backend/src/lib/notification_service.py) - CLI 포함"
```

### 프론트엔드 (모든 병렬)
```bash
# T024-T025를 함께 실행:
Task: "HTML 대시보드 (frontend/src/index.html)"
Task: "JavaScript API 클라이언트 (frontend/src/js/api.js)"
```

## 작업 생성 규칙 적용

1. **데이터 모델에서**: ✅
   - Website 엔티티 → T009, T013
   - SSLCertificate 엔티티 → T010, T012
   - 관계 → T011, T015, T016

2. **사용자 스토리에서**: ✅
   - 웹사이트 추가 → T005
   - 웹사이트 삭제 → T006
   - Teams 알림 → T007
   - 주간 스케줄링 → T008

3. **아키텍처에서**: ✅
   - 라이브러리 우선 접근법 → T012, T013, T014 (CLI 포함)
   - 웹 앱 구조 → backend/frontend 분리
   - API 우선 설계 → T018, T019, T020

## 검증 체크리스트 ✅

- [x] 모든 엔티티에 모델 작업이 있음 (T009-T010)
- [x] 모든 테스트가 구현 전에 있음 (T005-T008 → T009-T025)
- [x] 병렬 작업이 진짜 독립적임 (다른 파일/컴포넌트)
- [x] 각 작업이 정확한 파일 경로를 명시함
- [x] [P] 작업끼리 같은 파일을 수정하지 않음
- [x] TDD 사이클 강제 (구현 전 실패하는 테스트 필요)
- [x] 라이브러리에 CLI 컴포넌트 포함
- [x] 통합 테스트가 plan.md의 사용자 시나리오 커버

## 참고사항

- **TDD 강제**: T005-T008 테스트가 T009+ 시작 전에 실패해야 함
- **커밋 전략**: 각 작업 완료 후 커밋
- **병렬 안전성**: [P] 작업들이 다른 파일을 수정하는지 검증됨
- **구조적 준수**: 모든 라이브러리 (T012-T014)에 CLI 인터페이스 포함
- **성능 목표**: <5초 대시보드 로딩 (통합 테스트에서 검증)
- **Teams 통합**: T007에서 실제 웹훅 테스트, 단위 테스트에서는 모킹