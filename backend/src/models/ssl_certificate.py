"""
SSL Certificate 모델

SSL 인증서 정보 및 상태를 추적하는 엔티티입니다.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.ext.declarative import declarative_base

try:
    # 패키지로 실행될 때 (python -m backend.src.models.ssl_certificate)
    from .website import Base, GUID
except ImportError:
    # 직접 실행될 때 (python ssl_certificate.py)
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from website import Base, GUID


class SSLStatus(Enum):
    """SSL 인증서 상태 열거형"""

    VALID = "valid"  # 정상 인증서
    INVALID = "invalid"  # 유효하지 않은 인증서
    EXPIRED = "expired"  # 만료된 인증서
    REVOKED = "revoked"  # 폐기된 인증서
    UNKNOWN = "unknown"  # 상태 불명


class SSLCertificate(Base):
    """SSL 인증서 엔티티

    Attributes:
        id: UUID primary key (자동 생성)
        website_id: Website 외래키 (not null, cascade delete)
        issuer: 인증서 발급자 (CA 정보)
        subject: 인증서 주체 (도메인 정보)
        serial_number: 인증서 시리얼 번호
        issued_date: 발급 날짜
        expiry_date: 만료 날짜 (알림 기준)
        fingerprint: SHA-256 지문 (인증서 고유 식별)
        status: 인증서 상태 (enum)
        last_checked: 마지막 체크 시간
        created_at: 레코드 생성 시간
        website: 관련 웹사이트 (관계)
    """

    __tablename__ = "ssl_certificates"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Foreign Key to Website
    website_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 인증서 정보
    issuer: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )

    subject: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )

    serial_number: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )

    # 날짜 정보
    issued_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    expiry_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,  # 만료 알림 쿼리 최적화
    )

    # 인증서 지문 (고유 식별)
    fingerprint: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,  # 같은 인증서 중복 방지
    )

    # 상태 정보
    status: Mapped[SSLStatus] = mapped_column(
        SQLEnum(SSLStatus),
        nullable=False,
        default=SSLStatus.UNKNOWN,
        index=True,  # 상태별 필터링 최적화
    )

    last_checked: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,  # 배치 처리 최적화
    )

    # 레코드 생성 시간
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # 관계: 웹사이트
    website = relationship(
        "Website",
        back_populates="ssl_certificates",
        lazy="select",
    )

    def __init__(
        self,
        website_id: uuid.UUID,
        issuer: str,
        subject: str,
        serial_number: str,
        issued_date: datetime,
        expiry_date: datetime,
        fingerprint: str,
        status: SSLStatus = SSLStatus.UNKNOWN,
    ):
        """SSL Certificate 인스턴스 초기화

        Args:
            website_id: 관련 웹사이트 ID
            issuer: 발급자
            subject: 주체
            serial_number: 시리얼 번호
            issued_date: 발급일
            expiry_date: 만료일
            fingerprint: 지문
            status: 상태
        """
        self.website_id = website_id
        self.issuer = issuer
        self.subject = subject
        self.serial_number = serial_number
        self.issued_date = issued_date
        self.expiry_date = expiry_date
        self.fingerprint = fingerprint
        self.status = status
        self.last_checked = datetime.utcnow()

    @validates("expiry_date")
    def validate_expiry_date(self, key: str, expiry_date: datetime) -> datetime:
        """만료일 유효성 검증

        Args:
            key: 필드명
            expiry_date: 검증할 만료일

        Returns:
            검증된 만료일

        Raises:
            ValueError: 만료일이 발급일보다 이전인 경우
        """
        if hasattr(self, "issued_date") and self.issued_date:
            if expiry_date <= self.issued_date:
                raise ValueError("만료일은 발급일보다 미래여야 합니다")

        return expiry_date

    @validates("fingerprint")
    def validate_fingerprint(self, key: str, fingerprint: str) -> str:
        """지문 유효성 검증

        Args:
            key: 필드명
            fingerprint: 검증할 지문

        Returns:
            검증된 지문

        Raises:
            ValueError: 지문이 유효하지 않은 경우
        """
        if not fingerprint or len(fingerprint.strip()) == 0:
            raise ValueError("지문은 필수입니다")

        # SHA-256 지문 형식 검증 (64자 16진수)
        fingerprint = fingerprint.strip().lower()
        if len(fingerprint) != 64:
            raise ValueError("지문은 64자 16진수여야 합니다")

        try:
            int(fingerprint, 16)
        except ValueError:
            raise ValueError("지문은 유효한 16진수여야 합니다")

        return fingerprint

    def is_expired(self) -> bool:
        """인증서가 만료되었는지 확인

        Returns:
            만료 여부
        """
        return datetime.utcnow() > self.expiry_date

    def is_expiring_soon(self, days: int = 30) -> bool:
        """인증서가 곧 만료되는지 확인

        Args:
            days: 확인할 일수

        Returns:
            곧 만료 여부
        """
        from datetime import timedelta

        threshold = datetime.utcnow() + timedelta(days=days)
        return self.expiry_date <= threshold

    def days_until_expiry(self) -> int:
        """만료까지 남은 일수

        Returns:
            만료까지 남은 일수 (음수면 이미 만료됨)
        """
        delta = self.expiry_date - datetime.utcnow()
        return delta.days

    def update_status_based_on_expiry(self) -> None:
        """만료일을 기준으로 상태 업데이트"""
        if self.is_expired():
            self.status = SSLStatus.EXPIRED
        elif self.status == SSLStatus.EXPIRED and not self.is_expired():
            # 만료에서 복구된 경우 (시스템 시간 변경 등)
            self.status = SSLStatus.VALID

    def update_check_time(self) -> None:
        """마지막 체크 시간 업데이트"""
        self.last_checked = datetime.utcnow()

    def get_notification_urgency(self) -> str:
        """알림 긴급도 반환

        Returns:
            긴급도 ('critical', 'warning', 'info', 'none')
        """
        if self.status in [SSLStatus.INVALID, SSLStatus.REVOKED]:
            return "critical"

        if self.is_expired():
            return "critical"

        days_left = self.days_until_expiry()
        if days_left <= 1:
            return "critical"
        elif days_left <= 7:
            return "warning"
        elif days_left <= 30:
            return "info"
        else:
            return "none"

    def __repr__(self) -> str:
        """문자열 표현"""
        return (
            f"<SSLCertificate(id={self.id}, website_id={self.website_id}, "
            f"subject='{self.subject}', status={self.status.value}, "
            f"expiry_date={self.expiry_date})>"
        )

    def __str__(self) -> str:
        """사용자 친화적 문자열 표현"""
        days_left = self.days_until_expiry()
        if days_left > 0:
            return f"{self.subject} (만료 {days_left}일 남음, {self.status.value})"
        else:
            return f"{self.subject} (만료됨, {self.status.value})"

    def to_dict(self) -> dict:
        """딕셔너리로 변환 (JSON 직렬화용)

        Returns:
            SSL 인증서 정보 딕셔너리
        """
        return {
            "id": str(self.id),
            "website_id": str(self.website_id),
            "issuer": self.issuer,
            "subject": self.subject,
            "serial_number": self.serial_number,
            "issued_date": self.issued_date.isoformat() if self.issued_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "fingerprint": self.fingerprint,
            "status": self.status.value,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "days_until_expiry": self.days_until_expiry(),
            "is_expired": self.is_expired(),
            "notification_urgency": self.get_notification_urgency(),
        }

    @classmethod
    def create_from_cert_info(
        cls,
        website_id: uuid.UUID,
        cert_info: dict,
        status: SSLStatus = SSLStatus.VALID,
    ) -> "SSLCertificate":
        """인증서 정보 딕셔너리로부터 생성

        Args:
            website_id: 웹사이트 ID
            cert_info: 인증서 정보 (issuer, subject, serial_number, issued_date, expiry_date, fingerprint)
            status: 초기 상태

        Returns:
            생성된 SSLCertificate 인스턴스
        """
        return cls(
            website_id=website_id,
            issuer=cert_info["issuer"],
            subject=cert_info["subject"],
            serial_number=cert_info["serial_number"],
            issued_date=cert_info["issued_date"],
            expiry_date=cert_info["expiry_date"],
            fingerprint=cert_info["fingerprint"],
            status=status,
        )