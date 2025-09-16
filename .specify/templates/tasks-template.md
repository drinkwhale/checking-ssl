# 작업 목록: [기능명]

**입력**: `/specs/[###-feature-name]/`에서 설계 문서 로드
**필수 조건**: plan.md (필수), research.md, data-model.md, contracts/

## 실행 흐름 (main)
```
1. 기능 디렉토리에서 plan.md 로드
   → 없으면: ERROR "구현 계획을 찾을 수 없음"
   → 추출: 기술 스택, 라이브러리, 구조
2. 선택적 설계 문서 로드:
   → data-model.md: 엔티티 추출 → 모델 작업
   → contracts/: 각 파일 → 계약 테스트 작업
   → research.md: 결정사항 추출 → 설정 작업
3. 카테고리별 작업 생성:
   → 설정: 프로젝트 초기화, 의존성, 린팅
   → 테스트: 계약 테스트, 통합 테스트
   → 핵심: 모델, 서비스, CLI 명령
   → 통합: DB, 미들웨어, 로깅
   → 마무리: 단위 테스트, 성능, 문서
4. 작업 규칙 적용:
   → 다른 파일 = [P]로 병렬 표시
   → 같은 파일 = 순차 (no [P])
   → 구현 전 테스트 (TDD)
5. 작업 순차 번호 부여 (T001, T002...)
6. 의존성 그래프 생성
7. 병렬 실행 예제 생성
8. 작업 완전성 검증:
   → 모든 계약에 테스트가 있는가?
   → 모든 엔티티에 모델이 있는가?
   → 모든 엔드포인트가 구현되었는가?
9. 반환: SUCCESS (실행 준비 완료)
```

## 형식: `[ID] [P?] 설명`
- **[P]**: 병렬 실행 가능 (다른 파일, 의존성 없음)
- 설명에 정확한 파일 경로 포함

## 경로 규칙
- **단일 프로젝트**: 저장소 루트에 `src/`, `tests/`
- **웹 앱**: `backend/src/`, `frontend/src/`
- **모바일**: `api/src/`, `ios/src/` 또는 `android/src/`
- 아래 경로는 단일 프로젝트 기준 - plan.md 구조에 따라 조정

## 단계 3.1: 설정
- [ ] T001 구현 계획에 따른 프로젝트 구조 생성
- [ ] T002 [언어] 프로젝트를 [프레임워크] 의존성으로 초기화
- [ ] T003 [P] 린팅 및 포맷팅 도구 설정

## 단계 3.2: 테스트 우선 (TDD) ⚠️ 3.3 이전에 반드시 완료
**중요: 이 테스트들은 반드시 작성되어야 하고 구현 전에 실패해야 함**
- [ ] T004 [P] POST /api/users 계약 테스트 (tests/contract/test_users_post.py)
- [ ] T005 [P] GET /api/users/{id} 계약 테스트 (tests/contract/test_users_get.py)
- [ ] T006 [P] 사용자 등록 통합 테스트 (tests/integration/test_registration.py)
- [ ] T007 [P] 인증 플로우 통합 테스트 (tests/integration/test_auth.py)

## 단계 3.3: 핵심 구현 (테스트 실패 후에만)
- [ ] T008 [P] User 모델 (src/models/user.py)
- [ ] T009 [P] UserService CRUD (src/services/user_service.py)
- [ ] T010 [P] CLI --create-user (src/cli/user_commands.py)
- [ ] T011 POST /api/users 엔드포인트
- [ ] T012 GET /api/users/{id} 엔드포인트
- [ ] T013 입력 검증
- [ ] T014 오류 처리 및 로깅

## 단계 3.4: 통합
- [ ] T015 UserService를 DB에 연결
- [ ] T016 인증 미들웨어
- [ ] T017 요청/응답 로깅
- [ ] T018 CORS 및 보안 헤더

## 단계 3.5: 마무리
- [ ] T019 [P] 검증용 단위 테스트 (tests/unit/test_validation.py)
- [ ] T020 성능 테스트 (<200ms)
- [ ] T021 [P] docs/api.md 업데이트
- [ ] T022 중복 제거
- [ ] T023 manual-testing.md 실행

## 의존성
- 테스트 (T004-T007) → 구현 (T008-T014) 이전
- T008이 T009, T015를 차단
- T016이 T018을 차단
- 구현 → 마무리 (T019-T023) 이전

## 병렬 실행 예제
```
# T004-T007을 함께 실행:
Task: "POST /api/users 계약 테스트 (tests/contract/test_users_post.py)"
Task: "GET /api/users/{id} 계약 테스트 (tests/contract/test_users_get.py)"
Task: "등록 통합 테스트 (tests/integration/test_registration.py)"
Task: "인증 통합 테스트 (tests/integration/test_auth.py)"
```

## 참고사항
- [P] 작업 = 다른 파일, 의존성 없음
- 구현 전 테스트 실패 확인
- 각 작업 후 커밋
- 피하기: 모호한 작업, 같은 파일 충돌

## 작업 생성 규칙
*main() 실행 중 적용됨*

1. **계약에서**:
   - 각 계약 파일 → 계약 테스트 작업 [P]
   - 각 엔드포인트 → 구현 작업

2. **데이터 모델에서**:
   - 각 엔티티 → 모델 생성 작업 [P]
   - 관계 → 서비스 레이어 작업

3. **사용자 스토리에서**:
   - 각 스토리 → 통합 테스트 [P]
   - 퀵스타트 시나리오 → 검증 작업

4. **순서**:
   - 설정 → 테스트 → 모델 → 서비스 → 엔드포인트 → 마무리
   - 의존성이 병렬 실행을 차단

## 검증 체크리스트
*GATE: main()에서 반환 전 확인*

- [ ] 모든 계약에 해당 테스트가 있음
- [ ] 모든 엔티티에 모델 작업이 있음
- [ ] 모든 테스트가 구현 전에 있음
- [ ] 병렬 작업이 진짜 독립적임
- [ ] 각 작업이 정확한 파일 경로를 명시함
- [ ] [P] 작업끼리 같은 파일을 수정하지 않음