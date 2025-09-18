"""
데이터베이스 설정 및 연결 관리

SQLAlchemy 엔진, 세션 관리, 마이그레이션을 담당합니다.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
import asyncio
import greenlet

try:
    # 패키지로 실행될 때 (python -m backend.src.database)
    from .models.website import Base
    from .models.ssl_certificate import SSLCertificate  # Import to register the table
except ImportError:
    # 직접 실행될 때 (python database.py)
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from models.website import Base
    from models.ssl_certificate import SSLCertificate  # Import to register the table


class DatabaseConfig:
    """데이터베이스 설정 클래스"""

    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./ssl_checker.db")
        self.echo = os.getenv("DEBUG", "false").lower() == "true"
        self.pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
        self.max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))

    @property
    def async_database_url(self) -> str:
        """비동기 데이터베이스 URL 반환"""
        if self.database_url.startswith("sqlite"):
            return self.database_url.replace("sqlite://", "sqlite+aiosqlite://")
        elif self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://")
        else:
            return self.database_url

    @property
    def is_sqlite(self) -> bool:
        """SQLite 사용 여부 확인"""
        return self.database_url.startswith("sqlite")

    @property
    def is_postgresql(self) -> bool:
        """PostgreSQL 사용 여부 확인"""
        return self.database_url.startswith("postgresql")


class DatabaseManager:
    """데이터베이스 연결 관리자"""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig()
        self._engine = None
        self._async_engine = None
        self._session_factory = None
        self._async_session_factory = None

    @property
    def engine(self):
        """동기 엔진 (마이그레이션용)"""
        if self._engine is None:
            if self.config.is_sqlite:
                self._engine = create_engine(
                    self.config.database_url,
                    echo=self.config.echo,
                    poolclass=StaticPool,
                    connect_args={"check_same_thread": False},
                )
            else:
                self._engine = create_engine(
                    self.config.database_url,
                    echo=self.config.echo,
                    pool_size=self.config.pool_size,
                    max_overflow=self.config.max_overflow,
                )
        return self._engine

    @property
    def async_engine(self):
        """비동기 엔진 (일반 사용)"""
        if self._async_engine is None:
            if self.config.is_sqlite:
                self._async_engine = create_async_engine(
                    self.config.async_database_url,
                    echo=self.config.echo,
                    poolclass=StaticPool,
                    connect_args={"check_same_thread": False},
                )
            else:
                self._async_engine = create_async_engine(
                    self.config.async_database_url,
                    echo=self.config.echo,
                    pool_size=self.config.pool_size,
                    max_overflow=self.config.max_overflow,
                )
        return self._async_engine

    @property
    def session_factory(self):
        """동기 세션 팩토리"""
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False,
            )
        return self._session_factory

    @property
    def async_session_factory(self):
        """비동기 세션 팩토리"""
        if self._async_session_factory is None:
            self._async_session_factory = async_sessionmaker(
                bind=self.async_engine,
                class_=AsyncSession,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )
        return self._async_session_factory

    def create_isolated_async_session_factory(self):
        """격리된 비동기 세션 팩토리 생성 (greenlet 문제 해결용)

        새로운 엔진과 세션 팩토리를 생성하여 greenlet context 충돌을 방지합니다.
        """
        # 새로운 엔진 생성
        if self.config.is_sqlite:
            isolated_engine = create_async_engine(
                self.config.async_database_url,
                echo=self.config.echo,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
        else:
            isolated_engine = create_async_engine(
                self.config.async_database_url,
                echo=self.config.echo,
                pool_size=2,  # 격리된 세션은 작은 풀 사용
                max_overflow=5,
            )

        # 새로운 세션 팩토리 생성
        return async_sessionmaker(
            bind=isolated_engine,
            class_=AsyncSession,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

    def get_session(self) -> Session:
        """동기 세션 생성"""
        return self.session_factory()

    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """비동기 세션 컨텍스트 매니저

        Yields:
            AsyncSession: 비동기 데이터베이스 세션
        """
        async with self.async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def create_all_tables(self) -> None:
        """모든 테이블 생성"""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_all_tables(self) -> None:
        """모든 테이블 삭제 (테스트용)"""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    def create_all_tables_sync(self) -> None:
        """모든 테이블 생성 (동기)"""
        Base.metadata.create_all(bind=self.engine)

    def drop_all_tables_sync(self) -> None:
        """모든 테이블 삭제 (동기, 테스트용)"""
        Base.metadata.drop_all(bind=self.engine)

    async def check_connection(self) -> bool:
        """데이터베이스 연결 확인

        Returns:
            연결 성공 여부
        """
        try:
            async with self.async_engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            print(f"데이터베이스 연결 실패: {e}")
            return False

    async def init_database(self) -> None:
        """데이터베이스 초기화 (테이블 생성 + 인덱스)"""
        await self.create_all_tables()
        await self._create_indexes()

    async def _create_indexes(self) -> None:
        """커스텀 인덱스 생성"""
        indexes = [
            # 복합 인덱스: SSL 인증서 만료 체크
            """
            CREATE INDEX IF NOT EXISTS idx_ssl_expiry_date
            ON ssl_certificates (expiry_date, website_id)
            """,
            # 사이트별 히스토리 인덱스
            """
            CREATE INDEX IF NOT EXISTS idx_ssl_website_created_at
            ON ssl_certificates (website_id, created_at DESC)
            """,
        ]

        async with self.async_engine.begin() as conn:
            for index_sql in indexes:
                try:
                    await conn.execute(text(index_sql))
                except Exception as e:
                    print(f"인덱스 생성 실패: {e}")

    async def close(self) -> None:
        """연결 정리"""
        if self._async_engine:
            await self._async_engine.dispose()
        if self._engine:
            self._engine.dispose()


# 전역 데이터베이스 관리자 인스턴스
db_manager = DatabaseManager()


# 의존성 주입용 함수들
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 의존성: 비동기 세션 제공

    Yields:
        AsyncSession: 비동기 데이터베이스 세션
    """
    async with db_manager.get_async_session() as session:
        yield session


def get_async_session_factory():
    """비동기 세션 팩토리 반환

    Returns:
        async_sessionmaker: 독립적인 세션 생성용 팩토리
    """
    return db_manager.async_session_factory

def get_isolated_async_session_factory():
    """격리된 비동기 세션 팩토리 반환 (greenlet 문제 해결용)

    새로운 엔진과 세션을 생성하여 greenlet context 충돌을 방지합니다.

    Returns:
        async_sessionmaker: 격리된 세션 생성용 팩토리
    """
    return db_manager.create_isolated_async_session_factory()


def get_session() -> Session:
    """동기 세션 제공 (CLI, 테스트용)

    Returns:
        Session: 동기 데이터베이스 세션
    """
    return db_manager.get_session()


# 데이터베이스 초기화 함수
async def init_db() -> None:
    """데이터베이스 초기화"""
    await db_manager.init_database()


async def close_db() -> None:
    """데이터베이스 연결 정리"""
    await db_manager.close()


# 헬스체크 함수
async def health_check() -> dict:
    """데이터베이스 헬스체크

    Returns:
        헬스체크 결과
    """
    try:
        is_connected = await db_manager.check_connection()
        return {
            "database": "healthy" if is_connected else "unhealthy",
            "database_url": db_manager.config.database_url.split("@")[-1] if "@" in db_manager.config.database_url else "local",
            "engine_type": "sqlite" if db_manager.config.is_sqlite else "postgresql",
        }
    except Exception as e:
        return {
            "database": "error",
            "error": str(e),
        }


# Alembic 지원을 위한 메타데이터 Export
metadata = Base.metadata


# 테스트 지원 함수
class TestDatabaseManager:
    """테스트용 데이터베이스 관리자"""

    def __init__(self):
        self.config = DatabaseConfig()
        self.config.database_url = "sqlite:///:memory:"
        self.manager = DatabaseManager(self.config)

    async def setup(self) -> None:
        """테스트 데이터베이스 설정"""
        await self.manager.create_all_tables()

    async def teardown(self) -> None:
        """테스트 데이터베이스 정리"""
        await self.manager.drop_all_tables()
        await self.manager.close()

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """테스트용 세션 제공"""
        async with self.manager.get_async_session() as session:
            yield session


# 마이그레이션 지원
def get_alembic_config():
    """Alembic 설정 반환"""
    from alembic.config import Config
    from alembic import command

    # alembic.ini 경로 설정
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_manager.config.database_url)
    return alembic_cfg


def run_migrations():
    """마이그레이션 실행"""
    from alembic import command

    alembic_cfg = get_alembic_config()
    command.upgrade(alembic_cfg, "head")


def create_migration(message: str):
    """새 마이그레이션 생성"""
    from alembic import command

    alembic_cfg = get_alembic_config()
    command.revision(alembic_cfg, autogenerate=True, message=message)