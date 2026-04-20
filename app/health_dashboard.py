"""
health_dashboard.py — Rich System Monitoring Dashboard
Hiển thị CPU, RAM, Disk, Container status, Pipeline metrics, v.v.
"""
import os
import time
import subprocess
import json
from datetime import datetime

def get_system_metrics():
    """Thu thập metrics hệ thống"""
    metrics = {}

    # CPU Usage
    try:
        load = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        metrics["cpu_usage"] = round(load[0] / cpu_count * 100, 1)
        metrics["cpu_load_1m"] = load[0]
        metrics["cpu_load_5m"] = load[1]
        metrics["cpu_load_15m"] = load[2]
        metrics["cpu_cores"] = cpu_count
    except Exception:
        metrics["cpu_usage"] = 0
        metrics["cpu_cores"] = 1

    # Memory
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            parts = line.split()
            mem[parts[0].rstrip(":")] = int(parts[1])
        total = mem.get("MemTotal", 0) / 1024  # MB
        available = mem.get("MemAvailable", 0) / 1024
        used = total - available
        metrics["ram_total_mb"] = round(total)
        metrics["ram_used_mb"] = round(used)
        metrics["ram_available_mb"] = round(available)
        metrics["ram_usage_pct"] = round(used / total * 100, 1) if total > 0 else 0
    except Exception:
        metrics["ram_total_mb"] = 0
        metrics["ram_used_mb"] = 0
        metrics["ram_usage_pct"] = 0

    # Disk
    try:
        stat = os.statvfs("/")
        total = stat.f_blocks * stat.f_frsize / (1024**3)
        free = stat.f_bavail * stat.f_frsize / (1024**3)
        used = total - free
        metrics["disk_total_gb"] = round(total, 1)
        metrics["disk_used_gb"] = round(used, 1)
        metrics["disk_free_gb"] = round(free, 1)
        metrics["disk_usage_pct"] = round(used / total * 100, 1) if total > 0 else 0
    except Exception:
        metrics["disk_total_gb"] = 0
        metrics["disk_usage_pct"] = 0

    # Uptime
    try:
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        metrics["uptime"] = f"{days}d {hours}h {minutes}m"
    except Exception:
        metrics["uptime"] = "N/A"

    return metrics


def get_container_status():
    """Lấy danh sách Docker containers"""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}|{{.Image}}"],
            capture_output=True, text=True, timeout=5
        )
        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            name = parts[0] if len(parts) > 0 else ""
            status = parts[1] if len(parts) > 1 else ""
            ports = parts[2] if len(parts) > 2 else ""
            image = parts[3] if len(parts) > 3 else ""
            is_healthy = "healthy" in status.lower()
            is_up = "up" in status.lower()
            containers.append({
                "name": name,
                "status": status,
                "ports": ports,
                "image": image,
                "healthy": is_healthy,
                "up": is_up,
            })
        return containers
    except Exception:
        return []


def get_db_stats(engine):
    """Lấy thống kê từ PostgreSQL"""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM shop.transactions")).scalar() or 0
            fraud = conn.execute(text("SELECT COUNT(*) FROM shop.fraud_transactions")).scalar() or 0
            latest = conn.execute(text(
                "SELECT ingested_at FROM shop.transactions ORDER BY ingested_at DESC LIMIT 1"
            )).scalar()
            return {
                "total_transactions": total,
                "fraud_transactions": fraud,
                "fraud_rate": round(fraud / total * 100, 3) if total > 0 else 0,
                "last_ingested": str(latest) if latest else "N/A",
            }
    except Exception as e:
        return {"total_transactions": 0, "fraud_transactions": 0, "fraud_rate": 0, "last_ingested": "N/A", "error": str(e)}


def render_dashboard_html(system, containers, db_stats, mlflow_metrics):
    """Render HTML dashboard hoàn chỉnh"""

    # Container rows
    container_rows = ""
    for c in containers:
        icon = "🟢" if c["up"] else "🔴"
        health = "✅ Healthy" if c["healthy"] else ("🟡 Running" if c["up"] else "❌ Down")
        container_rows += f"""
        <tr>
            <td>{icon} {c['name']}</td>
            <td><span class="badge {'badge-ok' if c['up'] else 'badge-err'}">{health}</span></td>
            <td class="text-muted">{c['status']}</td>
            <td class="text-muted">{c['ports'][:50] if c['ports'] else '—'}</td>
        </tr>"""

    # MLflow section
    f1 = mlflow_metrics.get("f1_score", 0)
    auprc = mlflow_metrics.get("auprc", 0)
    auc_roc = mlflow_metrics.get("auc_roc", 0)

    # Color for gauges
    def gauge_color(pct):
        if pct < 60: return "#22c55e"
        if pct < 85: return "#f59e0b"
        return "#ef4444"

    cpu_pct = system.get("cpu_usage", 0)
    ram_pct = system.get("ram_usage_pct", 0)
    disk_pct = system.get("disk_usage_pct", 0)

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛡️ System Monitor — Fraud Detection</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0f172a;
            --card: #1e293b;
            --card-border: #334155;
            --text: #e2e8f0;
            --text-muted: #94a3b8;
            --accent: #3b82f6;
            --green: #22c55e;
            --yellow: #f59e0b;
            --red: #ef4444;
            --purple: #a855f7;
        }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
        }}
        .topbar {{
            background: linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%);
            border-bottom: 1px solid var(--card-border);
            padding: 16px 32px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .topbar h1 {{ font-size: 1.2rem; font-weight: 600; }}
        .topbar h1 span {{ color: var(--accent); }}
        .topbar .meta {{ color: var(--text-muted); font-size: 0.8rem; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}

        .grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 24px; }}
        .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
        .grid-2 {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; margin-bottom: 24px; }}

        @media (max-width: 1024px) {{
            .grid-3 {{ grid-template-columns: 1fr; }}
            .grid-4 {{ grid-template-columns: repeat(2, 1fr); }}
            .grid-2 {{ grid-template-columns: 1fr; }}
        }}

        .card {{
            background: var(--card);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 24px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.3);
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}
        .card-title {{ font-size: 0.85rem; color: var(--text-muted); font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }}

        .metric-value {{ font-size: 2.2rem; font-weight: 700; line-height: 1; }}
        .metric-sub {{ font-size: 0.8rem; color: var(--text-muted); margin-top: 4px; }}

        /* Gauge */
        .gauge-container {{ position: relative; width: 120px; height: 120px; margin: 0 auto 12px; }}
        .gauge-bg {{ fill: none; stroke: #334155; stroke-width: 10; }}
        .gauge-fill {{ fill: none; stroke-width: 10; stroke-linecap: round; transition: stroke-dashoffset 1s ease; }}

        /* Stats card */
        .stat-card {{
            background: var(--card);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 20px;
            text-align: center;
        }}
        .stat-card .icon {{ font-size: 1.5rem; margin-bottom: 8px; }}
        .stat-card .value {{ font-size: 1.6rem; font-weight: 700; }}
        .stat-card .label {{ font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; }}

        /* Table */
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; padding: 12px; color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--card-border); }}
        td {{ padding: 12px; border-bottom: 1px solid rgba(51,65,85,0.5); font-size: 0.85rem; }}
        tr:hover {{ background: rgba(59,130,246,0.05); }}
        .text-muted {{ color: var(--text-muted); }}

        .badge {{
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-ok {{ background: rgba(34,197,94,0.15); color: var(--green); }}
        .badge-err {{ background: rgba(239,68,68,0.15); color: var(--red); }}
        .badge-warn {{ background: rgba(245,158,11,0.15); color: var(--yellow); }}

        .section-title {{
            font-size: 1rem;
            font-weight: 600;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .refresh-btn {{
            background: var(--accent);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.8rem;
            font-weight: 500;
            transition: opacity 0.2s;
        }}
        .refresh-btn:hover {{ opacity: 0.85; }}

        .pulse {{ animation: pulse 2s infinite; }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}

        .links a {{
            display: inline-block;
            background: rgba(59,130,246,0.1);
            color: var(--accent);
            border: 1px solid rgba(59,130,246,0.3);
            padding: 8px 16px;
            border-radius: 8px;
            text-decoration: none;
            font-size: 0.85rem;
            margin-right: 8px;
            margin-bottom: 8px;
            transition: all 0.2s;
        }}
        .links a:hover {{
            background: rgba(59,130,246,0.2);
            transform: translateY(-1px);
        }}
    </style>
</head>
<body>
    <div class="topbar">
        <h1>🛡️ <span>Fraud Detection</span> System Monitor</h1>
        <div class="meta">
            <span class="pulse">🟢</span> Live &mdash; {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC
            &nbsp;|&nbsp; Uptime: {system.get("uptime", "N/A")}
            &nbsp;&nbsp;<button class="refresh-btn" onclick="location.reload()">↻ Refresh</button>
        </div>
    </div>

    <div class="container">
        <!-- System Gauges -->
        <div class="grid-3">
            <div class="card" style="text-align:center;">
                <div class="card-title">CPU Usage</div>
                <div class="gauge-container">
                    <svg viewBox="0 0 120 120">
                        <circle class="gauge-bg" cx="60" cy="60" r="50" />
                        <circle class="gauge-fill" cx="60" cy="60" r="50"
                            stroke="{gauge_color(cpu_pct)}"
                            stroke-dasharray="314"
                            stroke-dashoffset="{314 - (314 * cpu_pct / 100)}"
                            transform="rotate(-90 60 60)" />
                        <text x="60" y="60" text-anchor="middle" dy="8" fill="var(--text)" font-size="22" font-weight="700">{cpu_pct}%</text>
                    </svg>
                </div>
                <div class="metric-sub">{system.get("cpu_cores", 0)} cores | Load: {system.get("cpu_load_1m", 0):.1f}</div>
            </div>
            <div class="card" style="text-align:center;">
                <div class="card-title">RAM Usage</div>
                <div class="gauge-container">
                    <svg viewBox="0 0 120 120">
                        <circle class="gauge-bg" cx="60" cy="60" r="50" />
                        <circle class="gauge-fill" cx="60" cy="60" r="50"
                            stroke="{gauge_color(ram_pct)}"
                            stroke-dasharray="314"
                            stroke-dashoffset="{314 - (314 * ram_pct / 100)}"
                            transform="rotate(-90 60 60)" />
                        <text x="60" y="60" text-anchor="middle" dy="8" fill="var(--text)" font-size="22" font-weight="700">{ram_pct}%</text>
                    </svg>
                </div>
                <div class="metric-sub">{system.get("ram_used_mb", 0):,} / {system.get("ram_total_mb", 0):,} MB</div>
            </div>
            <div class="card" style="text-align:center;">
                <div class="card-title">Disk Usage</div>
                <div class="gauge-container">
                    <svg viewBox="0 0 120 120">
                        <circle class="gauge-bg" cx="60" cy="60" r="50" />
                        <circle class="gauge-fill" cx="60" cy="60" r="50"
                            stroke="{gauge_color(disk_pct)}"
                            stroke-dasharray="314"
                            stroke-dashoffset="{314 - (314 * disk_pct / 100)}"
                            transform="rotate(-90 60 60)" />
                        <text x="60" y="60" text-anchor="middle" dy="8" fill="var(--text)" font-size="22" font-weight="700">{disk_pct}%</text>
                    </svg>
                </div>
                <div class="metric-sub">{system.get("disk_used_gb", 0):.1f} / {system.get("disk_total_gb", 0):.1f} GB</div>
            </div>
        </div>

        <!-- Pipeline Stats -->
        <div class="grid-4">
            <div class="stat-card">
                <div class="icon">📦</div>
                <div class="value">{db_stats.get("total_transactions", 0):,}</div>
                <div class="label">Total Transactions</div>
            </div>
            <div class="stat-card">
                <div class="icon">🚨</div>
                <div class="value" style="color:var(--red);">{db_stats.get("fraud_transactions", 0):,}</div>
                <div class="label">Fraud Detected</div>
            </div>
            <div class="stat-card">
                <div class="icon">📈</div>
                <div class="value">{db_stats.get("fraud_rate", 0):.3f}%</div>
                <div class="label">Fraud Rate</div>
            </div>
            <div class="stat-card">
                <div class="icon">🧠</div>
                <div class="value" style="color:var(--green);">{f1:.4f}</div>
                <div class="label">F1-Score (ML Model)</div>
            </div>
        </div>

        <!-- Model Metrics + Quick Links -->
        <div class="grid-2">
            <div class="card">
                <div class="section-title">🧠 ML Model Performance</div>
                <table>
                    <tr><td>F1-Score</td><td style="text-align:right;font-weight:600;">{f1:.4f}</td></tr>
                    <tr><td>AUPRC</td><td style="text-align:right;font-weight:600;">{auprc:.4f}</td></tr>
                    <tr><td>AUC-ROC</td><td style="text-align:right;font-weight:600;">{auc_roc:.4f}</td></tr>
                    <tr><td>Precision</td><td style="text-align:right;font-weight:600;">{mlflow_metrics.get("precision", 0):.4f}</td></tr>
                    <tr><td>Recall</td><td style="text-align:right;font-weight:600;">{mlflow_metrics.get("recall", 0):.4f}</td></tr>
                </table>
            </div>
            <div class="card">
                <div class="section-title">🔗 Quick Links</div>
                <div class="links" style="margin-top:12px;">
                    <a href="/docs">📖 API Swagger Docs</a>
                    <a href="http://{os.getenv('HOST_IP','140.245.127.238')}:8501" target="_blank">📊 Streamlit Dashboard</a>
                    <a href="http://{os.getenv('HOST_IP','140.245.127.238')}:5050" target="_blank">🧪 MLflow UI</a>
                    <a href="http://{os.getenv('HOST_IP','140.245.127.238')}:9000" target="_blank">📡 Kafdrop (Kafka)</a>
                </div>
                <div style="margin-top:20px;">
                    <div class="section-title">📋 Pipeline Info</div>
                    <table>
                        <tr><td>Last Ingested</td><td style="text-align:right;">{db_stats.get("last_ingested", "N/A")}</td></tr>
                        <tr><td>Kafka Topic</td><td style="text-align:right;">transactions-data</td></tr>
                        <tr><td>API Version</td><td style="text-align:right;">2.0.0</td></tr>
                        <tr><td>Security</td><td style="text-align:right;"><span class="badge badge-ok">12 Features</span></td></tr>
                    </table>
                </div>
            </div>
        </div>

        <!-- Container Status -->
        <div class="card">
            <div class="section-title">🐳 Docker Containers</div>
            <table>
                <thead>
                    <tr>
                        <th>Container</th>
                        <th>Health</th>
                        <th>Status</th>
                        <th>Ports</th>
                    </tr>
                </thead>
                <tbody>
                    {container_rows if container_rows else '<tr><td colspan="4" class="text-muted">Không thể lấy thông tin container (cần chạy trong Docker network)</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        // Auto-refresh every 30 seconds
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>"""
