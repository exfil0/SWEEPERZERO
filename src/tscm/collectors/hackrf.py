"""HackRF and RTL-SDR RF collectors."""

import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from tscm.collectors.rf_parser import RTLPowerParser
from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


def run_rtl_power_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run rtl_power sweep and parse results.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save raw CSV (for artifact tracking)

    Returns:
        True if successful
    """
    if not config.rtl_sdr.enabled:
        print("RTL-SDR is disabled in config")
        return False

    # Build rtl_power command
    freq_start_hz = int(config.rtl_sdr.freq_start_mhz * 1e6)
    freq_end_hz = int(config.rtl_sdr.freq_end_mhz * 1e6)
    bin_size_hz = int(config.rtl_sdr.bin_size_hz)
    interval_sec = config.rtl_sdr.interval_seconds
    duration_sec = config.durations.rf_duration

    cmd = [
        "rtl_power",
        "-f",
        f"{freq_start_hz}:{freq_end_hz}:{bin_size_hz}",
        "-i",
        str(interval_sec),
        "-e",
        str(duration_sec),
        "-",  # Output to stdout
    ]

    print(f"Running: {' '.join(cmd)}")
    print(f"Duration: {duration_sec} seconds")

    # Create temp file if output_dir specified
    output_file = None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")
        output_file = output_dir / f"rtl_power_{timestamp}.csv"

    try:
        # Run rtl_power and stream output
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )

        parser = RTLPowerParser(strict=False)
        events_batch = []
        batch_size = 100

        file_handle = None
        if output_file:
            file_handle = open(output_file, "w")

        # Process output line by line
        for line in process.stdout:
            # Save to file if requested
            if file_handle:
                file_handle.write(line)

            # Parse line
            event = parser.parse_line(line)
            if event is None:
                continue

            # Convert to database events (one per frequency bin)
            for freq_hz, power_db in event.freq_bins:
                events_batch.append({
                    "event_type": "rf",
                    "timestamp": event.timestamp,
                    "freq_hz": freq_hz,
                    "power_db": power_db,
                    "bandwidth_hz": event.freq_step_hz,
                })

            # Bulk insert when batch is full
            if len(events_batch) >= batch_size:
                store.add_events_bulk(sweep_db_id, events_batch)
                print(f"Stored {len(events_batch)} RF events")
                events_batch = []

        # Close file
        if file_handle:
            file_handle.close()

        # Wait for process to complete
        process.wait()

        # Store remaining events
        if events_batch:
            store.add_events_bulk(sweep_db_id, events_batch)
            print(f"Stored {len(events_batch)} RF events")

        # Add artifact record
        if output_file and output_file.exists():
            store.add_artifact(
                sweep_db_id,
                artifact_type="rtl_power_csv",
                file_path=str(output_file),
                file_size_bytes=output_file.stat().st_size,
                description=f"RTL-SDR rtl_power sweep {freq_start_hz/1e6:.0f}-{freq_end_hz/1e6:.0f} MHz",
            )

        print(f"RTL-SDR sweep completed. Parsed {parser.lines_parsed} lines, skipped {parser.lines_skipped}")

        if parser.errors:
            print(f"Warnings: {len(parser.errors)} parse errors occurred")

        return process.returncode == 0

    except FileNotFoundError:
        print("Error: rtl_power not found. Install with: apt install rtl-sdr")
        return False
    except KeyboardInterrupt:
        print("\nRTL-SDR sweep interrupted")
        if process:
            process.terminate()
            process.wait()
        return False
    except Exception as e:
        print(f"Error during RTL-SDR sweep: {e}")
        return False


def run_hackrf_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run HackRF sweep.

    Note: HackRF uses a different output format than rtl_power.
    This is a stub implementation. TODO: Implement HackRF parser.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save raw data

    Returns:
        True if successful
    """
    if not config.hackrf.enabled:
        print("HackRF is disabled in config")
        return False

    # For now, fall back to rtl_power if available
    print("Note: HackRF parser not yet implemented, using RTL-SDR instead")
    return run_rtl_power_sweep(config, store, sweep_db_id, output_dir)

    # TODO: Implement HackRF sweep parser
    # HackRF output format is different from rtl_power
    # Format: date, time, hz_low, hz_high, hz_bin_width, num_samples, dB, dB, ...
    # See: https://github.com/mossmann/hackrf/wiki/hackrf_sweep
