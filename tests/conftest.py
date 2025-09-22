"""
테스트 설정 및 픽스처
"""

import pytest
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import AsyncGenerator, Generator
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.src.database import get_async_session, Base
from backend.src.main import app
from backend.src.models.website import Website
from backend.src.models.ssl_certificate import SSLCertificate, SSLStatus


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """이벤트 루프 픽스처"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    """테스트용 데이터베이스 엔진"""

    def enable_fk(dbapi_connection, connection_record):
        """SQLite에서 Foreign Key 제약 조건 활성화"""
        import sqlite3
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False
    )

    # Foreign Key 활성화를 위한 이벤트 리스너 추가
    from sqlalchemy import event
    event.listen(engine.sync_engine, "connect", enable_fk)

    # 테이블 생성
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """데이터베이스 세션 픽스처"""
    async with AsyncSession(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False
    ) as session:
        yield session
        await session.rollback()


@pytest.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    """비동기 HTTP 클라이언트 픽스처"""

    # 의존성 오버라이드
    app.dependency_overrides[get_async_session] = lambda: db_session

    # 테스트용 앱에서 TrustedHostMiddleware 제거
    # 미들웨어는 user_middleware에 저장됨
    original_middleware = app.user_middleware.copy()
    app.user_middleware = [
        middleware for middleware in app.user_middleware
        if middleware.cls.__name__ != 'TrustedHostMiddleware'
    ]
    app.middleware_stack = app.build_middleware_stack()

    async with httpx.AsyncClient(
        app=app,
        base_url="http://testserver",
        follow_redirects=True
    ) as client:
        yield client

    # 미들웨어 복원
    app.user_middleware = original_middleware
    app.middleware_stack = app.build_middleware_stack()

    # 오버라이드 정리
    app.dependency_overrides.clear()


@pytest.fixture
async def sample_website(db_session: AsyncSession) -> Website:
    """샘플 웹사이트 픽스처"""
    website = Website.create(
        url="https://example.com",
        name="Example Site"
    )
    db_session.add(website)
    await db_session.commit()
    await db_session.refresh(website)
    return website


@pytest.fixture
async def sample_ssl_certificate(db_session: AsyncSession, sample_website: Website) -> SSLCertificate:
    """샘플 SSL 인증서 픽스처"""
    ssl_cert = SSLCertificate(
        website_id=sample_website.id,
        issuer="Test CA",
        subject=f"CN={sample_website.url}",
        serial_number="12345",
        issued_date=datetime.utcnow() - timedelta(days=30),
        expiry_date=datetime.utcnow() + timedelta(days=30),
        fingerprint="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
        status=SSLStatus.VALID
    )
    db_session.add(ssl_cert)
    await db_session.commit()
    await db_session.refresh(ssl_cert)
    return ssl_cert


@pytest.fixture
async def sample_website_with_ssl(
    db_session: AsyncSession,
    sample_website: Website,
    sample_ssl_certificate: SSLCertificate
) -> tuple[Website, SSLCertificate]:
    """SSL 인증서가 있는 웹사이트 픽스처"""
    return sample_website, sample_ssl_certificate


@pytest.fixture
async def sample_website_with_recent_ssl(db_session: AsyncSession) -> tuple[Website, SSLCertificate]:
    """최근 SSL 체크가 있는 웹사이트 픽스처"""
    website = Website.create(
        url="https://recent-ssl.com",
        name="Recent SSL Site"
    )
    db_session.add(website)
    await db_session.commit()
    await db_session.refresh(website)

    ssl_cert = SSLCertificate(
        website_id=website.id,
        issuer="Recent CA",
        subject=f"CN={website.url}",
        serial_number="recent123",
        issued_date=datetime.utcnow() - timedelta(hours=1),
        expiry_date=datetime.utcnow() + timedelta(days=90),
        fingerprint="b1c2d3e4f5a6789012345678901234567890bcdefab234567890bcdefab23456",
        status=SSLStatus.VALID,
        last_checked=datetime.utcnow()
    )
    db_session.add(ssl_cert)
    await db_session.commit()
    await db_session.refresh(ssl_cert)

    return website, ssl_cert


@pytest.fixture
async def multiple_websites(db_session: AsyncSession) -> list[Website]:
    """여러 웹사이트 픽스처"""
    websites = []
    for i in range(5):
        website = Website.create(
            url=f"https://example{i}.com",
            name=f"Example Site {i}"
        )
        db_session.add(website)
        websites.append(website)

    await db_session.commit()

    # 세션에서 다시 조회
    for website in websites:
        await db_session.refresh(website)

    return websites