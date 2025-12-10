"""Configuration management with YAML, environment overrides, and validation."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RFBandConfig(BaseModel):
    """Configuration for a single RF band sweep."""

    freq_start_mhz: float = Field(..., description="Start frequency in MHz")
    freq_end_mhz: float = Field(..., description="End frequency in MHz")
    step_mhz: float = Field(..., description="Step size in MHz")
    label: str = Field(..., description="Label for this band")


class CollectorDurations(BaseModel):
    """Duration settings for each collector type."""

    rf_duration: int = Field(default=600, description="RF sweep duration in seconds")
    wifi_duration: int = Field(default=900, description="Wi-Fi capture duration in seconds")
    ble_duration: int = Field(default=900, description="BLE capture duration in seconds")
    gsm_duration: int = Field(default=600, description="GSM scan duration in seconds")


class GPSConfig(BaseModel):
    """GPS configuration."""

    enable_gps: bool = Field(default=True, description="Enable GPS tagging")
    gpsd_host: str = Field(default="127.0.0.1", description="GPSD host")
    gpsd_port: int = Field(default=2947, description="GPSD port")


class HackRFConfig(BaseModel):
    """HackRF-specific configuration."""

    enabled: bool = Field(default=True, description="Enable HackRF sweeps")
    bands: List[RFBandConfig] = Field(
        default_factory=lambda: [
            RFBandConfig(
                freq_start_mhz=25, freq_end_mhz=300, step_mhz=5, label="rf_hackrf_low"
            ),
            RFBandConfig(
                freq_start_mhz=300, freq_end_mhz=1200, step_mhz=5, label="rf_hackrf_mid"
            ),
            RFBandConfig(
                freq_start_mhz=1200, freq_end_mhz=6000, step_mhz=10, label="rf_hackrf_high"
            ),
        ]
    )


class RTLSDRConfig(BaseModel):
    """RTL-SDR configuration."""

    enabled: bool = Field(default=True, description="Enable RTL-SDR (rtl_power) sweeps")
    freq_start_mhz: float = Field(default=50, description="Start frequency in MHz")
    freq_end_mhz: float = Field(default=1700, description="End frequency in MHz")
    bin_size_hz: float = Field(default=1e6, description="Frequency bin size in Hz")
    interval_seconds: int = Field(default=10, description="Integration interval in seconds")


class WiFiConfig(BaseModel):
    """Wi-Fi configuration."""

    enabled: bool = Field(default=True, description="Enable Wi-Fi monitoring")
    interface: str = Field(default="wlan0", description="Wi-Fi interface name")


class BLEConfig(BaseModel):
    """BLE configuration."""

    enabled: bool = Field(default=True, description="Enable BLE monitoring")
    interface: str = Field(default="ubertooth", description="BLE device type (ubertooth, hci0)")


class GSMConfig(BaseModel):
    """GSM configuration."""

    enabled: bool = Field(default=False, description="Enable GSM scanning")
    device_string: str = Field(default="bladerf=0", description="OsmoSDR device string")
    bands: str = Field(default="EGSM900,DCS1800", description="GSM bands to scan")
    allowed_mcc_mnc: List[str] = Field(
        default_factory=list, description="Allowed MCC-MNC pairs (e.g., ['655-01', '655-07'])"
    )


class StorageConfig(BaseModel):
    """Storage configuration."""

    database_path: str = Field(
        default="~/.tscm/data/sweeps.db", description="Path to SQLite database"
    )
    enable_wal: bool = Field(default=True, description="Enable SQLite WAL mode")


class TSCMConfig(BaseSettings):
    """Main TSCM configuration."""

    model_config = SettingsConfigDict(
        env_prefix="TSCM_",
        env_nested_delimiter="__",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Client/project identification
    client_name: str = Field(default="default_client", description="Client name")
    base_dir: str = Field(
        default="~/.tscm/data/clients", description="Base directory for sweep data"
    )

    # Component configurations
    gps: GPSConfig = Field(default_factory=GPSConfig)
    durations: CollectorDurations = Field(default_factory=CollectorDurations)
    hackrf: HackRFConfig = Field(default_factory=HackRFConfig)
    rtl_sdr: RTLSDRConfig = Field(default_factory=RTLSDRConfig)
    wifi: WiFiConfig = Field(default_factory=WiFiConfig)
    ble: BLEConfig = Field(default_factory=BLEConfig)
    gsm: GSMConfig = Field(default_factory=GSMConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    # Orchestration
    parallel_sweeps: bool = Field(
        default=True, description="Run compatible sweeps in parallel"
    )

    @field_validator("base_dir", "storage")
    @classmethod
    def expand_paths(cls, v: Any) -> Any:
        """Expand ~ and environment variables in paths."""
        if isinstance(v, str):
            return os.path.expanduser(os.path.expandvars(v))
        elif isinstance(v, StorageConfig):
            v.database_path = os.path.expanduser(os.path.expandvars(v.database_path))
        return v


def load_config(config_path: Optional[Path] = None) -> TSCMConfig:
    """
    Load configuration with proper precedence.

    Load order:
    1. Default values from pydantic models
    2. YAML file (if provided or found in default locations)
    3. Environment variables (TSCM_* prefix)
    4. .env file (if present)

    Args:
        config_path: Optional path to YAML config file

    Returns:
        TSCMConfig instance
    """
    yaml_data: Dict[str, Any] = {}

    # Try to find config file
    if config_path is None:
        # Look in common locations
        search_paths = [
            Path("config.yaml"),
            Path("~/.tscm/config.yaml").expanduser(),
            Path("/etc/tscm/config.yaml"),
        ]
        for path in search_paths:
            if path.exists():
                config_path = path
                break

    # Load YAML if found
    if config_path and config_path.exists():
        with open(config_path) as f:
            yaml_data = yaml.safe_load(f) or {}

    # Merge with environment variables (pydantic_settings handles this)
    # Environment variables take precedence over YAML
    config = TSCMConfig(**yaml_data)

    return config


def save_example_config(path: Path) -> None:
    """Save an example configuration file."""
    example_config = TSCMConfig()
    config_dict = example_config.model_dump()

    with open(path, "w") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
