-- SSL Checker 데이터베이스 초기화 스크립트

-- 확장 설치 (UUID 생성용)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 데이터베이스 설정
ALTER DATABASE ssl_checker SET timezone = 'Asia/Seoul';

-- 기본 사용자 권한 부여
GRANT ALL PRIVILEGES ON DATABASE ssl_checker TO ssl_user;