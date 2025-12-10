"""Storage API for sweep data."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import sessionmaker

from .models import Anomaly, Artifact, Event, Sweep, create_engine_with_wal, init_db


class SweepStore:
    """Storage interface for TSCM sweep data."""

    def __init__(self, database_path: str, enable_wal: bool = True, echo: bool = False):
        """
        Initialize storage.

        Args:
            database_path: Path to SQLite database file
            enable_wal: Enable Write-Ahead Logging mode
            echo: Echo SQL statements for debugging
        """
        # Ensure directory exists
        db_path = Path(database_path).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create engine and session factory
        database_url = f"sqlite:///{db_path}"
        self.engine = create_engine_with_wal(database_url, enable_wal=enable_wal, echo=echo)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

        # Initialize schema
        init_db(self.engine)

    def create_sweep(
        self,
        sweep_id: str,
        client_name: str,
        site: Optional[str] = None,
        room: Optional[str] = None,
        start_time: Optional[datetime] = None,
        gps_lat: Optional[float] = None,
        gps_lon: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> int:
        """
        Create a new sweep session.

        Args:
            sweep_id: Unique identifier for the sweep
            client_name: Client name
            site: Site name
            room: Room name
            start_time: Sweep start time (defaults to now)
            gps_lat: GPS latitude
            gps_lon: GPS longitude
            notes: Additional notes

        Returns:
            Database ID of created sweep
        """
        with self.SessionLocal() as session:
            sweep = Sweep(
                sweep_id=sweep_id,
                client_name=client_name,
                site=site,
                room=room,
                start_time=start_time or datetime.now(timezone.utc),
                status="running",
                gps_lat=gps_lat,
                gps_lon=gps_lon,
                notes=notes,
            )
            session.add(sweep)
            session.commit()
            session.refresh(sweep)
            return sweep.id

    def update_sweep(
        self,
        sweep_db_id: int,
        end_time: Optional[datetime] = None,
        status: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Update sweep metadata.

        Args:
            sweep_db_id: Database ID of sweep
            end_time: Sweep end time
            status: Sweep status (running, completed, failed)
            notes: Additional notes

        Returns:
            True if sweep was updated
        """
        with self.SessionLocal() as session:
            sweep = session.get(Sweep, sweep_db_id)
            if not sweep:
                return False

            if end_time is not None:
                sweep.end_time = end_time
            if status is not None:
                sweep.status = status
            if notes is not None:
                sweep.notes = notes

            session.commit()
            return True

    def add_event(
        self,
        sweep_db_id: int,
        event_type: str,
        timestamp: datetime,
        freq_hz: Optional[float] = None,
        power_db: Optional[float] = None,
        bandwidth_hz: Optional[float] = None,
        mac_address: Optional[str] = None,
        ssid: Optional[str] = None,
        signal_strength: Optional[float] = None,
        mcc: Optional[int] = None,
        mnc: Optional[int] = None,
        lac: Optional[int] = None,
        cid: Optional[int] = None,
        arfcn: Optional[int] = None,
        metadata: Optional[Dict] = None,
    ) -> int:
        """
        Add an event to a sweep.

        Args:
            sweep_db_id: Database ID of sweep
            event_type: Type of event (rf, wifi, ble, gsm, gps)
            timestamp: Event timestamp
            freq_hz: Frequency in Hz (RF)
            power_db: Power in dB (RF)
            bandwidth_hz: Bandwidth in Hz (RF)
            mac_address: MAC address (Wi-Fi/BLE)
            ssid: SSID (Wi-Fi)
            signal_strength: Signal strength (Wi-Fi/BLE)
            mcc: Mobile Country Code (GSM)
            mnc: Mobile Network Code (GSM)
            lac: Location Area Code (GSM)
            cid: Cell ID (GSM)
            arfcn: Absolute Radio Frequency Channel Number (GSM)
            metadata: Additional metadata as dict

        Returns:
            Database ID of created event
        """
        with self.SessionLocal() as session:
            event = Event(
                sweep_id=sweep_db_id,
                event_type=event_type,
                timestamp=timestamp,
                freq_hz=freq_hz,
                power_db=power_db,
                bandwidth_hz=bandwidth_hz,
                mac_address=mac_address,
                ssid=ssid,
                signal_strength=signal_strength,
                mcc=mcc,
                mnc=mnc,
                lac=lac,
                cid=cid,
                arfcn=arfcn,
                event_metadata=json.dumps(metadata) if metadata else None,
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            return event.id

    def add_events_bulk(self, sweep_db_id: int, events: List[Dict]) -> int:
        """
        Add multiple events in bulk.

        Args:
            sweep_db_id: Database ID of sweep
            events: List of event dictionaries

        Returns:
            Number of events added
        """
        with self.SessionLocal() as session:
            event_objects = []
            for event_data in events:
                metadata = event_data.pop("metadata", None)
                event = Event(
                    sweep_id=sweep_db_id,
                    event_metadata=json.dumps(metadata) if metadata else None,
                    **event_data,
                )
                event_objects.append(event)

            session.add_all(event_objects)
            session.commit()
            return len(event_objects)

    def add_artifact(
        self,
        sweep_db_id: int,
        artifact_type: str,
        file_path: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        checksum_sha256: Optional[str] = None,
        description: Optional[str] = None,
    ) -> int:
        """
        Add an artifact to a sweep.

        Args:
            sweep_db_id: Database ID of sweep
            artifact_type: Type of artifact (rf_csv, wifi_pcap, etc.)
            file_path: Path to artifact file
            file_size_bytes: File size in bytes
            checksum_sha256: SHA256 checksum
            description: Description of artifact

        Returns:
            Database ID of created artifact
        """
        with self.SessionLocal() as session:
            artifact = Artifact(
                sweep_id=sweep_db_id,
                artifact_type=artifact_type,
                file_path=file_path,
                file_size_bytes=file_size_bytes,
                checksum_sha256=checksum_sha256,
                description=description,
            )
            session.add(artifact)
            session.commit()
            session.refresh(artifact)
            return artifact.id

    def get_sweep_by_id(self, sweep_id: str) -> Optional[Dict]:
        """Get sweep by sweep_id."""
        with self.SessionLocal() as session:
            stmt = select(Sweep).where(Sweep.sweep_id == sweep_id)
            sweep = session.scalar(stmt)
            if not sweep:
                return None

            return {
                "id": sweep.id,
                "sweep_id": sweep.sweep_id,
                "client_name": sweep.client_name,
                "site": sweep.site,
                "room": sweep.room,
                "start_time": sweep.start_time,
                "end_time": sweep.end_time,
                "status": sweep.status,
                "gps_lat": sweep.gps_lat,
                "gps_lon": sweep.gps_lon,
                "notes": sweep.notes,
                "created_at": sweep.created_at,
            }

    def get_sweeps(
        self,
        client_name: Optional[str] = None,
        site: Optional[str] = None,
        room: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Query sweeps with optional filters."""
        with self.SessionLocal() as session:
            stmt = select(Sweep).order_by(desc(Sweep.start_time)).limit(limit)

            if client_name:
                stmt = stmt.where(Sweep.client_name == client_name)
            if site:
                stmt = stmt.where(Sweep.site == site)
            if room:
                stmt = stmt.where(Sweep.room == room)

            sweeps = session.scalars(stmt).all()

            return [
                {
                    "id": s.id,
                    "sweep_id": s.sweep_id,
                    "client_name": s.client_name,
                    "site": s.site,
                    "room": s.room,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "status": s.status,
                }
                for s in sweeps
            ]

    def get_events(
        self, sweep_db_id: int, event_type: Optional[str] = None, limit: int = 1000
    ) -> List[Dict]:
        """Get events for a sweep."""
        with self.SessionLocal() as session:
            stmt = (
                select(Event)
                .where(Event.sweep_id == sweep_db_id)
                .order_by(Event.timestamp)
                .limit(limit)
            )

            if event_type:
                stmt = stmt.where(Event.event_type == event_type)

            events = session.scalars(stmt).all()

            return [
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "timestamp": e.timestamp,
                    "freq_hz": e.freq_hz,
                    "power_db": e.power_db,
                    "mac_address": e.mac_address,
                    "ssid": e.ssid,
                    "metadata": json.loads(e.event_metadata) if e.event_metadata else None,
                }
                for e in events
            ]

    def get_artifacts(self, sweep_db_id: int) -> List[Dict]:
        """Get artifacts for a sweep."""
        with self.SessionLocal() as session:
            stmt = select(Artifact).where(Artifact.sweep_id == sweep_db_id)
            artifacts = session.scalars(stmt).all()

            return [
                {
                    "id": a.id,
                    "artifact_type": a.artifact_type,
                    "file_path": a.file_path,
                    "file_size_bytes": a.file_size_bytes,
                    "description": a.description,
                }
                for a in artifacts
            ]

    def insert_anomaly(
        self,
        sweep_id: int,
        event_id: Optional[int],
        kind: str,
        score: float,
        metadata: Optional[Dict] = None,
    ) -> int:
        """
        Insert an anomaly record.

        Args:
            sweep_id: Database ID of sweep
            event_id: Optional reference to specific event ID
            kind: Type of anomaly (freq_anomaly, rogue_ap, unknown_ble, etc.)
            score: Anomaly score (0.0 - 1.0)
            metadata: Additional metadata as dict

        Returns:
            Database ID of created anomaly
        """
        with self.SessionLocal() as session:
            anomaly = Anomaly(
                sweep_id=sweep_id,
                event_ref=event_id,
                kind=kind,
                score=score,
                anomaly_metadata=json.dumps(metadata) if metadata else None,
            )
            session.add(anomaly)
            session.commit()
            session.refresh(anomaly)
            return anomaly.id

    def get_anomalies(
        self, sweep_db_id: int, kind: Optional[str] = None, min_score: float = 0.0
    ) -> List[Dict]:
        """
        Get anomalies for a sweep.

        Args:
            sweep_db_id: Database ID of sweep
            kind: Optional filter by anomaly kind
            min_score: Minimum anomaly score to return

        Returns:
            List of anomaly records
        """
        with self.SessionLocal() as session:
            stmt = (
                select(Anomaly)
                .where(Anomaly.sweep_id == sweep_db_id)
                .where(Anomaly.score >= min_score)
                .order_by(desc(Anomaly.score))
            )

            if kind:
                stmt = stmt.where(Anomaly.kind == kind)

            anomalies = session.scalars(stmt).all()

            return [
                {
                    "id": a.id,
                    "event_ref": a.event_ref,
                    "kind": a.kind,
                    "score": a.score,
                    "metadata": json.loads(a.anomaly_metadata) if a.anomaly_metadata else None,
                    "created_at": a.created_at,
                }
                for a in anomalies
            ]
