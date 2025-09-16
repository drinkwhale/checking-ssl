# Python 3.11-alpine 베이스 이미지 사용
FROM python:3.11-alpine

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치 (SSL 인증서 처리를 위해)
RUN apk add --no-cache \
    build-base \
    libffi-dev \
    openssl-dev \
    curl \
    && rm -rf /var/cache/apk/*

# Python 의존성 파일 복사
COPY requirements.txt .

# Python 의존성 설치
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY src/ ./src/

# 환경 변수 설정
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 헬스체크 추가
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# 포트 노출
EXPOSE 8000

# 애플리케이션 실행
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]