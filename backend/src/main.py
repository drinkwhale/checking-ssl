"""
FastAPI 메인 애플리케이션

SSL Certificate Monitoring Dashboard의 메인 웹 애플리케이션입니다.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from .database import init_db, close_db
from .api import websites, ssl, health


# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


# 애플리케이션 라이프사이클 관리
@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 시작/종료 시 실행되는 코드"""
    # 시작 시 실행
    logger.info("SSL Certificate Monitor 시작 중...")

    try:
        # 데이터베이스 초기화
        await init_db()
        logger.info("데이터베이스 초기화 완료")

        # 스케줄러 시작 (추후 구현)
        # await start_scheduler()
        # logger.info("스케줄러 시작 완료")

        yield

    finally:
        # 종료 시 실행
        logger.info("SSL Certificate Monitor 종료 중...")

        # 스케줄러 종료 (추후 구현)
        # await stop_scheduler()
        # logger.info("스케줄러 종료 완료")

        # 데이터베이스 연결 종료
        await close_db()
        logger.info("데이터베이스 연결 종료 완료")


# FastAPI 애플리케이션 생성
app = FastAPI(
    title="SSL Certificate Monitor",
    description="웹사이트 SSL 인증서 모니터링 및 알림 시스템",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan
)


# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # 개발용 프론트엔드
        "http://localhost:8080",  # 개발용 프론트엔드 대안
        "https://ssl-monitor.example.com",  # 프로덕션 도메인 (예시)
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# 신뢰할 수 있는 호스트 미들웨어
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "ssl-monitor.example.com",  # 프로덕션 도메인 (예시)
        "*.ssl-monitor.example.com",  # 서브도메인 허용 (예시)
    ]
)


# API 라우터 등록
app.include_router(websites.router)
app.include_router(ssl.router)
app.include_router(health.router)


# 전역 예외 처리
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 예외 처리"""
    logger.warning(f"HTTP {exc.status_code} 오류 발생: {exc.detail} - {request.url}")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "message": exc.detail,
            "timestamp": "",
            "path": str(request.url.path)
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """일반 예외 처리"""
    logger.error(f"예상치 못한 오류 발생: {str(exc)} - {request.url}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "status_code": 500,
            "message": "내부 서버 오류가 발생했습니다",
            "timestamp": "",
            "path": str(request.url.path)
        }
    )


# 요청/응답 로깅 미들웨어
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """요청/응답 로깅"""
    start_time = asyncio.get_event_loop().time()

    # 요청 로깅
    logger.info(f"요청 시작: {request.method} {request.url.path}")

    try:
        response = await call_next(request)
        process_time = asyncio.get_event_loop().time() - start_time

        # 응답 로깅
        logger.info(
            f"요청 완료: {request.method} {request.url.path} "
            f"- 상태: {response.status_code} - 소요시간: {process_time:.3f}초"
        )

        # 응답 헤더에 처리 시간 추가
        response.headers["X-Process-Time"] = str(process_time)

        return response

    except Exception as e:
        process_time = asyncio.get_event_loop().time() - start_time
        logger.error(
            f"요청 처리 중 오류: {request.method} {request.url.path} "
            f"- 소요시간: {process_time:.3f}초 - 오류: {str(e)}"
        )
        raise


# 루트 엔드포인트
@app.get("/")
async def root():
    """루트 엔드포인트 - 기본 정보 제공"""
    return {
        "message": "SSL Certificate Monitor API",
        "version": "1.0.0",
        "status": "running",
        "docs_url": "/api/docs",
        "health_check": "/api/health"
    }


# API 정보 엔드포인트
@app.get("/api")
async def api_info():
    """API 정보 제공"""
    return {
        "title": "SSL Certificate Monitor API",
        "version": "1.0.0",
        "description": "웹사이트 SSL 인증서 모니터링 및 알림 시스템 API",
        "endpoints": {
            "websites": "/api/websites",
            "ssl": "/api/ssl",
            "health": "/api/health",
            "documentation": "/api/docs"
        },
        "features": [
            "웹사이트 SSL 인증서 모니터링",
            "만료 임박 알림",
            "일괄 SSL 체크",
            "상세 SSL 정보 조회",
            "시스템 헬스체크",
            "실시간 메트릭"
        ]
    }


# 정적 파일 서빙 (프론트엔드용)
try:
    import os
    frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "src")
    if os.path.exists(frontend_path):
        app.mount("/static", StaticFiles(directory=frontend_path), name="static")
        logger.info(f"정적 파일 서빙 설정: {frontend_path}")
except Exception as e:
    logger.warning(f"정적 파일 서빙 설정 실패: {e}")


# 개발용 서버 실행
def run_dev_server():
    """개발용 서버 실행"""
    uvicorn.run(
        "backend.src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
        access_log=True
    )


if __name__ == "__main__":
    run_dev_server()