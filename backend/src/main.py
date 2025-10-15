"""
FastAPI 메인 애플리케이션

SSL Certificate Monitoring Dashboard의 메인 웹 애플리케이션입니다.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

# Uvicorn ProxyHeaders 미들웨어 import (프록시 뒤에서 실행될 때 필요)
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


# 캐시 제어가 가능한 커스텀 StaticFiles 클래스
class NoCacheStaticFiles(StaticFiles):
    """
    정적 파일 서빙 시 캐시를 비활성화하는 커스텀 클래스
    개발 중에는 항상 최신 파일을 제공하도록 설정
    """
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        # 개발 환경: 캐시 비활성화
        # 운영 환경: 짧은 캐시 시간 설정 (5분)
        if os.getenv("ENVIRONMENT", "development") == "production":
            response.headers["Cache-Control"] = "public, max-age=300"  # 5분
        else:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

try:
    # 패키지로 실행될 때 (python -m backend.src.main)
    from .database import init_db, close_db
    from .api import websites, ssl, health, tasks, settings
    from .scheduler import start_scheduler, stop_scheduler
    from .background import start_background_executor, stop_background_executor
except ImportError:
    # 직접 실행될 때 (python main.py)
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from database import init_db, close_db
    from api import websites, ssl, health, tasks, settings
    from scheduler import start_scheduler, stop_scheduler
    from background import start_background_executor, stop_background_executor


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

        # 백그라운드 작업 실행기 시작
        await start_background_executor()
        logger.info("백그라운드 작업 실행기 시작 완료")

        # 스케줄러 시작
        await start_scheduler()
        logger.info("스케줄러 시작 완료")

        yield

    finally:
        # 종료 시 실행
        logger.info("SSL Certificate Monitor 종료 중...")

        # 스케줄러 종료
        await stop_scheduler()
        logger.info("스케줄러 종료 완료")

        # 백그라운드 작업 실행기 종료
        await stop_background_executor()
        logger.info("백그라운드 작업 실행기 종료 완료")

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


# ProxyHeaders 미들웨어 설정 (가장 먼저 추가해야 함)
# OpenShift Route/Kubernetes Ingress 뒤에서 실행될 때 X-Forwarded-* 헤더 인식
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# CORS 미들웨어 설정
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080,https://ssl-monitoring-checking-ssl.d3.clouz.io,https://postgresql-checking-ssl.d3.clouz.io").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# 신뢰할 수 있는 호스트 미들웨어
# 참고: Kubernetes 환경에서는 내부 Service 통신을 위해 "*" 허용 필요
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS if ALLOWED_HOSTS != ["*"] else ["*"],
)


# API 라우터 등록
app.include_router(websites.router)
app.include_router(ssl.router)
app.include_router(health.router)
app.include_router(tasks.router)
app.include_router(settings.router)


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


# 요청/응답 로깅 및 리다이렉트 수정 미들웨어
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """요청/응답 로깅 및 HTTPS 리다이렉트 처리"""
    start_time = asyncio.get_event_loop().time()

    # 프록시 헤더 확인
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    forwarded_host = request.headers.get("x-forwarded-host", "")

    # 요청 로깅
    logger.info(f"요청 시작: {request.method} {request.url.path} (Proto: {forwarded_proto}, Host: {forwarded_host})")

    try:
        response = await call_next(request)
        process_time = asyncio.get_event_loop().time() - start_time

        # 307 리다이렉트의 경우 Location 헤더를 HTTPS로 수정
        if response.status_code == 307 and "location" in response.headers:
            location = response.headers["location"]

            # X-Forwarded-Proto가 https이거나, 알려진 HTTPS 도메인인 경우
            if forwarded_proto == "https" or "ssl-monitoring-checking-ssl.d3.clouz.io" in location:
                if location.startswith("http://"):
                    new_location = location.replace("http://", "https://", 1)
                    response.headers["location"] = new_location
                    logger.info(f"리다이렉트 URL 수정: {location} -> {new_location}")

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


# 루트 엔드포인트 - 프론트엔드 서빙
@app.get("/")
async def root():
    """루트 엔드포인트 - 프론트엔드 대시보드 제공"""
    try:
        import os
        # 프로젝트 루트 디렉토리 찾기
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # Docker 환경: /app/src/main.py -> /app
        # 로컬 환경: backend/src/main.py -> project_root
        if current_dir.startswith("/app/src"):
            # Docker 컨테이너 환경
            project_root = "/app"
        else:
            # 로컬 개발 환경
            project_root = os.path.dirname(os.path.dirname(current_dir))

        frontend_path = os.path.join(project_root, "frontend", "src", "index.html")

        logger.info(f"현재 디렉토리: {current_dir}")
        logger.info(f"프로젝트 루트: {project_root}")
        logger.info(f"프론트엔드 파일 경로: {frontend_path}")

        if os.path.exists(frontend_path):
            # HTML 파일에 캐시 제어 헤더 추가
            response = FileResponse(frontend_path)
            if os.getenv("ENVIRONMENT", "development") == "production":
                response.headers["Cache-Control"] = "public, max-age=300"
            else:
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response
        else:
            # 프론트엔드 파일이 없는 경우 API 정보 반환
            return {
                "message": "SSL Certificate Monitor API",
                "version": "1.0.0",
                "status": "running",
                "docs_url": "/api/docs",
                "health_check": "/api/health",
                "note": "Frontend dashboard not found",
                "debug": {
                    "current_dir": current_dir,
                    "project_root": project_root,
                    "frontend_path": frontend_path,
                    "exists": os.path.exists(frontend_path)
                }
            }
    except Exception as e:
        logger.warning(f"프론트엔드 파일 서빙 실패: {e}")
        return {
            "message": "SSL Certificate Monitor API",
            "version": "1.0.0",
            "status": "running",
            "docs_url": "/api/docs",
            "health_check": "/api/health",
            "error": str(e)
        }


# 설정 페이지 엔드포인트
@app.get("/settings.html")
async def settings_page():
    """설정 페이지 제공"""
    try:
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # Docker 환경 vs 로컬 환경 구분
        if current_dir.startswith("/app/src"):
            project_root = "/app"
        else:
            project_root = os.path.dirname(os.path.dirname(current_dir))

        settings_path = os.path.join(project_root, "frontend", "src", "settings.html")

        logger.info(f"설정 페이지 경로: {settings_path}")

        if os.path.exists(settings_path):
            # HTML 파일에 캐시 제어 헤더 추가
            response = FileResponse(settings_path)
            if os.getenv("ENVIRONMENT", "development") == "production":
                response.headers["Cache-Control"] = "public, max-age=300"
            else:
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response
        else:
            raise HTTPException(status_code=404, detail="Settings page not found")
    except Exception as e:
        logger.warning(f"설정 페이지 서빙 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
            "tasks": "/api/tasks",
            "settings": "/api/settings",
            "documentation": "/api/docs"
        },
        "features": [
            "웹사이트 SSL 인증서 모니터링",
            "만료 임박 알림",
            "일괄 SSL 체크",
            "상세 SSL 정보 조회",
            "시스템 헬스체크",
            "실시간 메트릭",
            "자동 스케줄링",
            "백그라운드 작업 관리"
        ]
    }


# 정적 파일 서빙 (프론트엔드용)
try:
    import os
    # 프로젝트 루트 디렉토리 찾기
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Docker 환경 vs 로컬 환경 구분
    if current_dir.startswith("/app/src"):
        project_root = "/app"
    else:
        project_root = os.path.dirname(os.path.dirname(current_dir))

    frontend_path = os.path.join(project_root, "frontend", "src")

    if os.path.exists(frontend_path):
        # JavaScript, CSS 등 정적 파일을 위한 마운트 (캐시 제어 적용)
        js_path = os.path.join(frontend_path, "js")
        if os.path.exists(js_path):
            app.mount("/js", NoCacheStaticFiles(directory=js_path), name="js")
            logger.info(f"JavaScript 파일 서빙 설정 (캐시 제어): {js_path}")

        css_path = os.path.join(frontend_path, "css")
        if os.path.exists(css_path):
            app.mount("/css", NoCacheStaticFiles(directory=css_path), name="css")
            logger.info(f"CSS 파일 서빙 설정 (캐시 제어): {css_path}")

        app.mount("/static", NoCacheStaticFiles(directory=frontend_path), name="static")
        logger.info(f"정적 파일 서빙 설정 완료 (캐시 제어): {frontend_path}")
    else:
        logger.warning(f"프론트엔드 디렉토리를 찾을 수 없음: {frontend_path}")
except Exception as e:
    logger.warning(f"정적 파일 서빙 설정 실패: {e}")


# 개발용 서버 실행
def run_dev_server():
    """개발용 서버 실행"""
    uvicorn.run(
        "backend.src.main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info",
        access_log=True
    )


if __name__ == "__main__":
    run_dev_server()