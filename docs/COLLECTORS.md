# SWEEPERZERO Collectors Documentation

This document describes the collectors implemented in the SWEEPERZERO TSCM toolkit.

## Overview

SWEEPERZERO supports multiple signal collection types:
- **RF Spectrum**: HackRF and RTL-SDR for wide-spectrum sweeps
- **Wi-Fi**: Airodump-ng and scapy for Wi-Fi monitoring
- **BLE**: Ubertooth, hcitool, and bleak for Bluetooth Low Energy scanning
- **GSM**: gr-gsm for cellular network monitoring

## HackRF Collector

### Native HackRF Parser

The HackRF collector provides native parsing of `hackrf_sweep` output with automatic fallback to `rtl_power`.

**Features:**
- Parses hackrf_sweep CSV format (date, time, hz_low, hz_high, hz_bin_width, num_samples, dB readings)
- Supports wide frequency ranges (1 MHz - 6 GHz)
- Handles multiple frequency bands per sweep
- Falls back to RTL-SDR when HackRF unavailable

**Usage:**
```bash
# Run RF sweep (automatically selects best available tool)
tscm sweep --kind rf --client acme --site hq --room boardroom
```

**Configuration:**
```yaml
hackrf:
  enabled: true
  bands:
    - freq_start_mhz: 25
      freq_end_mhz: 300
      step_mhz: 5
      label: rf_hackrf_low
```

## Data Storage

All events are stored in SQLite with the following structure for each collector type.

For complete API documentation, see the inline documentation in `src/tscm/storage/store.py`.
