# Frontend CLAUDE.md

## 모듈 개요
SSL Certificate Monitor의 프론트엔드 - 바닐라 JavaScript 기반 대시보드 웹 애플리케이션입니다.

## 기술 스택
- **기본**: HTML5, CSS3, 바닐라 JavaScript (ES6+)
- **UI 프레임워크**: Tailwind CSS (CDN)
- **아이콘**: Heroicons (SVG 직접 구현)
- **차트**: Chart.js (CDN)
- **API 통신**: Fetch API + 커스텀 API 클라이언트

## 디렉토리 구조
```
src/
├── index.html          # 메인 대시보드 페이지
└── js/
    └── api.js          # API 클라이언트 및 유틸리티
```

## 핵심 컴포넌트

### 1. API 클라이언트 (`js/api.js`)
백엔드 API와의 통신을 담당하는 완전한 REST 클라이언트:

#### 주요 클래스
- **`SSLMonitorAPI`**: 메인 API 클라이언트
- **`WebsitesAPI`**: 웹사이트 관련 API
- **`SSLAPI`**: SSL 인증서 관련 API
- **`HealthAPI`**: 헬스체크 API
- **`TasksAPI`**: 백그라운드 작업 API
- **`APIUtils`**: 유틸리티 함수들

#### 사용 예시
```javascript
// API 초기화
const api = new SSLMonitorAPI();
api.init();

// 웹사이트 목록 조회
const websites = await api.websites.list({ active_only: true });

// SSL 상태 요약
const summary = await api.ssl.getStatusSummary();

// 웹사이트 추가
await api.websites.create({
    url: "https://example.com",
    name: "My Website",
    auto_check_ssl: true
});
```

### 2. 대시보드 UI (`index.html`)
반응형 대시보드 인터페이스:

#### 주요 섹션
- **상태 요약 카드**: 전체/유효/만료/임박 인증서 통계
- **웹사이트 목록**: 실시간 SSL 상태 표시
- **필터링**: 상태별, 활성 사이트 필터
- **모달**: 웹사이트 추가, 상세 정보 표시
- **토스트 알림**: 사용자 피드백

## UI/UX 가이드라인

### 상태 표시 색상
```css
.status-valid    { /* 녹색: 유효한 인증서 */ }
.status-expired  { /* 빨간색: 만료된 인증서 */ }
.status-invalid  { /* 노란색: 오류 상태 */ }
.status-unknown  { /* 회색: 확인 필요 */ }
```

### 만료 경고 시스템
- **7일 이내**: 빨간색 경고 + 깜박임 애니메이션
- **30일 이내**: 노란색 주의
- **그 외**: 일반 표시

### 애니메이션
- **로딩**: 회전 애니메이션 (`loading-spinner`)
- **페이드인**: 항목 추가 시 (`fade-in`)
- **만료 임박**: 펄스 애니메이션 (`expiring-soon`)

## 주요 기능

### 실시간 대시보드
- 자동 새로고침 (5분 간격)
- SSL 상태 요약 통계
- 만료 임박 인증서 하이라이트

### 웹사이트 관리
- 웹사이트 추가/삭제
- 개별/일괄 SSL 체크
- 상세 정보 모달

### 알림 및 피드백
- 토스트 알림 시스템
- 오류 처리 및 사용자 피드백
- 로딩 상태 표시

## 개발 가이드

### 이벤트 리스너 패턴
```javascript
// DOM 로드 완료 후 초기화
document.addEventListener('DOMContentLoaded', function() {
    // API 초기화
    window.SSLMonitorAPI.init();

    // 이벤트 리스너 설정
    setupEventListeners();

    // 초기 데이터 로드
    loadDashboardData();
});
```

### 오류 처리
```javascript
try {
    await api.websites.create(data);
    showToast('성공적으로 추가되었습니다', 'success');
} catch (error) {
    console.error('오류:', error);
    showToast('작업에 실패했습니다', 'error');
}
```

### 모달 관리
```javascript
// 모달 열기
function openAddWebsiteModal() {
    document.getElementById('add-website-modal').classList.remove('hidden');
}

// 모달 닫기
function closeAddWebsiteModal() {
    document.getElementById('add-website-modal').classList.add('hidden');
    document.getElementById('add-website-form').reset();
}
```

## 성능 최적화

### 데이터 로딩
- 비동기 API 호출
- 로딩 상태 표시
- 오류 시 재시도 로직

### UI 렌더링
- 동적 DOM 생성/업데이트
- 이벤트 위임 패턴
- 메모리 누수 방지

### 캐싱 전략
- LocalStorage 활용 (APIUtils.storage)
- API 응답 캐싱
- 정적 리소스 캐싱

## 배포 고려사항

### 정적 파일 서빙
백엔드 FastAPI에서 자동으로 서빙:
- `/` → `index.html`
- `/js/*` → JavaScript 파일
- `/css/*` → CSS 파일 (미래 확장용)

### CORS 설정
개발/운영 환경별 CORS 정책:
```javascript
// 개발: localhost:3000, localhost:8080
// 운영: ssl-monitor.example.com
```

### 브라우저 호환성
- ES6+ 문법 사용
- Fetch API 필수
- 모던 브라우저 타겟 (IE 미지원)

## 확장 가능성

### 차트 통계 (예정)
Chart.js를 활용한 SSL 인증서 통계 시각화:
- 만료 임박 차트
- 월별 갱신 현황
- 도메인별 상태 분포

### PWA 지원 (예정)
- Service Worker
- 오프라인 지원
- 푸시 알림

### 테마 지원 (예정)
- 다크/라이트 모드
- 사용자 설정 저장