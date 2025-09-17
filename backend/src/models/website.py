"""
Website 모델

모니터링 대상 웹사이트 정보를 관리하는 엔티티입니다.
"""

import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import Boolean, DateTime, String, text, TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class GUID(TypeDecorator):
    """범용 UUID 타입 (SQLite/PostgreSQL 호환)"""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(UUID())
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if isinstance(value, uuid.UUID):
                return str(value)
            return value

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(value)


class Website(Base):
    """웹사이트 엔티티

    Attributes:
        id: UUID primary key (자동 생성)
        url: HTTPS URL (unique constraint, not null)
        name: 표시명 (nullable, default: URL에서 추출)
        created_at: 생성 시간 (auto-generated)
        updated_at: 수정 시간 (auto-updated)
        is_active: 모니터링 활성화 여부 (default: true)
        ssl_certificates: 관련 SSL 인증서들 (관계)
    """

    __tablename__ = "websites"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )

    # URL (유니크 제약조건)
    url: Mapped[str] = mapped_column(
        String(2048),
        unique=True,
        nullable=False,
        index=True,
    )

    # 표시명 (nullable)
    name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    # 타임스탬프
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.utcnow,
    )

    # 활성화 상태
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    # 관계: SSL 인증서들 (CASCADE DELETE)
    ssl_certificates = relationship(
        "SSLCertificate",
        back_populates="website",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __init__(self, url: str, name: Optional[str] = None, is_active: bool = True):
        """Website 인스턴스 초기화

        Args:
            url: HTTPS URL
            name: 표시명 (없으면 도메인에서 추출)
            is_active: 활성화 상태
        """
        self.url = url
        self.name = name or self._extract_domain_from_url(url)
        self.is_active = is_active

    @validates("url")
    def validate_url(self, key: str, url: str) -> str:
        """URL 유효성 검증

        Args:
            key: 필드명
            url: 검증할 URL

        Returns:
            검증된 URL

        Raises:
            ValueError: URL이 유효하지 않은 경우
        """
        if not url:
            raise ValueError("URL은 필수입니다")

        if not url.startswith("https://"):
            raise ValueError("HTTPS URL만 허용됩니다")

        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                raise ValueError("유효한 도메인이 필요합니다")

            # 경로가 있는지 확인 (루트 도메인만 허용)
            if parsed.path and parsed.path != "/":
                raise ValueError("경로를 포함한 URL은 허용되지 않습니다. 루트 도메인만 사용하세요")

            # 기본 포트가 아닌 경우 허용 (예: https://example.com:8443)
            return url.rstrip("/")  # 끝에 있는 슬래시 제거

        except Exception as e:
            raise ValueError(f"유효하지 않은 URL 형식입니다: {str(e)}")

    @validates("name")
    def validate_name(self, key: str, name: Optional[str]) -> Optional[str]:
        """이름 유효성 검증

        Args:
            key: 필드명
            name: 검증할 이름

        Returns:
            검증된 이름
        """
        if name and len(name.strip()) == 0:
            return None

        if name and len(name) > 255:
            raise ValueError("이름은 255자를 초과할 수 없습니다")

        return name.strip() if name else None

    def _extract_domain_from_url(self, url: str) -> str:
        """URL에서 도메인 추출

        Args:
            url: 대상 URL

        Returns:
            추출된 도메인명
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc

            # 포트 번호 제거
            if ":" in domain:
                domain = domain.split(":")[0]

            # www. 제거
            if domain.startswith("www."):
                domain = domain[4:]

            return domain.title()  # 첫 글자 대문자
        except Exception:
            return "Unknown Domain"

    def update_url(self, new_url: str) -> None:
        """URL 업데이트 (자동으로 이름도 업데이트)

        Args:
            new_url: 새로운 URL
        """
        # URL 검증은 validates에서 자동으로 처리됨
        self.url = new_url

        # 이름이 기본값인 경우 새 도메인으로 업데이트
        old_domain = self._extract_domain_from_url(self.url)
        if self.name == old_domain:
            self.name = self._extract_domain_from_url(new_url)

    def deactivate(self) -> None:
        """웹사이트 비활성화 (소프트 삭제)"""
        self.is_active = False

    def activate(self) -> None:
        """웹사이트 활성화"""
        self.is_active = True

    def __repr__(self) -> str:
        """문자열 표현"""
        status = "active" if self.is_active else "inactive"
        return f"<Website(id={self.id}, url='{self.url}', name='{self.name}', status={status})>"

    def __str__(self) -> str:
        """사용자 친화적 문자열 표현"""
        return f"{self.name} ({self.url})"

    def to_dict(self) -> dict:
        """딕셔너리로 변환 (JSON 직렬화용)

        Returns:
            웹사이트 정보 딕셔너리
        """
        return {
            "id": str(self.id),
            "url": self.url,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": self.is_active,
        }

    @classmethod
    def create(cls, url: str, name: Optional[str] = None) -> "Website":
        """팩토리 메서드로 웹사이트 생성

        Args:
            url: 웹사이트 URL
            name: 표시명 (선택사항)

        Returns:
            생성된 Website 인스턴스
        """
        return cls(url=url, name=name)