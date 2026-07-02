from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    ForeignKey,
)
from src.app_models.database import Base


# For Authentication
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)


class Link(Base):
    __tablename__ = "links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)
    short_url = Column(String(200), nullable=False)
    original_url = Column(Text, nullable=False)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    click_count = Column(BigInteger, default=0, nullable=False)
    unique_visitor_count = Column(BigInteger, default=0, nullable=False)

    max_clicks = Column(Integer, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_links_code", "code"),
        Index("ix_links_is_active", "is_active"),
        Index("ix_links_created_at", "created_at"),
    )


class Click(Base):
    __tablename__ = "clicks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    link_code = Column(String(50), ForeignKey("links.code"), nullable=False)
    clicked_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ip_hash = Column(String(64), nullable=True)  # SHA-256

    user_agent = Column(Text, nullable=True)
    referer = Column(Text, nullable=True)

    country = Column(String(100), nullable=True)
    country_code = Column(String(2), nullable=True)
    city = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)

    device_type = Column(String(20), nullable=True)  # mobile / desktop
    browser = Column(String(50), nullable=True)
    os = Column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_clicks_link_code", "link_code"),
        Index("ix_clicks_link_code_time", "link_code", "clicked_at"),
        Index("ix_clicks_country", "country"),
        Index("ix_clicks_device_type", "device_type"),
        Index("ix_clicks_link_code_ip_hash", "link_code", "ip_hash"),
    )
