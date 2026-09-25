import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, ForeignKey, String, DateTime, Text, Integer, JSON, UniqueConstraint, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from pgvector.sqlalchemy import Vector
from .config import settings


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)
Json = JSON().with_variant(JSONB, 'postgresql')


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default='user')
    profile: Mapped[dict] = mapped_column(Json, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Login(Base):
    __tablename__ = 'sessions'
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Record(Base):
    """Versionable domain documents. Ownership is always enforced in the API.

    Kinds: cv, vacancy, document, plan, interview, source, question, material.
    Shared knowledge has owner_id=NULL; only admin routes may mutate it.
    """
    __tablename__ = 'records'
    __table_args__ = (UniqueConstraint('owner_id', 'kind', 'dedup_key'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    dedup_key: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default='draft', index=True)
    data: Mapped[dict] = mapped_column(Json, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Knowledge(Base):
    __tablename__ = 'knowledge'
    record_id: Mapped[str] = mapped_column(ForeignKey('records.id', ondelete='CASCADE'), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(20))
    level: Mapped[str] = mapped_column(String(10))
    language: Mapped[str] = mapped_column(String(2))
    embedding: Mapped[list | None] = mapped_column(Vector(1536))


class Job(Base):
    __tablename__ = 'jobs'
    __table_args__ = (UniqueConstraint('owner_id', 'request_key'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    request_key: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(Json)
    result: Mapped[dict] = mapped_column(Json, default=dict)
    checkpoints: Mapped[dict] = mapped_column(Json, default=dict)
    status: Mapped[str] = mapped_column(String(24), default='queued', index=True)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Budget(Base):
    __tablename__ = 'budgets'
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    charged: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    video_seconds: Mapped[int] = mapped_column(Integer, default=0)


class Usage(Base):
    __tablename__ = 'usage'
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    # No personal content; preserve aggregate spend after account deletion.
    month: Mapped[str] = mapped_column(ForeignKey('budgets.month'))
    operation: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    reserved: Mapped[float] = mapped_column(Numeric(12, 6))
    actual: Mapped[float | None] = mapped_column(Numeric(12, 6))
    state: Mapped[str] = mapped_column(String(20), default='reserved')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
