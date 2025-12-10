"""SQLAlchemy models for TSCM sweep storage."""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow():
    """Return current UTC time for database defaults."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Sweep(Base):
    """Represents a complete sweep session."""

    __tablename__ = "sweeps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sweep_id = Column(String(100), unique=True, nullable=False, index=True)
    client_name = Column(String(100), nullable=False)
    site = Column(String(100), nullable=True)
    room = Column(String(100), nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="running")  # running, completed, failed
    gps_lat = Column(Float, nullable=True)
    gps_lon = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    events = relationship("Event", back_populates="sweep", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="sweep", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_sweep_client_site_room", "client_name", "site", "room"),
        Index("idx_sweep_start_time", "start_time"),
        Index("idx_sweep_status", "status"),
    )


class Event(Base):
    """Represents a single RF/Wi-Fi/BLE/GSM event during a sweep."""

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sweep_id = Column(Integer, ForeignKey("sweeps.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(
        String(20), nullable=False, index=True
    )  # rf, wifi, ble, gsm, gps
    timestamp = Column(DateTime, nullable=False)

    # RF-specific fields
    freq_hz = Column(Float, nullable=True)
    power_db = Column(Float, nullable=True)
    bandwidth_hz = Column(Float, nullable=True)

    # Wi-Fi/BLE-specific fields
    mac_address = Column(String(17), nullable=True, index=True)
    ssid = Column(String(255), nullable=True)
    signal_strength = Column(Float, nullable=True)

    # GSM-specific fields
    mcc = Column(Integer, nullable=True)
    mnc = Column(Integer, nullable=True)
    lac = Column(Integer, nullable=True)
    cid = Column(Integer, nullable=True)
    arfcn = Column(Integer, nullable=True)

    # Generic fields
    event_metadata = Column(Text, nullable=True)  # JSON string for additional data

    created_at = Column(DateTime, default=utcnow, nullable=False)

    # Relationships
    sweep = relationship("Sweep", back_populates="events")

    __table_args__ = (
        Index("idx_event_sweep_type", "sweep_id", "event_type"),
        Index("idx_event_timestamp", "timestamp"),
        Index("idx_event_freq", "freq_hz"),
        Index("idx_event_mac", "mac_address"),
    )


class Artifact(Base):
    """Represents an artifact (file, log, capture) from a sweep."""

    __tablename__ = "artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sweep_id = Column(Integer, ForeignKey("sweeps.id", ondelete="CASCADE"), nullable=False)
    artifact_type = Column(
        String(50), nullable=False, index=True
    )  # rf_csv, wifi_pcap, ble_log, gsm_raw
    file_path = Column(String(500), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    checksum_sha256 = Column(String(64), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    # Relationships
    sweep = relationship("Sweep", back_populates="artifacts")

    __table_args__ = (Index("idx_artifact_sweep_type", "sweep_id", "artifact_type"),)


def create_engine_with_wal(database_url: str, enable_wal: bool = True, echo: bool = False):
    """
    Create SQLAlchemy engine with WAL mode enabled.

    Args:
        database_url: Database connection URL
        enable_wal: Whether to enable Write-Ahead Logging mode
        echo: Whether to echo SQL statements

    Returns:
        SQLAlchemy Engine
    """
    engine = create_engine(database_url, echo=echo)

    if enable_wal and database_url.startswith("sqlite"):
        # Enable WAL mode for better concurrency
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
            cursor.execute("PRAGMA busy_timeout=5000")  # 5 second timeout
            cursor.close()

    return engine


def init_db(engine):
    """Initialize database schema."""
    Base.metadata.create_all(engine)
