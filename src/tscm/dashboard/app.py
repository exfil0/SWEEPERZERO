"""Web dashboard for TSCM sweep visualization.

Simple Flask-based dashboard for viewing sweep results.
"""

from pathlib import Path
from typing import Optional

from tscm.config import load_config
from tscm.storage.store import SweepStore


def create_app(config_path: Optional[Path] = None):
    """
    Create Flask application.

    Args:
        config_path: Optional path to config file

    Returns:
        Flask application instance
    """
    try:
        from flask import Flask, jsonify, render_template, request
    except ImportError:
        raise ImportError("Flask is required for dashboard. Install with: pip install flask")

    app = Flask(__name__, template_folder=str(Path(__file__).parent.parent / "templates"))
    
    # Load TSCM config
    config = load_config(config_path)
    store = SweepStore(config.storage.database_path, config.storage.enable_wal)

    @app.route("/")
    def index():
        """Dashboard home page."""
        return render_template("dashboard.html")

    @app.route("/api/sweeps")
    def get_sweeps():
        """API endpoint to list sweeps."""
        client = request.args.get("client")
        site = request.args.get("site")
        room = request.args.get("room")
        try:
            limit = int(request.args.get("limit", 50))
            limit = min(max(limit, 1), 1000)  # Clamp between 1 and 1000
        except (ValueError, TypeError):
            limit = 50

        sweeps = store.get_sweeps(
            client_name=client,
            site=site,
            room=room,
            limit=limit,
        )

        return jsonify(sweeps)

    @app.route("/api/sweeps/<int:sweep_id>")
    def get_sweep(sweep_id):
        """API endpoint to get sweep details."""
        sweep = store.get_sweep_by_id(str(sweep_id))
        if not sweep:
            return jsonify({"error": "Sweep not found"}), 404

        # Get events summary
        events_summary = {}
        for event_type in ["rf", "wifi", "ble", "gsm"]:
            events = store.get_events(sweep["id"], event_type=event_type, limit=1000)
            events_summary[event_type] = {
                "count": len(events),
                "events": events[:100],  # Limit for performance
            }

        # Get anomalies
        anomalies = store.get_anomalies(sweep["id"])

        # Get artifacts
        artifacts = store.get_artifacts(sweep["id"])

        return jsonify({
            "sweep": sweep,
            "events": events_summary,
            "anomalies": anomalies,
            "artifacts": artifacts,
        })

    @app.route("/api/anomalies/<int:sweep_id>")
    def get_anomalies(sweep_id):
        """API endpoint to get anomalies for a sweep."""
        min_score = float(request.args.get("min_score", 0.0))
        kind = request.args.get("kind")

        anomalies = store.get_anomalies(sweep_id, kind=kind, min_score=min_score)
        return jsonify(anomalies)

    return app


def run_dashboard(host: str = "127.0.0.1", port: int = 5000, config_path: Optional[Path] = None):
    """
    Run the dashboard web server.

    Args:
        host: Host to bind to
        port: Port to listen on
        config_path: Optional path to config file
    """
    app = create_app(config_path)
    print(f"Starting TSCM dashboard on http://{host}:{port}")
    app.run(host=host, port=port, debug=True)


def _get_default_dashboard_template() -> str:
    """Get default dashboard HTML template."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>TSCM Dashboard</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #f5f5f5;
            color: #333;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .header h1 { font-size: 28px; margin-bottom: 5px; }
        .header p { opacity: 0.9; font-size: 14px; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .card {
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            padding: 20px;
            margin-bottom: 20px;
        }
        .card h2 { 
            font-size: 20px; 
            margin-bottom: 15px; 
            color: #667eea;
            border-bottom: 2px solid #f0f0f0;
            padding-bottom: 10px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #f0f0f0;
        }
        th {
            background: #f8f9fa;
            font-weight: 600;
            color: #667eea;
        }
        tr:hover { background: #f8f9fa; }
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
        }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-warning { background: #fff3cd; color: #856404; }
        .badge-danger { background: #f8d7da; color: #721c24; }
        .loading { text-align: center; padding: 40px; color: #999; }
        .empty { text-align: center; padding: 40px; color: #999; }
        .btn {
            display: inline-block;
            padding: 8px 16px;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 14px;
            transition: background 0.3s;
        }
        .btn:hover { background: #5568d3; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 SWEEPERZERO Dashboard</h1>
        <p>Technical Surveillance Counter-Measures Monitoring</p>
    </div>

    <div class="container">
        <div class="card">
            <h2>Recent Sweeps</h2>
            <div id="sweeps-list" class="loading">Loading sweeps...</div>
        </div>
    </div>

    <script>
        async function loadSweeps() {
            try {
                const response = await fetch('/api/sweeps?limit=20');
                const sweeps = await response.json();
                
                if (sweeps.length === 0) {
                    document.getElementById('sweeps-list').innerHTML = 
                        '<div class="empty">No sweeps found. Run a sweep to get started.</div>';
                    return;
                }
                
                let html = '<table>';
                html += '<thead><tr>';
                html += '<th>Sweep ID</th>';
                html += '<th>Client</th>';
                html += '<th>Site/Room</th>';
                html += '<th>Start Time</th>';
                html += '<th>Status</th>';
                html += '<th>Actions</th>';
                html += '</tr></thead><tbody>';
                
                for (const sweep of sweeps) {
                    const statusBadge = sweep.status === 'completed' ? 'badge-success' : 
                                      sweep.status === 'running' ? 'badge-warning' : 'badge-danger';
                    
                    html += '<tr>';
                    html += `<td><strong>${sweep.sweep_id}</strong></td>`;
                    html += `<td>${sweep.client_name}</td>`;
                    html += `<td>${sweep.site || '-'} / ${sweep.room || '-'}</td>`;
                    html += `<td>${new Date(sweep.start_time).toLocaleString()}</td>`;
                    html += `<td><span class="badge ${statusBadge}">${sweep.status}</span></td>`;
                    html += `<td><a href="#" class="btn" onclick="viewSweep(${sweep.id}); return false;">View</a></td>`;
                    html += '</tr>';
                }
                
                html += '</tbody></table>';
                document.getElementById('sweeps-list').innerHTML = html;
            } catch (error) {
                document.getElementById('sweeps-list').innerHTML = 
                    '<div class="empty">Error loading sweeps: ' + error.message + '</div>';
            }
        }
        
        async function viewSweep(sweepId) {
            alert('Viewing sweep ' + sweepId + ' - Full sweep viewer coming soon!');
        }
        
        // Load sweeps on page load
        loadSweeps();
        
        // Auto-refresh every 30 seconds
        setInterval(loadSweeps, 30000);
    </script>
</body>
</html>"""


if __name__ == "__main__":
    run_dashboard()
