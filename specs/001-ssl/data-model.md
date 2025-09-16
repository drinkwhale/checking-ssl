# Data Model: SSL Certificate Monitoring

## Entity Relationship Overview

```
Website (1) -----> (N) SSLCertificate
    |
    |- id: UUID (PK)
    |- url: String (Unique)
    |- name: String (Optional display name)
    |- created_at: DateTime
    |- updated_at: DateTime
    |- is_active: Boolean

SSLCertificate
    |- id: UUID (PK)
    |- website_id: UUID (FK -> Website.id)
    |- issuer: String
    |- subject: String
    |- serial_number: String
    |- issued_date: DateTime
    |- expiry_date: DateTime
    |- fingerprint: String
    |- status: Enum (valid, invalid, expired, revoked)
    |- last_checked: DateTime
    |- created_at: DateTime
```

## Entity Specifications

### Website Entity
**Purpose**: 모니터링 대상 웹사이트 정보 관리

**Fields**:
- `id`: UUID primary key (자동 생성)
- `url`: HTTPS URL (unique constraint, not null)
- `name`: 표시명 (nullable, default: URL에서 추출)
- `created_at`: 생성 시간 (auto-generated)
- `updated_at`: 수정 시간 (auto-updated)
- `is_active`: 모니터링 활성화 여부 (default: true)

**Constraints**:
- URL은 https://로 시작해야 함
- URL은 시스템 내 유일해야 함
- name이 없으면 URL의 도메인을 기본값으로 사용

**Business Rules**:
- 삭제 시 관련 SSL 인증서 정보도 함께 삭제 (CASCADE)
- 비활성화된 웹사이트는 자동 체크에서 제외
- URL 변경 시 새 SSL 체크 트리거

### SSLCertificate Entity
**Purpose**: SSL 인증서 정보 및 상태 추적

**Fields**:
- `id`: UUID primary key (자동 생성)
- `website_id`: Website 외래키 (not null, cascade delete)
- `issuer`: 인증서 발급자 (CA 정보)
- `subject`: 인증서 주체 (도메인 정보)
- `serial_number`: 인증서 시리얼 번호
- `issued_date`: 발급 날짜
- `expiry_date`: 만료 날짜 (알림 기준)
- `fingerprint`: SHA-256 지문 (인증서 고유 식별)
- `status`: 인증서 상태 (enum)
- `last_checked`: 마지막 체크 시간
- `created_at`: 레코드 생성 시간

**Status Enum Values**:
- `valid`: 정상 인증서
- `invalid`: 유효하지 않은 인증서
- `expired`: 만료된 인증서
- `revoked`: 폐기된 인증서
- `unknown`: 상태 불명

**Constraints**:
- website_id는 존재하는 Website을 참조해야 함
- expiry_date는 issued_date보다 미래여야 함
- fingerprint는 고유해야 함 (같은 인증서 중복 방지)

**Business Rules**:
- 새 SSL 체크 시 기존 레코드 업데이트 또는 새 레코드 생성
- 만료 30일/7일/1일 전 알림 트리거
- 상태 변경 시 히스토리 로깅

## Database Indexing Strategy

### Primary Indexes
- `Website.id` (Primary Key)
- `SSLCertificate.id` (Primary Key)

### Foreign Key Indexes
- `SSLCertificate.website_id` (FK to Website)

### Business Logic Indexes
- `Website.url` (Unique, 빠른 URL 검색)
- `Website.is_active` (활성 사이트 필터링)
- `SSLCertificate.expiry_date` (만료 알림 쿼리 최적화)
- `SSLCertificate.status` (상태별 필터링)
- `SSLCertificate.last_checked` (배치 처리 최적화)

### Composite Indexes
- `(Website.is_active, SSLCertificate.expiry_date)` (활성 사이트 만료 체크)
- `(SSLCertificate.website_id, SSLCertificate.created_at)` (사이트별 히스토리)

## Data Validation Rules

### Website URL Validation
```python
# URL 형식 검증
- 반드시 https:// 로 시작
- 유효한 도메인 형식
- 포트 번호 허용 (예: https://example.com:8443)
- 경로 허용하지 않음 (루트 도메인만)

# 예제
✅ Valid: "https://google.com"
✅ Valid: "https://api.example.com:8443"
❌ Invalid: "http://example.com" (HTTP)
❌ Invalid: "https://example.com/path" (경로 포함)
❌ Invalid: "example.com" (프로토콜 없음)
```

### SSL Certificate Validation
```python
# 날짜 검증
- issued_date <= current_date <= expiry_date (정상 인증서인 경우)
- expiry_date > issued_date (논리적 일관성)

# 상태 검증
- expired: expiry_date < current_date
- valid: 정상적으로 체인 검증 완료
- invalid: 체인 검증 실패, 형식 오류 등
```

## Migration Strategy

### Initial Schema (V1)
1. Website 테이블 생성
2. SSLCertificate 테이블 생성
3. 외래키 제약조건 설정
4. 인덱스 생성

### Future Migrations
- V2: 알림 설정 테이블 추가 가능성
- V3: 인증서 히스토리 테이블 분리 고려
- V4: 다중 포트 지원 확장

## Test Data Examples

### Sample Website Records
```sql
INSERT INTO websites VALUES
  ('550e8400-e29b-41d4-a716-446655440000', 'https://google.com', 'Google', NOW(), NOW(), true),
  ('550e8400-e29b-41d4-a716-446655440001', 'https://github.com', 'GitHub', NOW(), NOW(), true),
  ('550e8400-e29b-41d4-a716-446655440002', 'https://expired.badssl.com', 'Expired Test', NOW(), NOW(), false);
```

### Sample SSLCertificate Records
```sql
INSERT INTO ssl_certificates VALUES
  ('660e8400-e29b-41d4-a716-446655440000', '550e8400-e29b-41d4-a716-446655440000',
   'Google Trust Services', 'google.com', 'ABC123...',
   '2024-01-01 00:00:00', '2024-12-31 23:59:59', 'sha256:XYZ...', 'valid', NOW(), NOW());
```