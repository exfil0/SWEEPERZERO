# SWEEPERZERO

**Technical Surveillance Counter-Measures (TSCM) Toolkit**

A professional-grade Python application for detecting technical surveillance threats including RF bugs, rogue Wi-Fi access points, BLE tracking devices, and GSM cell site simulators (IMSI catchers).

## Features

- **RF Spectrum Analysis**: RTL-SDR and HackRF support for wide-spectrum RF sweeps
- **Wi-Fi Monitoring**: Detect rogue access points and anomalous clients
- **BLE Scanning**: Identify tracking beacons and suspicious BLE devices  
- **GSM Surveillance**: Scan for rogue base stations and IMSI catchers
- **GPS Tagging**: Geolocation of sweep data
- **SQLite Storage**: Structured event storage with WAL mode for performance
- **Parallel Sweeps**: Run multiple collectors concurrently
- **YAML Configuration**: Flexible, validated configuration with environment overrides
- **CLI Interface**: User-friendly command-line tools

---

## Table of Contents

- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Device Setup](#device-setup)
- [Architecture](#architecture)
- [Development](#development)
- [Security Considerations](#security-considerations)
- [Troubleshooting](#troubleshooting)
- [Privacy & Retention](#privacy--retention)

---

## Quick Start

```bash
# 1. Install dependencies (requires root/sudo)
sudo ./scripts/install.sh

# 2. Install Python package
pip install -e .

# 3. Initialize configuration
tscm init

# 4. Edit configuration
nano config.yaml

# 5. Verify devices
tscm preflight
tscm list-devices

# 6. Run a sweep
tscm sweep --kind rf --client acme --site hq --room ceo_office
```

---

## Installation

### System Requirements

- **OS**: Linux (Ubuntu 20.04+, Debian 11+, or similar)
- **Python**: 3.8 or higher
- **Hardware**: RTL-SDR, HackRF, BladeRF, Ubertooth, or compatible SDR devices
- **Storage**: 500MB minimum for application, varies for sweep data

### Automated Installation

The install script handles system dependencies:

```bash
sudo ./scripts/install.sh
```

This installs:
- RTL-SDR tools (`rtl_power`, `rtl_test`)
- HackRF tools (`hackrf_sweep`, `hackrf_info`)
- Aircrack-ng suite for Wi-Fi monitoring
- Ubertooth tools for BLE capture
- gr-gsm for GSM scanning (if available)
- GPSD for GPS integration

### Manual Installation

1. **Install system packages**:
   ```bash
   sudo apt install rtl-sdr hackrf aircrack-ng gpsd gpsd-clients \
                    bluez ubertooth python3 python3-pip
   ```

2. **Install Python package**:
   ```bash
   pip install -e .
   ```

3. **Verify installation**:
   ```bash
   tscm --help
   ```

### Docker Installation

```bash
# Build image
docker build -t sweeperzero -f deploy/Dockerfile .

# Run (requires USB device passthrough)
docker run --device=/dev/bus/usb --network host sweeperzero tscm preflight
```

---

## Configuration

### Create Config File

```bash
tscm init
```

This creates `config.yaml` with documented defaults.

### Configuration Structure

```yaml
# Client identification
client_name: acme_corp
base_dir: ~/.tscm/data/clients

# GPS
gps:
  enable_gps: true
  gpsd_host: 127.0.0.1
  gpsd_port: 2947

# Durations (seconds)
durations:
  rf_duration: 600      # 10 minutes
  wifi_duration: 900    # 15 minutes  
  ble_duration: 900     # 15 minutes
  gsm_duration: 600     # 10 minutes

# RTL-SDR configuration
rtl_sdr:
  enabled: true
  freq_start_mhz: 50
  freq_end_mhz: 1700
  bin_size_hz: 1000000
  interval_seconds: 10

# Wi-Fi configuration
wifi:
  enabled: true
  interface: wlan0

# BLE configuration
ble:
  enabled: true
  interface: ubertooth

# GSM configuration
gsm:
  enabled: false
  device_string: bladerf=0
  bands: EGSM900,DCS1800
  allowed_mcc_mnc:
    - "310-260"  # Example: T-Mobile US

# Storage
storage:
  database_path: ~/.tscm/data/sweeps.db
  enable_wal: true

# Orchestration
parallel_sweeps: true
```

### Environment Variable Overrides

Use `TSCM_*` prefix with `__` for nested keys:

```bash
export TSCM_CLIENT_NAME="special_client"
export TSCM_GPS__ENABLE_GPS=false
export TSCM_RTL_SDR__FREQ_START_MHZ=100
```

---

## Usage

### Preflight Checks

Verify device availability before sweeps:

```bash
tscm preflight
```

### List Devices

Enumerate detected hardware:

```bash
tscm list-devices
```

### Running Sweeps

#### RF Sweep (RTL-SDR)

```bash
tscm sweep --kind rf --client acme --site hq --room boardroom
```

This:
1. Creates a sweep record in the database
2. Runs `rtl_power` for configured duration
3. Parses CSV output line-by-line
4. Stores frequency/power events in SQLite
5. Saves raw CSV as artifact

#### All Sweeps (Orchestrated)

```bash
tscm sweep --kind all --client acme --site dc1 --room server_room
```

Runs all enabled collectors (RF, Wi-Fi, BLE, GSM) in parallel where feasible.

### Viewing Results

Results are stored in SQLite database (default: `~/.tscm/data/sweeps.db`).

Query with Python:

```python
from tscm.storage.store import SweepStore

store = SweepStore("~/.tscm/data/sweeps.db")

# List recent sweeps
sweeps = store.get_sweeps(limit=10)

# Get events from a sweep
events = store.get_events(sweep_db_id=1, event_type="rf", limit=100)
```

---

## Device Setup

### RTL-SDR

**Driver Blacklist**:

```bash
sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf <<EOF
blacklist dvb_usb_rtl28xxu
EOF
```

**Udev Rules** (non-root access):

```bash
sudo tee /etc/udev/rules.d/20-rtlsdr.rules <<EOF
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
EOF

sudo udevadm control --reload-rules
```

### HackRF

**Udev Rules**:

```bash
sudo tee /etc/udev/rules.d/53-hackrf.rules <<EOF
ATTR{idVendor}=="1d50", ATTR{idProduct}=="6089", MODE="0666", GROUP="plugdev"
EOF
```

**Test**:
```bash
hackrf_info
```

### Wi-Fi Adapter

**Monitor Mode Test**:

```bash
sudo airmon-ng start wlan0
```

**Recommended Adapters**: ALFA AWUS036ACH, TP-Link TL-WN722N v1

### Non-Root Operation

Use setcap for specific tools:

```bash
sudo setcap cap_net_raw,cap_net_admin=eip /usr/bin/rtl_power
```

Add user to groups:

```bash
sudo usermod -aG plugdev,dialout $USER
```

---

## Architecture

### Project Structure

```
SWEEPERZERO/
├── src/tscm/
│   ├── cli.py              # Typer CLI interface
│   ├── config.py           # Pydantic configuration models
│   ├── collectors/
│   │   ├── rf_parser.py    # rtl_power CSV parser
│   │   ├── hackrf.py       # HackRF/RTL-SDR integration
│   │   └── orchestrator.py # Multi-collector orchestration
│   └── storage/
│       ├── models.py       # SQLAlchemy models
│       └── store.py        # Storage API
├── tests/
├── scripts/install.sh
├── deploy/
└── config.example.yaml
```

### Data Flow

1. CLI Command → Parse arguments, load config
2. Create Sweep → Initialize database record
3. Run Collectors → Execute tools
4. Parse Output → Stream processing
5. Store Events → Bulk insert into SQLite
6. Update Sweep → Mark completion status

### Database Schema

- **sweeps**: Session metadata (client, site, room, timestamps, GPS)  
- **events**: Individual RF/Wi-Fi/BLE/GSM observations  
- **artifacts**: References to raw capture files

---

## Development

### Setup Dev Environment

```bash
git clone https://github.com/exfil0/SWEEPERZERO.git
cd SWEEPERZERO
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
pytest --cov=tscm
```

### Adding a New Collector

1. Create `src/tscm/collectors/your_collector.py`
2. Implement function: `run_your_sweep(config, store, sweep_db_id) -> bool`
3. Add to orchestrator
4. Write tests
5. Update config schema

---

## Security Considerations

### Best Practices

1. **Input Sanitization**: All inputs validated via pydantic
2. **No Shell Injection**: Use `subprocess` with argument lists
3. **Minimal Privileges**: Run as non-root (use udev rules)
4. **Secure Storage**: Database permissions should be 0600
5. **Audit Logging**: All activity logged with timestamps

### Capabilities Required

For non-root operation:
- `CAP_NET_RAW`: Raw socket access
- `CAP_NET_ADMIN`: Network configuration

### Known Limitations

- Wi-Fi: Requires monitor mode
- BLE: Ubertooth detection is probabilistic
- GSM: Scanning may be restricted in some jurisdictions
- RF: May miss narrow-band or frequency-hopping transmitters

---

## Troubleshooting

### "rtl_power not found"

```bash
sudo apt install rtl-sdr
```

### "Permission denied" accessing USB

Add udev rules and user to plugdev group, then log out/in.

### "No RTL-SDR device found"

Check device and blacklist DVB-T drivers.

### Wi-Fi monitor mode fails

```bash
sudo airmon-ng check kill
sudo airmon-ng start wlan0
```

### Database locked errors

Ensure only one sweep runs at a time. WAL mode should prevent this.

---

## Privacy & Retention

### Data Collected

- RF Events: Frequency, power, timestamp
- Wi-Fi: BSSID, SSID, signal strength, client MACs
- BLE: MAC addresses, advertisement data
- GSM: Cell IDs, MCC/MNC, LAC, power levels
- GPS: Latitude, longitude (if enabled)

### Legal Considerations

- RF scanning regulations vary by jurisdiction
- Ensure compliance with local wiretapping laws
- Treat collected data as potentially sensitive

**Disclaimer**: Users are responsible for legal compliance.

---

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Submit a pull request

### Development Priorities

- HackRF native parser
- Wi-Fi/BLE/GSM collector implementations
- Web dashboard for visualization
- Baseline/anomaly detection
- Report generation

---

## License

MIT License

---

## Acknowledgments

- RTL-SDR project
- HackRF project
- gr-gsm
- Ubertooth
- Aircrack-ng

---

**SWEEPERZERO** - Securing spaces, one sweep at a time.
