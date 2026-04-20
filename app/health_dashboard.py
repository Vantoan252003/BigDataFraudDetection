"""
health_dashboard.py — Rich Real-time System Monitoring Dashboard (Defensive Version)
Fix 500 error by adding broad try/except and robust key checking.
"""
import os
import json
import docker
import traceback
from sqlalchemy import text
from datetime import datetime

def get_system_metrics():
    """Thu thập metrics hệ thống"""
    metrics = {
        "cpu_usage": 0, "cpu_cores": 1, 
        "ram_usage_pct": 0, "ram_used_mb": 0, "ram_total_mb": 0,
        "disk_usage_pct": 0, "disk_used_gb": 0, "disk_total_gb": 0,
        "uptime": "N/A"
    }
    try:
        # CPU
        load = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        metrics["cpu_usage"] = round(load[0] / cpu_count * 100, 1)
        metrics["cpu_cores"] = cpu_count
        # RAM
        with open("/proc/meminfo") as f:
            m = {l.split()[0].rstrip(":"): int(l.split()[1]) for l in f.readlines()}
        total = m.get("MemTotal", 0) / 1024
        avail = m.get("MemAvailable", 0) / 1024
        used = total - avail
        metrics["ram_usage_pct"] = round(used / total * 100, 1) if total > 0 else 0
        metrics["ram_used_mb"] = round(used)
        metrics["ram_total_mb"] = round(total)
        # Disk
        s = os.statvfs("/")
        total = s.f_blocks * s.f_frsize / (1024**3)
        free = s.f_bavail * s.f_frsize / (1024**3)
        used = total - free
        metrics["disk_usage_pct"] = round(used / total * 100, 1) if total > 0 else 0
        metrics["disk_used_gb"] = round(used, 1)
        metrics["disk_total_gb"] = round(total, 1)
        # Uptime
        with open("/proc/uptime") as f:
            upt = float(f.read().split()[0])
        metrics["uptime"] = f"{int(upt // 86400)}d {int((upt % 86400) // 3600)}h {int((upt % 3600) // 60)}m"
    except Exception as e:
        print(f"[Dashboard] System Metrics Error: {e}")
    return metrics

def get_container_status():
    """Lấy chi tiết Docker containers"""
    try:
        client = docker.from_env()
        containers = []
        for c in client.containers.list(all=True):
            try:
                attrs = c.attrs
                status = attrs.get('State', {}).get('Status', 'unknown')
                health = attrs.get('State', {}).get('Health', {}).get('Status', '')
                image_tag = "unknown"
                if c.image.tags:
                    image_tag = c.image.tags[0]
                
                # Format StartedAt
                started = attrs.get('State', {}).get('StartedAt', 'N/A')
                if 'T' in started:
                    started = started.split('.')[0].replace('T', ' ')

                containers.append({
                    "name": c.name,
                    "status": status,
                    "image": image_tag,
                    "up_for": started,
                    "up": status == "running",
                    "healthy": health == "healthy"
                })
            except: continue
        return containers
    except Exception as e:
        print(f"[Dashboard] Docker Error: {e}")
        return []

def get_db_stats(engine):
    """Lấy thống kê từ PostgreSQL"""
    try:
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM transactions_data")).scalar()
            fraud = conn.execute(text("SELECT COUNT(*) FROM transactions_data WHERE isFraud = 1")).scalar()
            last = conn.execute(text("SELECT MAX(timestamp) FROM transactions_data")).scalar()
            return {
                "total_transactions": total or 0,
                "fraud_transactions": fraud or 0,
                "fraud_rate": round(fraud/total*100, 2) if total and total > 0 else 0,
                "last_ingested": str(last) if last else "N/A"
            }
    except Exception as e:
        print(f"[Dashboard] DB Error: {e}")
        return {"total_transactions": 0, "fraud_transactions": 0, "fraud_rate": 0, "last_ingested": "N/A"}

def render_dashboard_html(system, containers, db_stats, mlflow_metrics):
    try:
        # Default empty values to prevent formatting errors
        sys = system or {}
        cnts = containers or []
        db = db_stats or {}
        ml = mlflow_metrics or {}
        if not isinstance(ml, dict): ml = {}

        cpu_p = sys.get("cpu_usage", 0)
        ram_p = sys.get("ram_usage_pct", 0)
        disk_p = sys.get("disk_usage_pct", 0)

        def gc(p): 
            try: p_val = float(p)
            except: p_val = 0
            return "#22c55e" if p_val < 60 else ("#f59e0b" if p_val < 85 else "#ef4444")
        
        def gv(val, default="0.0000"):
            try: return f"{float(val):.4f}"
            except: return default

        html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8"><title>🛡️ Real-time System Monitor</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{ --bg: #0f172a; --card: #1e293b; --border: #334155; --text: #e2e8f0; --muted: #94a3b8; --accent: #3b82f6; }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:'Inter',sans-serif; background:var(--bg); color:var(--text); padding:20px; }}
        .header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; border-bottom:1px solid var(--border); padding-bottom:15px; }}
        .live-dot {{ width:10px; height:10px; background:#22c55e; border-radius:50%; display:inline-block; margin-right:8px; animation: blink 1.5s infinite; }}
        @keyframes blink {{ 0% {{ opacity:1; }} 50% {{ opacity:0.3; }} 100% {{ opacity:1; }} }}
        .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap:20px; }}
        .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }}
        .card-h {{ font-size:0.8rem; color:var(--muted); text-transform:uppercase; margin-bottom:15px; font-weight:600; }}
        .gauge {{ position:relative; width:100px; height:100px; margin:0 auto; }}
        .gauge svg {{ transform: rotate(-90deg); }}
        .gauge-v {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); font-weight:700; font-size:1.2rem; }}
        table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
        th, td {{ text-align:left; padding:10px; font-size:0.85rem; border-bottom:1px solid rgba(255,255,255,0.05); }}
        .badge {{ padding:2px 8px; border-radius:12px; font-size:0.7rem; font-weight:700; }}
        .bg-ok {{ background:rgba(34,197,94,0.15); color:#22c55e; }}
        .bg-err {{ background:rgba(239,68,68,0.15); color:#ef4444; }}
        .links a {{ color:var(--accent); text-decoration:none; display:inline-block; margin-right:15px; font-size:0.8rem; }}
    </style>
</head>
<body>
    <div class="header">
        <div><h1>🛡️ Project <span>Monitor</span></h1><p style="font-size:0.8rem;color:var(--muted)">Uptime: <span id="uptime">{sys.get('uptime','N/A')}</span></p></div>
        <div id="status-box"><span class="live-dot"></span><span style="font-size:0.9rem">Real-time Live</span></div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-h">CPU Usage</div>
            <div class="gauge">
                <svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="none" stroke="#334155" stroke-width="8"/>
                <circle cx="50" cy="50" r="45" fill="none" stroke="{gc(cpu_p)}" stroke-width="8" stroke-dasharray="283" stroke-dashoffset="{283 - (283 * float(cpu_p or 0) / 100)}"/></svg>
                <div class="gauge-v">{cpu_p}%</div>
            </div>
        </div>
        <div class="card">
            <div class="card-h">RAM Usage</div>
            <div class="gauge">
                <svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="none" stroke="#334155" stroke-width="8"/>
                <circle cx="50" cy="50" r="45" fill="none" stroke="{gc(ram_p)}" stroke-width="8" stroke-dasharray="283" stroke-dashoffset="{283 - (283 * float(ram_p or 0) / 100)}"/></svg>
                <div class="gauge-v">{ram_p}%</div>
            </div>
            <p style="text-align:center;font-size:0.7rem;color:var(--muted);margin-top:10px">{sys.get('ram_used_mb',0)} / {sys.get('ram_total_mb',0)} MB</p>
        </div>
        <div class="card">
            <div class="card-h">ML Metrics (Latest)</div>
            <table>
                <tr><td>F1-Score</td><td style="color:#22c55e;font-weight:600">{gv(ml.get('f1_score',0))}</td></tr>
                <tr><td>AUPRC</td><td>{gv(ml.get('auprc',0))}</td></tr>
                <tr><td>AUC-ROC</td><td>{gv(ml.get('auc_roc',0))}</td></tr>
            </table>
        </div>
    </div>

    <div class="card" style="margin-top:20px">
        <div class="card-h">Pipeline & Database Status</div>
        <div style="display:flex;gap:30px;padding:10px">
            <div><p style="color:var(--muted);font-size:0.7rem">Total Tx</p><h2>{db.get('total_transactions',0):,}</h2></div>
            <div><p style="color:var(--muted);font-size:0.7rem">Fraud Detected</p><h2 style="color:#ef4444">{db.get('fraud_transactions',0):,}</h2></div>
            <div><p style="color:var(--muted);font-size:0.7rem">Last Update</p><p style="font-size:0.85rem">{db.get('last_ingested','N/A')}</p></div>
        </div>
    </div>

    <div class="card" style="margin-top:20px">
        <div class="card-h">Docker Services</div>
        <table>
            <thead><tr style="text-align:left;color:var(--muted)"><th>Service</th><th>Image</th><th>Status</th><th>Started At</th></tr></thead>
            <tbody>
                {"".join([f"<tr><td>{c['name']}</td><td style='font-size:0.7rem;color:var(--muted)'>{c['image']}</td><td><span class='badge {'bg-ok' if c['up'] else 'bg-err'}'>{'Healthy' if c['healthy'] else c['status'].upper()}</span></td><td style='font-size:0.7rem'>{c['up_for']}</td></tr>" for c in cnts])}
            </tbody>
        </table>
    </div>

    <div class="links" style="margin-top:20px">
        <a href="/docs">Swagger API</a>
        <a href="http://{os.getenv('HOST_IP','140.245.127.238')}:8501">Streamlit UI</a>
        <a href="http://{os.getenv('HOST_IP','140.245.127.238')}:5050">MLflow UI</a>
    </div>

    <script>
        setInterval(() => location.reload(), 5000);
    </script>
</body></html>"""
        return html
    except Exception as e:
        error_info = traceback.format_exc()
        print(f"[Dashboard] Render Error: {error_info}")
        return f"<html><body><h1>Dashboard Error</h1><pre>{error_info}</pre></body></html>"
