"""CLI interface for TSCM toolkit."""

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from tscm.config import load_config, save_example_config
from tscm.storage.store import SweepStore

app = typer.Typer(
    name="tscm",
    help="SWEEPERZERO - Technical Surveillance Counter-Measures toolkit",
    add_completion=False,
)
console = Console()


@app.command()
def init(
    config_path: Path = typer.Option(
        Path("config.yaml"),
        "--config",
        "-c",
        help="Path where to create config file",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing config file",
    ),
):
    """Initialize TSCM configuration."""
    if config_path.exists() and not force:
        rprint(
            f"[yellow]Config file already exists at {config_path}[/yellow]"
        )
        rprint("Use --force to overwrite")
        raise typer.Exit(1)

    try:
        save_example_config(config_path)
        rprint(f"[green]✓[/green] Created config file at {config_path}")
        rprint("\nNext steps:")
        rprint("  1. Edit config.yaml to customize settings")
        rprint("  2. Run 'tscm preflight' to check device availability")
        rprint("  3. Run 'tscm sweep --kind rf' to test RF collection")
    except Exception as e:
        rprint(f"[red]Error creating config: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def preflight(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config file",
    ),
):
    """Run preflight checks for devices and capabilities."""
    try:
        config = load_config(config_path)
    except Exception as e:
        rprint(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)

    rprint("[bold]TSCM Preflight Checks[/bold]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Notes", style="dim")

    checks = []

    # Check RTL-SDR
    rtl_power_path = shutil.which("rtl_power")
    if rtl_power_path:
        checks.append(("RTL-SDR (rtl_power)", "✓ Available", f"Found at {rtl_power_path}"))
    else:
        checks.append((
            "RTL-SDR (rtl_power)",
            "✗ Missing",
            "Install: apt install rtl-sdr",
        ))

    # Check HackRF
    hackrf_path = shutil.which("hackrf_sweep")
    if hackrf_path:
        # Try to detect device
        try:
            result = subprocess.run(
                ["hackrf_info"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                checks.append(("HackRF", "✓ Available", "Device detected"))
            else:
                checks.append(("HackRF", "⚠ Tool found", "No device detected"))
        except Exception:
            checks.append(("HackRF", "⚠ Tool found", "Cannot check device"))
    else:
        checks.append(("HackRF", "✗ Missing", "Install: apt install hackrf"))

    # Check GPSD
    if config.gps.enable_gps:
        gpspipe_path = shutil.which("gpspipe")
        if gpspipe_path:
            checks.append(("GPSD (gpspipe)", "✓ Available", f"Found at {gpspipe_path}"))
        else:
            checks.append((
                "GPSD (gpspipe)",
                "✗ Missing",
                "Install: apt install gpsd gpsd-clients",
            ))

    # Check Wi-Fi tools
    if config.wifi.enabled:
        airmon_path = shutil.which("airmon-ng")
        airodump_path = shutil.which("airodump-ng")
        if airmon_path and airodump_path:
            checks.append(("Wi-Fi (aircrack-ng)", "✓ Available", "airmon-ng and airodump-ng found"))
        else:
            checks.append((
                "Wi-Fi (aircrack-ng)",
                "✗ Missing",
                "Install: apt install aircrack-ng",
            ))

    # Check BLE (Ubertooth)
    if config.ble.enabled:
        ubertooth_path = shutil.which("ubertooth-btle")
        if ubertooth_path:
            checks.append(("BLE (Ubertooth)", "✓ Available", f"Found at {ubertooth_path}"))
        else:
            checks.append((
                "BLE (Ubertooth)",
                "✗ Missing",
                "Install: apt install ubertooth",
            ))

    # Check GSM tools
    if config.gsm.enabled:
        grgsm_path = shutil.which("grgsm_scanner")
        if grgsm_path:
            checks.append(("GSM (gr-gsm)", "✓ Available", f"Found at {grgsm_path}"))
        else:
            checks.append((
                "GSM (gr-gsm)",
                "✗ Missing",
                "Install: apt install gr-gsm (or compile from source)",
            ))

    # Check database
    db_path = Path(config.storage.database_path).expanduser()
    if db_path.parent.exists():
        checks.append(("Storage directory", "✓ Available", str(db_path.parent)))
    else:
        checks.append((
            "Storage directory",
            "⚠ Will create",
            f"{db_path.parent}",
        ))

    for component, status, notes in checks:
        table.add_row(component, status, notes)

    console.print(table)

    # Summary
    available = sum(1 for _, status, _ in checks if "✓" in status)
    missing = sum(1 for _, status, _ in checks if "✗" in status)
    warnings = sum(1 for _, status, _ in checks if "⚠" in status)

    rprint(f"\n[bold]Summary:[/bold] {available} available, {warnings} warnings, {missing} missing")

    if missing > 0:
        rprint("\n[yellow]Some components are missing. Install them to use all features.[/yellow]")
        rprint("See: scripts/install.sh or README.md for installation instructions")


@app.command(name="list-devices")
def list_devices():
    """List detected SDR and security devices."""
    rprint("[bold]Detected Devices[/bold]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Type", style="cyan")
    table.add_column("Device", style="white")
    table.add_column("Details", style="dim")

    devices_found = []

    # Check for RTL-SDR devices
    rtl_test = shutil.which("rtl_test")
    if rtl_test:
        try:
            result = subprocess.run(
                [rtl_test, "-t"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if "Found" in result.stderr:
                devices_found.append(("RTL-SDR", "Detected", result.stderr.split("\n")[0]))
        except Exception:
            pass

    # Check for HackRF
    hackrf_info = shutil.which("hackrf_info")
    if hackrf_info:
        try:
            result = subprocess.run(
                [hackrf_info],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and "Serial number" in result.stdout:
                serial_line = [line for line in result.stdout.split("\n") if "Serial number" in line]
                devices_found.append(("HackRF", "Detected", serial_line[0] if serial_line else ""))
        except Exception:
            pass

    # Check for BladeRF
    bladerf_cli = shutil.which("bladeRF-cli")
    if bladerf_cli:
        try:
            result = subprocess.run(
                [bladerf_cli, "-p"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                devices_found.append(("BladeRF", "Detected", "Use 'bladeRF-cli -p' for details"))
        except Exception:
            pass

    # Check for Ubertooth
    ubertooth_util = shutil.which("ubertooth-util")
    if ubertooth_util:
        try:
            result = subprocess.run(
                [ubertooth_util, "-v"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                devices_found.append(("Ubertooth", "Detected", "BLE capture device"))
        except Exception:
            pass

    # Check for Wi-Fi interfaces
    try:
        result = subprocess.run(
            ["iwconfig"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            wifi_ifaces = [
                line.split()[0]
                for line in result.stdout.split("\n")
                if "IEEE 802.11" in line or "no wireless" not in line.lower()
            ]
            for iface in wifi_ifaces:
                if iface:
                    devices_found.append(("Wi-Fi", iface, "Wireless interface"))
    except Exception:
        pass

    if devices_found:
        for dev_type, device, details in devices_found:
            table.add_row(dev_type, device, details)
        console.print(table)
    else:
        rprint("[yellow]No devices detected. Make sure tools are installed and devices are connected.[/yellow]")


@app.command()
def sweep(
    kind: str = typer.Option(
        "rf",
        "--kind",
        "-k",
        help="Type of sweep: rf, wifi, ble, gsm, all",
    ),
    client: Optional[str] = typer.Option(
        None,
        "--client",
        help="Client name (overrides config)",
    ),
    site: Optional[str] = typer.Option(
        None,
        "--site",
        help="Site name",
    ),
    room: Optional[str] = typer.Option(
        None,
        "--room",
        help="Room name",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config file",
    ),
):
    """Run a TSCM sweep."""
    try:
        config = load_config(config_path)
    except Exception as e:
        rprint(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)

    # Override config with CLI args
    if client:
        config.client_name = client

    # Initialize storage
    try:
        store = SweepStore(config.storage.database_path, config.storage.enable_wal)
    except OSError as e:
        rprint(f"[red]Error initializing storage: {e}[/red]")
        raise typer.Exit(1)

    # Create sweep ID
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    sweep_id = f"{config.client_name}_{site or 'unknown'}_{room or 'unknown'}_{timestamp}"

    rprint(f"[bold]Starting sweep: {sweep_id}[/bold]")
    rprint(f"Kind: {kind}")
    rprint(f"Client: {config.client_name}")
    if site:
        rprint(f"Site: {site}")
    if room:
        rprint(f"Room: {room}")
    rprint()

    # Create sweep in database
    try:
        sweep_db_id = store.create_sweep(
            sweep_id=sweep_id,
            client_name=config.client_name,
            site=site,
            room=room,
        )
        rprint(f"[green]✓[/green] Created sweep record (ID: {sweep_db_id})")
    except Exception as e:
        rprint(f"[red]Error creating sweep: {e}[/red]")
        raise typer.Exit(1)

    # Import collectors
    try:
        from tscm.collectors.hackrf import run_hackrf_sweep
        from tscm.collectors.orchestrator import run_all_sweeps
    except ImportError as e:
        rprint(f"[red]Error importing collectors: {e}[/red]")
        raise typer.Exit(1)

    # Run sweep based on kind
    success = False
    try:
        if kind == "rf":
            rprint("[cyan]Running RF sweep with RTL-SDR...[/cyan]")
            success = run_hackrf_sweep(config, store, sweep_db_id)
        elif kind == "all":
            rprint("[cyan]Running all sweeps...[/cyan]")
            success = run_all_sweeps(config, store, sweep_db_id)
        else:
            rprint(f"[red]Unknown sweep kind: {kind}[/red]")
            rprint("Available kinds: rf, wifi, ble, gsm, all")
            raise typer.Exit(1)

        if success:
            store.update_sweep(sweep_db_id, end_time=datetime.now(timezone.utc), status="completed")
            rprint("\n[green]✓ Sweep completed successfully[/green]")
            rprint(f"Sweep ID: {sweep_id}")
        else:
            store.update_sweep(sweep_db_id, status="failed")
            rprint("\n[yellow]⚠ Sweep completed with warnings[/yellow]")

    except KeyboardInterrupt:
        rprint("\n[yellow]Sweep interrupted by user[/yellow]")
        store.update_sweep(sweep_db_id, end_time=datetime.now(timezone.utc), status="failed")
        raise typer.Exit(1)
    except Exception as e:
        rprint(f"\n[red]Error during sweep: {e}[/red]")
        store.update_sweep(sweep_db_id, end_time=datetime.now(timezone.utc), status="failed")
        raise typer.Exit(1)


@app.command()
def baseline(
    client: str = typer.Option(
        ...,
        "--client",
        help="Client name for baseline",
    ),
    site: Optional[str] = typer.Option(
        None,
        "--site",
        help="Site name",
    ),
    room: Optional[str] = typer.Option(
        None,
        "--room",
        help="Room name",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file for baseline JSON",
    ),
    days_back: int = typer.Option(
        30,
        "--days",
        help="Number of days to look back for sweeps",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config file",
    ),
):
    """Create RF baseline from historical sweeps."""
    try:
        config = load_config(config_path)
    except Exception as e:
        rprint(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)

    try:
        from tscm.baseline import create_baseline, get_baseline_sweeps

        store = SweepStore(config.storage.database_path, config.storage.enable_wal)

        rprint(f"[bold]Creating baseline for {client}[/bold]")
        if site:
            rprint(f"Site: {site}")
        if room:
            rprint(f"Room: {room}")
        rprint()

        # Get suitable sweeps
        sweep_ids = get_baseline_sweeps(
            store,
            client_name=client,
            site=site,
            room=room,
            days_back=days_back,
            min_sweeps=3,
        )

        if not sweep_ids:
            rprint("[yellow]No completed sweeps found for baseline[/yellow]")
            raise typer.Exit(1)

        rprint(f"Found {len(sweep_ids)} sweeps for baseline")

        # Create baseline
        baseline = create_baseline(
            store,
            sweep_ids,
            freq_bin_mhz=1.0,
            output_path=output,
        )

        rprint(f"[green]✓[/green] Baseline created with {len(baseline['frequencies'])} frequency bins")

        if output:
            rprint(f"[green]✓[/green] Baseline saved to {output}")

    except ImportError as e:
        rprint(f"[red]Error importing baseline module: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        rprint(f"[red]Error creating baseline: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def report(
    sweep_id: str = typer.Argument(..., help="Sweep ID to generate report for"),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path",
    ),
    format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Report format: text, json, html",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config file",
    ),
):
    """Generate a report for a sweep."""
    try:
        config = load_config(config_path)
    except Exception as e:
        rprint(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)

    try:
        from tscm.report import generate_html_report, generate_json_report, generate_text_report

        store = SweepStore(config.storage.database_path, config.storage.enable_wal)

        # Get sweep by ID
        sweep = store.get_sweep_by_id(sweep_id)
        if not sweep:
            rprint(f"[red]Sweep {sweep_id} not found[/red]")
            raise typer.Exit(1)

        rprint(f"[bold]Generating {format} report for {sweep_id}[/bold]\n")

        # Generate report based on format
        if format == "text":
            report_text = generate_text_report(store, sweep["id"], output)
            if not output:
                rprint(report_text)
        elif format == "json":
            generate_json_report(store, sweep["id"], output)
        elif format == "html":
            generate_html_report(store, sweep["id"], output)
        else:
            rprint(f"[red]Unknown format: {format}[/red]")
            rprint("Available formats: text, json, html")
            raise typer.Exit(1)

        if output:
            rprint(f"\n[green]✓[/green] Report saved to {output}")

    except ImportError as e:
        rprint(f"[red]Error importing report module: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        rprint(f"[red]Error generating report: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def dashboard(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host to bind to",
    ),
    port: int = typer.Option(
        5000,
        "--port",
        "-p",
        help="Port to listen on",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config file",
    ),
):
    """Start the web dashboard."""
    try:
        from tscm.dashboard.app import run_dashboard

        rprint("[bold]Starting TSCM Dashboard[/bold]")
        rprint(f"URL: http://{host}:{port}")
        rprint("\nPress Ctrl+C to stop")
        rprint()

        run_dashboard(host=host, port=port, config_path=config_path)

    except ImportError as e:
        rprint(f"[red]Error: {e}[/red]")
        rprint("The dashboard requires Flask. Install with: pip install flask")
        raise typer.Exit(1)
    except KeyboardInterrupt:
        rprint("\n[yellow]Dashboard stopped[/yellow]")
    except Exception as e:
        rprint(f"[red]Error starting dashboard: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
