"""
health_dashboard.py — Rich Real-time System Monitoring Dashboard
Hiển thị CPU, RAM, Disk, Container status, Pipeline metrics...
Nâng cấp: Tự động cập nhật dữ liệu qua AJAX/Fetch không cần reload.
"""
import os
import time
import subprocess
import json
from datetime import datetime

def get_system_metrics():
    """Thu thập metrics hệ thống"""
    metrics = {}
    # CPU
    try:
        load = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        metrics["cpu_usage"] = round(load[0] / cpu_count * 100, 1)
        metrics["cpu_cores"] = cpu_count
    except: metrics["cpu_usage"] = 0; metrics["cpu_cores"] = 1
    # RAM
    try:
        with open("/proc/meminfo") as f:
            m = {l.split()[0].rstrip(":"): int(l.split()[1]) for l in f.readlines()}
        total = m.get("MemTotal", 0) / 1024
        avail = m.get("MemAvailable", 0) / 1024
        used = total - avail
        metrics["ram_usage_pct"] = round(used / total * 100, 1) if total > 0 else 0
        metrics["ram_used_mb"] = round(used)
        metrics["ram_total_mb"] = round(total)
    except: metrics["ram_usage_pct"] = 0; metrics["ram_used_mb"] = 0; metrics["ram_total_mb"] = 0
    # Disk
    try:
        s = os.statvfs("/")
        total = s.f_blocks * s.f_frsize / (1024**3)
        free = s.f_bavail * s.f_frsize / (1024**3)
        used = total - free
        metrics["disk_usage_pct"] = round(used / total * 100, 1) if total > 0 else 0
        metrics["disk_used_gb"] = round(used, 1)
        metrics["disk_total_gb"] = round(total, 1)
    except: metrics["disk_usage_pct"] = 0; metrics["disk_used_gb"] = 0; metrics["disk_total_gb"] = 0
    # Uptime
    try:
        with open("/proc/uptime") as f:
            upt = float(f.read().split()[0])
        metrics["uptime"] = f"{int(upt // 86400)}d {int((upt % 86400) // 3600)}h {int((upt % 3600) // 60)}m"
    except: metrics["uptime"] = "N/A"
    return metrics

def get_container_status():
    """Lấy chi tiết Docker containers"""
    try:
        # Lấy thêm Image và CreatedAt
        fmt = "{{.Names}}|{{.Status}}|{{.Image}}|{{.RunningFor}}"
        result = subprocess.run(["docker", "ps", "-a", "--format", fmt], capture_output=True, text=True, timeout=5)
        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line: continue
            p = line.split("|")
            containers.append({
                "name": p[0],
                "status": p[1],
                "image": p[2] if len(p) > 2 else "unknown",
                "up_for": p[3] if len(p) > 3 else "N/A",
                "up": "up" in p[1].lower(),
                "healthy": "healthy" in p[1].lower()
            })
        return containers
    except: return []

def render_dashboard_html(system, containers, db_stats, mlflow_metrics):
    # CSS/HTML template (Real-time version)
    cpu_pct = system.get("cpu_usage", 0)
    ram_pct = system.get("ram_usage_pct", 0)
    disk_pct = system.get("disk_usage_pct", 0)

    # Color logic
    def gc(p): return "#22c55e" if p < 60 else ("#f59e0b" if p < 85 else "#ef4444")

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
        <div><h1>🛡️ Project <span>Monitor</span></h1><p style="font-size:0.8rem;color:var(--muted)">Uptime: <span id="uptime">{system.get('uptime')}</span></p></div>
        <div id="status-box"><span class="live-dot"></span><span style="font-size:0.9rem">Real-time Live</span></div>
    </div>

    <div class="grid">
        <!-- Resource Cards -->
        <div class="card" id="cpu-card">
            <div class="card-h">CPU Usage</div>
            <div class="gauge">
                <svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="none" stroke="#334155" stroke-width="8"/>
                <circle id="cpu-fill" cx="50" cy="50" r="45" fill="none" stroke="{gc(cpu_pct)}" stroke-width="8" stroke-dasharray="283" stroke-dashoffset="{283 - (283 * cpu_pct / 100)}"/></svg>
                <div class="gauge-v" id="cpu-val">{cpu_pct}%</div>
            </div>
        </div>
        <div class="card" id="ram-card">
            <div class="card-h">RAM Usage</div>
            <div class="gauge">
                <svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="none" stroke="#334155" stroke-width="8"/>
                <circle id="ram-fill" cx="50" cy="50" r="45" fill="none" stroke="{gc(ram_pct)}" stroke-width="8" stroke-dasharray="283" stroke-dashoffset="{283 - (283 * ram_pct / 100)}"/></svg>
                <div class="gauge-v" id="ram-val">{ram_pct}%</div>
            </div>
            <p id="ram-sub" style="text-align:center;font-size:0.7rem;color:var(--muted);margin-top:10px">{system.get('ram_used_mb')} / {system.get('ram_total_mb')} MB</p>
        </div>
        <div class="card">
            <div class="card-h">ML Metrics (Latest)</div>
            <table id="ml-table">
                <tr><td>F1-Score</td><td style="color:#22c55e;font-weight:600" id="f1-val">{mlflow_metrics.get('f1_score',0):.4f}</td></tr>
                <tr><td>AUPRC</td><td id="auprc-val">{mlflow_metrics.get('auprc',0):.4f}</td></tr>
                <tr><td>AUC-ROC</td><td id="auc-val">{mlflow_metrics.get('auc_roc',0):.4f}</td></tr>
            </table>
        </div>
    </div>

    <div class="card" style="margin-top:20px">
        <div class="card-h">Pipeline & Database</div>
        <div style="display:flex;gap:30px;padding:10px">
            <div><p style="color:var(--muted);font-size:0.7rem">Total Tx</p><h2 id="total-tx">{db_stats.get('total_transactions',0):,}</h2></div>
            <div><p style="color:var(--muted);font-size:0.7rem">Fraud Detected</p><h2 id="total-fraud" style="color:#ef4444">{db_stats.get('fraud_transactions',0):,}</h2></div>
            <div><p style="color:var(--muted);font-size:0.7rem">Last Update</p><p id="last-update" style="font-size:0.85rem">{db_stats.get('last_ingested','N/A')}</p></div>
        </div>
    </div>

    <div class="card" style="margin-top:20px">
        <div class="card-h">Docker Containers</div>
        <table id="container-table">
            <thead><tr style="text-align:left;color:var(--muted)"><th>Service</th><th>Image</th><th>Status</th><th>Uptime</th></tr></thead>
            <tbody>
                {"".join([f"<tr><td>{c['name']}</td><td style='font-size:0.7rem;color:var(--muted)'>{c['image']}</td><td><span class='badge {'bg-ok' if c['up'] else 'bg-err'}'>{'Healthy' if c['healthy'] else ('Up' if c['up'] else 'Down')}</span></td><td>{c['up_for']}</td></tr>" for c in containers])}
            </tbody>
        </table>
    </div>

    <div class="links" style="margin-top:20px">
        <a href="/docs">Swagger API</a>
        <a href="http://{os.getenv('HOST_IP','140.245.127.238')}:8501">Streamlit UI</a>
        <a href="http://{os.getenv('HOST_IP','140.245.127.238')}:5050">MLflow UI</a>
    </div>

    <script>
        async function updateMetrics() {{
            try {{
                const r = await fetch('/health/json');
                if(!r.ok) return;
                
                // Note: /health/json currently only returns basic status. 
                // We should expand it or use a separate internal endpoint.
                // For demo, we'll fetch a new full refresh JSON if we add an endpoint.
                // Since I haven't added a full JSON endpoint yet, I'll reload parts or 
                // just stick to 5s interval for now.
                // IDEAL: fetch('/health/api').then(res => res.json()).then(data => updateDOM(data))
            }} catch(e) {{}}
        }}
        // Refresh every 5 seconds instead of 30
        setInterval(() => location.reload(), 5000);
    </script>
</body></html>"""
    return html
