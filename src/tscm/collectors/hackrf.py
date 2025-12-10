"""HackRF and RTL-SDR RF collectors."""

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tscm.collectors.hackrf_parser import HackRFParser
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
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
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

        try:
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
        finally:
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
        return False
    except Exception as e:
        print(f"Error during RTL-SDR sweep: {e}")
        return False


def run_hackrf_native_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run native HackRF sweep using hackrf_sweep.

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

    # Check if hackrf_sweep is available
    hackrf_sweep_path = shutil.which("hackrf_sweep")
    if not hackrf_sweep_path:
        print("hackrf_sweep not found, falling back to RTL-SDR")
        return run_rtl_power_sweep(config, store, sweep_db_id, output_dir)

    # Build hackrf_sweep command for each configured band
    duration_sec = config.durations.rf_duration
    all_success = True

    for band in config.hackrf.bands:
        freq_start_mhz = int(band.freq_start_mhz)
        freq_end_mhz = int(band.freq_end_mhz)
        
        # hackrf_sweep uses -f for frequency range in MHz
        cmd = [
            "hackrf_sweep",
            "-f",
            f"{freq_start_mhz}:{freq_end_mhz}",
            "-w",
            str(int(band.step_mhz * 1e6)),  # Convert MHz to Hz for bin width
        ]

        print(f"Running HackRF sweep: {band.label} ({freq_start_mhz}-{freq_end_mhz} MHz)")
        print(f"Command: {' '.join(cmd)}")
        print(f"Duration: {duration_sec} seconds")

        # Create temp file if output_dir specified
        output_file = None
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
            output_file = output_dir / f"hackrf_sweep_{band.label}_{timestamp}.csv"

        try:
            # Run hackrf_sweep and stream output
            # Note: hackrf_sweep writes to stdout by default
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )

            parser = HackRFParser(strict=False)
            events_batch = []
            batch_size = 100

            file_handle = None
            if output_file:
                file_handle = open(output_file, "w")

            try:
                import time
                start_time = time.time()
                
                # Process output line by line until duration expires
                for line in process.stdout:
                    # Check if duration exceeded
                    if time.time() - start_time > duration_sec:
                        process.terminate()
                        break

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
                            "bandwidth_hz": event.bin_width_hz,
                        })

                    # Bulk insert when batch is full
                    if len(events_batch) >= batch_size:
                        store.add_events_bulk(sweep_db_id, events_batch)
                        print(f"Stored {len(events_batch)} RF events")
                        events_batch = []
            finally:
                # Close file
                if file_handle:
                    file_handle.close()

                # Wait for process to complete
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

            # Store remaining events
            if events_batch:
                store.add_events_bulk(sweep_db_id, events_batch)
                print(f"Stored {len(events_batch)} RF events")

            # Add artifact record
            if output_file and output_file.exists():
                store.add_artifact(
                    sweep_db_id,
                    artifact_type="hackrf_sweep_csv",
                    file_path=str(output_file),
                    file_size_bytes=output_file.stat().st_size,
                    description=f"HackRF sweep {band.label} {freq_start_mhz}-{freq_end_mhz} MHz",
                )

            print(f"HackRF sweep {band.label} completed. Parsed {parser.lines_parsed} lines, skipped {parser.lines_skipped}")

            if parser.errors:
                print(f"Warnings: {len(parser.errors)} parse errors occurred")

            if process.returncode not in (0, None, -15):  # -15 is SIGTERM (expected when we terminate)
                all_success = False

        except FileNotFoundError:
            print("Error: hackrf_sweep not found")
            all_success = False
        except KeyboardInterrupt:
            print("\nHackRF sweep interrupted")
            all_success = False
        except Exception as e:
            print(f"Error during HackRF sweep: {e}")
            all_success = False

    return all_success


def run_hackrf_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run HackRF sweep with automatic fallback to RTL-SDR.

    This function tries to use native hackrf_sweep first. If HackRF is not
    available, it falls back to rtl_power.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save raw data

    Returns:
        True if successful
    """
    if not config.hackrf.enabled and not config.rtl_sdr.enabled:
        print("Both HackRF and RTL-SDR are disabled in config")
        return False

    # Try HackRF native first if enabled
    if config.hackrf.enabled:
        hackrf_sweep_path = shutil.which("hackrf_sweep")
        if hackrf_sweep_path:
            print("Using native HackRF sweep")
            return run_hackrf_native_sweep(config, store, sweep_db_id, output_dir)
        else:
            print("hackrf_sweep not found")

    # Fall back to RTL-SDR if available
    if config.rtl_sdr.enabled:
        rtl_power_path = shutil.which("rtl_power")
        if rtl_power_path:
            print("Falling back to RTL-SDR (rtl_power)")
            return run_rtl_power_sweep(config, store, sweep_db_id, output_dir)
        else:
            print("rtl_power not found")

    print("No RF collection tools available (tried hackrf_sweep and rtl_power)")
    return False
