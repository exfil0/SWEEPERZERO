"""Report generation module for sweep results."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from tscm.storage.store import SweepStore


def generate_text_report(
    store: SweepStore,
    sweep_id: int,
    output_path: Optional[Path] = None,
) -> str:
    """
    Generate a text report for a sweep.

    Args:
        store: Storage instance
        sweep_id: Database ID of sweep
        output_path: Optional path to save report

    Returns:
        Report text
    """
    # Get sweep details
    sweep = store.get_sweep_by_id(str(sweep_id))
    if not sweep:
        raise ValueError(f"Sweep {sweep_id} not found")

    # Build report
    lines = []
    lines.append("=" * 80)
    lines.append("TSCM SWEEP REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Sweep ID: {sweep['sweep_id']}")
    lines.append(f"Client: {sweep['client_name']}")
    if sweep["site"]:
        lines.append(f"Site: {sweep['site']}")
    if sweep["room"]:
        lines.append(f"Room: {sweep['room']}")
    lines.append(f"Status: {sweep['status']}")
    lines.append(f"Start Time: {sweep['start_time']}")
    if sweep["end_time"]:
        lines.append(f"End Time: {sweep['end_time']}")
    if sweep["gps_lat"] and sweep["gps_lon"]:
        lines.append(f"GPS: {sweep['gps_lat']:.6f}, {sweep['gps_lon']:.6f}")
    lines.append("")

    # Get events summary
    lines.append("-" * 80)
    lines.append("EVENTS SUMMARY")
    lines.append("-" * 80)

    event_types = ["rf", "wifi", "ble", "gsm"]
    for event_type in event_types:
        events = store.get_events(sweep["id"], event_type=event_type, limit=10000)
        lines.append(f"{event_type.upper()}: {len(events)} events")

        if event_type == "rf" and events:
            # RF statistics
            powers = [e["power_db"] for e in events if e["power_db"] is not None]
            if powers:
                lines.append(f"  Power range: {min(powers):.1f} to {max(powers):.1f} dB")
                lines.append(f"  Mean power: {sum(powers)/len(powers):.1f} dB")

        elif event_type == "wifi" and events:
            # Wi-Fi statistics
            unique_bssids = set(e["mac_address"] for e in events if e["mac_address"])
            lines.append(f"  Unique BSSIDs: {len(unique_bssids)}")
            ssids = [e["ssid"] for e in events if e["ssid"]]
            if ssids:
                lines.append(f"  SSIDs detected: {len(set(ssids))}")

        elif event_type == "ble" and events:
            # BLE statistics
            unique_macs = set(e["mac_address"] for e in events if e["mac_address"])
            lines.append(f"  Unique BLE devices: {len(unique_macs)}")

        elif event_type == "gsm" and events:
            # GSM statistics
            unique_cells = set(
                (e["mcc"], e["mnc"], e["lac"], e["cid"])
                for e in events
                if e["mcc"] is not None
            )
            lines.append(f"  Unique cells: {len(unique_cells)}")

    lines.append("")

    # Get anomalies
    anomalies = store.get_anomalies(sweep["id"], min_score=0.3)
    lines.append("-" * 80)
    lines.append(f"ANOMALIES ({len(anomalies)})")
    lines.append("-" * 80)

    if anomalies:
        for anomaly in anomalies[:20]:  # Top 20
            lines.append(f"[{anomaly['score']:.2f}] {anomaly['kind']}")
            if anomaly["metadata"]:
                details = anomaly["metadata"].get("details", "")
                if details:
                    lines.append(f"  {details}")
    else:
        lines.append("No significant anomalies detected")

    lines.append("")

    # Get artifacts
    artifacts = store.get_artifacts(sweep["id"])
    lines.append("-" * 80)
    lines.append(f"ARTIFACTS ({len(artifacts)})")
    lines.append("-" * 80)

    for artifact in artifacts:
        size_mb = artifact["file_size_bytes"] / (1024 * 1024) if artifact["file_size_bytes"] else 0
        lines.append(
            f"{artifact['artifact_type']}: {artifact['file_path']} ({size_mb:.2f} MB)"
        )

    lines.append("")
    lines.append("=" * 80)
    lines.append(f"Report generated: {datetime.utcnow().isoformat()}")
    lines.append("=" * 80)

    report_text = "\n".join(lines)

    # Save to file if requested
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report_text)
        print(f"Report saved to {output_path}")

    return report_text


def generate_json_report(
    store: SweepStore,
    sweep_id: int,
    output_path: Optional[Path] = None,
) -> Dict:
    """
    Generate a JSON report for a sweep.

    Args:
        store: Storage instance
        sweep_id: Database ID of sweep
        output_path: Optional path to save report

    Returns:
        Report dictionary
    """
    # Get sweep details
    sweep = store.get_sweep_by_id(str(sweep_id))
    if not sweep:
        raise ValueError(f"Sweep {sweep_id} not found")

    # Build report
    report = {
        "sweep": sweep,
        "events": {},
        "anomalies": store.get_anomalies(sweep["id"]),
        "artifacts": store.get_artifacts(sweep["id"]),
        "generated_at": datetime.utcnow().isoformat(),
    }

    # Get events by type
    event_types = ["rf", "wifi", "ble", "gsm"]
    for event_type in event_types:
        events = store.get_events(sweep["id"], event_type=event_type, limit=1000)
        report["events"][event_type] = events

    # Save to file if requested
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"JSON report saved to {output_path}")

    return report


def generate_html_report(
    store: SweepStore,
    sweep_id: int,
    output_path: Optional[Path] = None,
    template_path: Optional[Path] = None,
) -> str:
    """
    Generate an HTML report for a sweep.

    Args:
        store: Storage instance
        sweep_id: Database ID of sweep
        output_path: Optional path to save report
        template_path: Optional path to HTML template

    Returns:
        HTML report string
    """
    # Get data
    json_data = generate_json_report(store, sweep_id)

    # Load template
    if template_path and template_path.exists():
        with open(template_path) as f:
            template = f.read()
    else:
        # Use default template
        template = _get_default_html_template()

    # Simple template substitution
    html = template.replace("{{SWEEP_DATA}}", json.dumps(json_data, default=str))

    # Save to file if requested
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(html)
        print(f"HTML report saved to {output_path}")

    return html


def _get_default_html_template() -> str:
    """Get default HTML template."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>TSCM Sweep Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #333; }
        table { border-collapse: collapse; width: 100%; margin: 20px 0; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #4CAF50; color: white; }
        .anomaly { background-color: #ffebee; }
        .score-high { color: red; font-weight: bold; }
        .score-medium { color: orange; }
        .score-low { color: green; }
    </style>
</head>
<body>
    <h1>TSCM Sweep Report</h1>
    <div id="report-content">
        <p>Loading report data...</p>
    </div>
    <script>
        const sweepData = {{SWEEP_DATA}};
        
        function renderReport() {
            const sweep = sweepData.sweep;
            const anomalies = sweepData.anomalies;
            
            let html = '<h2>Sweep Details</h2>';
            html += '<table>';
            html += '<tr><th>Field</th><th>Value</th></tr>';
            html += `<tr><td>Sweep ID</td><td>${sweep.sweep_id}</td></tr>`;
            html += `<tr><td>Client</td><td>${sweep.client_name}</td></tr>`;
            html += `<tr><td>Status</td><td>${sweep.status}</td></tr>`;
            html += `<tr><td>Start Time</td><td>${sweep.start_time}</td></tr>`;
            html += '</table>';
            
            html += `<h2>Anomalies (${anomalies.length})</h2>`;
            if (anomalies.length > 0) {
                html += '<table>';
                html += '<tr><th>Score</th><th>Type</th><th>Details</th></tr>';
                for (const anomaly of anomalies) {
                    const scoreClass = anomaly.score > 0.7 ? 'score-high' : anomaly.score > 0.4 ? 'score-medium' : 'score-low';
                    html += `<tr class="anomaly">`;
                    html += `<td class="${scoreClass}">${anomaly.score.toFixed(2)}</td>`;
                    html += `<td>${anomaly.kind}</td>`;
                    html += `<td>${anomaly.metadata?.details || 'N/A'}</td>`;
                    html += '</tr>';
                }
                html += '</table>';
            } else {
                html += '<p>No significant anomalies detected.</p>';
            }
            
            document.getElementById('report-content').innerHTML = html;
        }
        
        renderReport();
    </script>
</body>
</html>"""
