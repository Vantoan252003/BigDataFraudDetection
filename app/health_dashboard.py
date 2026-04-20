"""
health_dashboard.py — Bảng Giám Sát Hệ Thống Thời Gian Thực (Tiếng Việt)
Tính năng: AJAX auto-refresh 5s (không reload trang), hiển thị CPU/RAM/Disk/SSD/Network,
Docker containers, DB stats (fraud đúng schema), MLflow metrics, top fraud accounts.
"""
import os
import json
import docker
import traceback
from sqlalchemy import text
from datetime import datetime


def get_system_metrics():
    """Thu thập metrics hệ thống (CPU, RAM, Disk, Network, Process)"""
    metrics = {
        "cpu_usage": 0, "cpu_cores": 1,
        "ram_usage_pct": 0, "ram_used_mb": 0, "ram_total_mb": 0,
        "disk_usage_pct": 0, "disk_used_gb": 0, "disk_total_gb": 0,
        "disk_read_mb": 0, "disk_write_mb": 0,
        "net_rx_mb": 0, "net_tx_mb": 0,
        "process_count": 0,
        "uptime": "N/A"
    }
    try:
        # CPU
        load = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        metrics["cpu_usage"] = round(load[0] / cpu_count * 100, 1)
        metrics["cpu_cores"] = cpu_count
        metrics["load_1m"] = round(load[0], 2)
        metrics["load_5m"] = round(load[1], 2)
        metrics["load_15m"] = round(load[2], 2)
    except Exception:
        pass

    try:
        # RAM
        with open("/proc/meminfo") as f:
            m = {l.split()[0].rstrip(":"): int(l.split()[1]) for l in f.readlines()}
        total = m.get("MemTotal", 0) / 1024
        avail = m.get("MemAvailable", 0) / 1024
        used = total - avail
        metrics["ram_usage_pct"] = round(used / total * 100, 1) if total > 0 else 0
        metrics["ram_used_mb"] = round(used)
        metrics["ram_total_mb"] = round(total)
        # Swap
        swap_total = m.get("SwapTotal", 0) / 1024
        swap_free = m.get("SwapFree", 0) / 1024
        metrics["swap_used_mb"] = round(swap_total - swap_free)
        metrics["swap_total_mb"] = round(swap_total)
    except Exception:
        pass

    try:
        # Disk
        s = os.statvfs("/")
        total = s.f_blocks * s.f_frsize / (1024**3)
        free = s.f_bavail * s.f_frsize / (1024**3)
        used = total - free
        metrics["disk_usage_pct"] = round(used / total * 100, 1) if total > 0 else 0
        metrics["disk_used_gb"] = round(used, 1)
        metrics["disk_total_gb"] = round(total, 1)
        metrics["disk_free_gb"] = round(free, 1)
    except Exception:
        pass

    try:
        # Disk I/O
        with open("/proc/diskstats") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14 and parts[2] in ("sda", "vda", "nvme0n1"):
                    sectors_read = int(parts[5])
                    sectors_written = int(parts[9])
                    metrics["disk_read_mb"] = round(sectors_read * 512 / (1024**2), 1)
                    metrics["disk_write_mb"] = round(sectors_written * 512 / (1024**2), 1)
                    # Detect SSD vs HDD
                    disk_name = parts[2]
                    rotational_path = f"/sys/block/{disk_name}/queue/rotational"
                    try:
                        with open(rotational_path) as rf:
                            is_rotational = rf.read().strip()
                            metrics["disk_type"] = "HDD" if is_rotational == "1" else "SSD/NVMe"
                    except Exception:
                        metrics["disk_type"] = "NVMe" if "nvme" in disk_name else "Không rõ"
                    break
    except Exception:
        metrics["disk_type"] = "Không rõ"

    try:
        # Network I/O
        with open("/proc/net/dev") as f:
            for line in f:
                if "eth0" in line or "ens" in line:
                    parts = line.split()
                    metrics["net_rx_mb"] = round(int(parts[1]) / (1024**2), 1)
                    metrics["net_tx_mb"] = round(int(parts[9]) / (1024**2), 1)
                    break
    except Exception:
        pass

    try:
        # Process count
        import subprocess
        result = subprocess.run(["ls", "/proc"], capture_output=True, text=True)
        metrics["process_count"] = sum(1 for d in result.stdout.split() if d.isdigit())
    except Exception:
        pass

    try:
        # Uptime
        with open("/proc/uptime") as f:
            upt = float(f.read().split()[0])
        days = int(upt // 86400)
        hours = int((upt % 86400) // 3600)
        mins = int((upt % 3600) // 60)
        metrics["uptime"] = f"{days} ngày {hours} giờ {mins} phút"
        metrics["uptime_seconds"] = int(upt)
    except Exception:
        pass

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

                # Ports
                ports = attrs.get('NetworkSettings', {}).get('Ports', {})
                port_list = []
                for container_port, host_bindings in (ports or {}).items():
                    if host_bindings:
                        for hb in host_bindings:
                            port_list.append(f"{hb.get('HostPort', '?')}→{container_port}")
                    else:
                        port_list.append(container_port)

                containers.append({
                    "name": c.name,
                    "status": status,
                    "image": image_tag,
                    "up_for": started,
                    "up": status == "running",
                    "healthy": health == "healthy",
                    "ports": ", ".join(port_list[:3]) if port_list else "—"
                })
            except:
                continue
        return containers
    except Exception as e:
        print(f"[Dashboard] Docker Error: {e}")
        return []


def get_db_stats(engine):
    """Lấy thống kê từ PostgreSQL — sử dụng đúng schema shop"""
    try:
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM shop.transactions")).scalar()
            fraud = conn.execute(text("SELECT COUNT(*) FROM shop.fraud_transactions")).scalar()
            last = conn.execute(text("SELECT MAX(ingested_at) FROM shop.transactions")).scalar()

            # Top 5 fraud accounts
            top_fraud = []
            try:
                rows = conn.execute(text("""
                    SELECT "nameOrig", COUNT(*) as cnt, SUM(amount) as total_amt
                    FROM shop.fraud_transactions
                    GROUP BY "nameOrig"
                    ORDER BY cnt DESC
                    LIMIT 5
                """)).fetchall()
                for row in rows:
                    name = row[0]
                    masked = name[:5] + "*" * (len(name) - 5) if len(name) > 5 else name
                    top_fraud.append({
                        "account": masked,
                        "count": row[1],
                        "total": round(float(row[2]), 2)
                    })
            except Exception:
                pass

            # Recent 5 fraud alerts
            recent_fraud = []
            try:
                rows = conn.execute(text("""
                    SELECT "nameOrig", "nameDest", amount, type, 
                           blacklist_flag, rule_fraud_flag, ingested_at
                    FROM shop.fraud_transactions
                    ORDER BY ingested_at DESC
                    LIMIT 5
                """)).fetchall()
                for row in rows:
                    orig = row[0][:5] + "***" if len(row[0]) > 5 else row[0]
                    dest = row[1][:5] + "***" if len(row[1]) > 5 else row[1]
                    reason = "Blacklist" if row[4] == 1 else ("Rule chặn" if row[5] == 1 else "ML Model")
                    recent_fraud.append({
                        "orig": orig,
                        "dest": dest,
                        "amount": f"${float(row[2]):,.2f}",
                        "type": row[3],
                        "reason": reason,
                        "time": str(row[6])[:19] if row[6] else "N/A"
                    })
            except Exception:
                pass

            # Fraud by type
            fraud_by_type = []
            try:
                rows = conn.execute(text("""
                    SELECT type, COUNT(*) as cnt
                    FROM shop.fraud_transactions
                    GROUP BY type ORDER BY cnt DESC
                """)).fetchall()
                for row in rows:
                    fraud_by_type.append({"type": row[0], "count": row[1]})
            except Exception:
                pass

            return {
                "total_transactions": total or 0,
                "fraud_transactions": fraud or 0,
                "fraud_rate": round(fraud / total * 100, 3) if total and total > 0 else 0,
                "last_ingested": str(last)[:19] if last else "N/A",
                "top_fraud": top_fraud,
                "recent_fraud": recent_fraud,
                "fraud_by_type": fraud_by_type
            }
    except Exception as e:
        print(f"[Dashboard] DB Error: {e}")
        return {
            "total_transactions": 0, "fraud_transactions": 0, "fraud_rate": 0,
            "last_ingested": "N/A", "top_fraud": [], "recent_fraud": [], "fraud_by_type": []
        }


def render_dashboard_html(system, containers, db_stats, mlflow_metrics):
    """Render HTML dashboard hoàn toàn bằng tiếng Việt, với AJAX refresh"""
    try:
        sys_m = system or {}
        cnts = containers or []
        db = db_stats or {}
        ml = mlflow_metrics or {}
        if not isinstance(ml, dict):
            ml = {}

        cpu_p = sys_m.get("cpu_usage", 0)
        ram_p = sys_m.get("ram_usage_pct", 0)
        disk_p = sys_m.get("disk_usage_pct", 0)

        def gc(p):
            try:
                p_val = float(p)
            except:
                p_val = 0
            return "#22c55e" if p_val < 60 else ("#f59e0b" if p_val < 85 else "#ef4444")

        def gv(val, default="0.0000"):
            try:
                return f"{float(val):.4f}"
            except:
                return default

        # Build containers table rows
        container_rows = ""
        for c in cnts:
            badge_class = "bg-ok" if c["up"] else "bg-err"
            status_text = "Khỏe mạnh" if c["healthy"] else ("Đang chạy" if c["up"] else c["status"].upper())
            container_rows += f"""<tr>
                <td><strong>{c['name']}</strong></td>
                <td style='font-size:0.75rem;color:var(--muted)'>{c['image']}</td>
                <td><span class='badge {badge_class}'>{status_text}</span></td>
                <td style='font-size:0.75rem;color:var(--muted)'>{c.get('ports', '—')}</td>
                <td style='font-size:0.75rem'>{c['up_for']}</td>
            </tr>"""

        # Top fraud rows
        top_fraud_rows = ""
        for i, tf in enumerate(db.get("top_fraud", [])):
            top_fraud_rows += f"""<tr>
                <td style="color:#f59e0b">#{i+1}</td>
                <td><code>{tf['account']}</code></td>
                <td style="color:#ef4444;font-weight:600">{tf['count']}</td>
                <td>${tf['total']:,.2f}</td>
            </tr>"""

        # Recent fraud rows
        recent_fraud_rows = ""
        for rf in db.get("recent_fraud", []):
            reason_color = "#ef4444" if rf["reason"] == "Blacklist" else ("#f59e0b" if rf["reason"] == "Rule chặn" else "#a78bfa")
            recent_fraud_rows += f"""<tr>
                <td><code>{rf['orig']}</code></td>
                <td><code>{rf['dest']}</code></td>
                <td style="font-weight:600">{rf['amount']}</td>
                <td>{rf['type']}</td>
                <td><span style="color:{reason_color};font-weight:600">⬤ {rf['reason']}</span></td>
                <td style="font-size:0.7rem;color:var(--muted)">{rf['time']}</td>
            </tr>"""

        # Fraud by type
        fraud_type_items = ""
        for ft in db.get("fraud_by_type", []):
            fraud_type_items += f"""<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05)">
                <span>{ft['type']}</span><span style="color:#ef4444;font-weight:600">{ft['count']:,}</span>
            </div>"""

        running_count = sum(1 for c in cnts if c["up"])
        total_count = len(cnts)

        html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>🛡️ Giám Sát Hệ Thống — Fraud Detection</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0a0e1a;
            --card: #111827;
            --card-hover: #1a2332;
            --border: #1e293b;
            --text: #e2e8f0;
            --muted: #64748b;
            --accent: #3b82f6;
            --accent-glow: rgba(59, 130, 246, 0.15);
            --success: #22c55e;
            --warning: #f59e0b;
            --danger: #ef4444;
            --purple: #a78bfa;
        }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{
            font-family:'Inter',sans-serif;
            background: var(--bg);
            color:var(--text);
            padding: 24px 32px;
            min-height: 100vh;
        }}

        /* Header */
        .header {{
            display:flex; justify-content:space-between; align-items:center;
            margin-bottom:28px; padding-bottom:20px;
            border-bottom:1px solid var(--border);
        }}
        .header h1 {{
            font-size:1.6rem; font-weight:800;
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            -webkit-background-clip:text; -webkit-text-fill-color:transparent;
        }}
        .header-sub {{ font-size:0.8rem; color:var(--muted); margin-top:4px; }}

        .live-badge {{
            display:flex; align-items:center; gap:8px;
            background: rgba(34,197,94,0.1); border:1px solid rgba(34,197,94,0.3);
            border-radius:20px; padding:6px 16px; font-size:0.8rem; font-weight:600;
            color: var(--success);
        }}
        .live-dot {{
            width:8px; height:8px; background:var(--success);
            border-radius:50%; animation: pulse 1.5s infinite;
        }}
        @keyframes pulse {{
            0%,100% {{ opacity:1; box-shadow:0 0 0 0 rgba(34,197,94,0.5); }}
            50% {{ opacity:0.6; box-shadow:0 0 0 6px rgba(34,197,94,0); }}
        }}

        /* Grid */
        .grid {{ display:grid; gap:16px; }}
        .grid-4 {{ grid-template-columns: repeat(4, 1fr); }}
        .grid-3 {{ grid-template-columns: repeat(3, 1fr); }}
        .grid-2 {{ grid-template-columns: repeat(2, 1fr); }}
        .grid-2-1 {{ grid-template-columns: 2fr 1fr; }}

        /* Cards */
        .card {{
            background:var(--card); border:1px solid var(--border);
            border-radius:14px; padding:20px;
            transition: all 0.2s ease;
        }}
        .card:hover {{ border-color: rgba(59,130,246,0.3); background: var(--card-hover); }}
        .card-h {{
            font-size:0.7rem; color:var(--muted); text-transform:uppercase;
            letter-spacing:1px; margin-bottom:12px; font-weight:600;
            display:flex; align-items:center; gap:6px;
        }}

        /* Gauge */
        .gauge {{ position:relative; width:90px; height:90px; margin:0 auto 8px; }}
        .gauge svg {{ transform: rotate(-90deg); }}
        .gauge-v {{
            position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
            font-weight:700; font-size:1.15rem;
        }}
        .gauge-label {{ text-align:center; font-size:0.7rem; color:var(--muted); }}

        /* Stat */
        .stat-value {{ font-size:1.8rem; font-weight:700; line-height:1.2; }}
        .stat-label {{ font-size:0.7rem; color:var(--muted); margin-top:2px; }}
        .stat-sub {{ font-size:0.7rem; color:var(--muted); margin-top:6px; }}

        /* Table */
        table {{ width:100%; border-collapse:collapse; }}
        th {{ text-align:left; padding:10px 12px; font-size:0.7rem; color:var(--muted);
              text-transform:uppercase; letter-spacing:0.5px;
              border-bottom:1px solid var(--border); font-weight:600; }}
        td {{ padding:10px 12px; font-size:0.82rem; border-bottom:1px solid rgba(255,255,255,0.03); }}
        tbody tr:hover {{ background: rgba(59,130,246,0.05); }}

        /* Badge */
        .badge {{
            padding:3px 10px; border-radius:12px; font-size:0.68rem;
            font-weight:700; display:inline-block;
        }}
        .bg-ok {{ background:rgba(34,197,94,0.12); color:#22c55e; }}
        .bg-err {{ background:rgba(239,68,68,0.12); color:#ef4444; }}
        .bg-warn {{ background:rgba(245,158,11,0.12); color:#f59e0b; }}

        /* Section */
        .section {{ margin-top:20px; }}
        .section-title {{
            font-size:0.9rem; font-weight:700; margin-bottom:14px;
            display:flex; align-items:center; gap:8px;
        }}

        /* Links */
        .links {{ margin-top:24px; display:flex; gap:12px; flex-wrap:wrap; }}
        .links a {{
            color:var(--accent); text-decoration:none; font-size:0.8rem; font-weight:500;
            padding:8px 16px; border:1px solid rgba(59,130,246,0.3);
            border-radius:8px; transition:all 0.2s;
        }}
        .links a:hover {{ background:rgba(59,130,246,0.1); border-color:var(--accent); }}

        /* Countdown */
        .countdown {{
            font-size:0.7rem; color:var(--muted); margin-left:12px;
        }}

        /* Info row */
        .info-row {{
            display:flex; gap:20px; flex-wrap:wrap; padding:8px 0;
        }}
        .info-item {{
            display:flex; flex-direction:column;
        }}
        .info-item .label {{ font-size:0.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; }}
        .info-item .value {{ font-size:0.9rem; font-weight:600; margin-top:2px; }}

        code {{ font-family:'Courier New',monospace; font-size:0.8rem; }}

        @media (max-width:1200px) {{
            .grid-4 {{ grid-template-columns: repeat(2, 1fr); }}
            .grid-3 {{ grid-template-columns: 1fr; }}
            .grid-2-1 {{ grid-template-columns: 1fr; }}
        }}
        @media (max-width:768px) {{
            .grid-4 {{ grid-template-columns: 1fr; }}
            body {{ padding: 16px; }}
        }}
    </style>
</head>
<body>
    <!-- Header -->
    <div class="header">
        <div>
            <h1>🛡️ Giám Sát Hệ Thống</h1>
            <div class="header-sub">
                Thời gian hoạt động: <strong>{sys_m.get('uptime','N/A')}</strong>
                &nbsp;|&nbsp; Cập nhật lúc: <span id="last-update">{datetime.now().strftime('%H:%M:%S')}</span>
                <span class="countdown" id="countdown">Làm mới sau 5s</span>
            </div>
        </div>
        <div class="live-badge">
            <span class="live-dot"></span> Trực Tiếp
        </div>
    </div>

    <!-- Row 1: System Gauges -->
    <div class="grid grid-4">
        <div class="card">
            <div class="card-h">🖥️ CPU</div>
            <div class="gauge">
                <svg viewBox="0 0 100 100">
                    <circle cx="50" cy="50" r="42" fill="none" stroke="#1e293b" stroke-width="7"/>
                    <circle cx="50" cy="50" r="42" fill="none" stroke="{gc(cpu_p)}" stroke-width="7"
                        stroke-dasharray="264" stroke-dashoffset="{264 - (264 * float(cpu_p or 0) / 100)}"
                        stroke-linecap="round"/>
                </svg>
                <div class="gauge-v" style="color:{gc(cpu_p)}">{cpu_p}%</div>
            </div>
            <div class="gauge-label">{sys_m.get('cpu_cores',1)} nhân</div>
            <div class="stat-sub" style="text-align:center">
                Tải: {sys_m.get('load_1m','?')} / {sys_m.get('load_5m','?')} / {sys_m.get('load_15m','?')}
            </div>
        </div>

        <div class="card">
            <div class="card-h">🧠 RAM</div>
            <div class="gauge">
                <svg viewBox="0 0 100 100">
                    <circle cx="50" cy="50" r="42" fill="none" stroke="#1e293b" stroke-width="7"/>
                    <circle cx="50" cy="50" r="42" fill="none" stroke="{gc(ram_p)}" stroke-width="7"
                        stroke-dasharray="264" stroke-dashoffset="{264 - (264 * float(ram_p or 0) / 100)}"
                        stroke-linecap="round"/>
                </svg>
                <div class="gauge-v" style="color:{gc(ram_p)}">{ram_p}%</div>
            </div>
            <div class="gauge-label">{sys_m.get('ram_used_mb',0):,} / {sys_m.get('ram_total_mb',0):,} MB</div>
            <div class="stat-sub" style="text-align:center">
                Swap: {sys_m.get('swap_used_mb',0):,} / {sys_m.get('swap_total_mb',0):,} MB
            </div>
        </div>

        <div class="card">
            <div class="card-h">💾 Ổ Đĩa ({sys_m.get('disk_type', 'N/A')})</div>
            <div class="gauge">
                <svg viewBox="0 0 100 100">
                    <circle cx="50" cy="50" r="42" fill="none" stroke="#1e293b" stroke-width="7"/>
                    <circle cx="50" cy="50" r="42" fill="none" stroke="{gc(disk_p)}" stroke-width="7"
                        stroke-dasharray="264" stroke-dashoffset="{264 - (264 * float(disk_p or 0) / 100)}"
                        stroke-linecap="round"/>
                </svg>
                <div class="gauge-v" style="color:{gc(disk_p)}">{disk_p}%</div>
            </div>
            <div class="gauge-label">{sys_m.get('disk_used_gb',0)} / {sys_m.get('disk_total_gb',0)} GB</div>
            <div class="stat-sub" style="text-align:center">
                Còn trống: {sys_m.get('disk_free_gb',0)} GB
            </div>
        </div>

        <div class="card">
            <div class="card-h">📡 Mạng & I/O</div>
            <div style="padding:8px 0">
                <div class="info-row">
                    <div class="info-item">
                        <span class="label">⬇ Nhận</span>
                        <span class="value" style="color:#22c55e">{sys_m.get('net_rx_mb',0):,} MB</span>
                    </div>
                    <div class="info-item">
                        <span class="label">⬆ Gửi</span>
                        <span class="value" style="color:#3b82f6">{sys_m.get('net_tx_mb',0):,} MB</span>
                    </div>
                </div>
                <div class="info-row" style="margin-top:8px">
                    <div class="info-item">
                        <span class="label">📖 Đọc đĩa</span>
                        <span class="value">{sys_m.get('disk_read_mb',0):,} MB</span>
                    </div>
                    <div class="info-item">
                        <span class="label">📝 Ghi đĩa</span>
                        <span class="value">{sys_m.get('disk_write_mb',0):,} MB</span>
                    </div>
                </div>
                <div style="margin-top:10px;font-size:0.7rem;color:var(--muted)">
                    Tiến trình: <strong>{sys_m.get('process_count',0)}</strong>
                </div>
            </div>
        </div>
    </div>

    <!-- Row 2: Pipeline + ML + Fraud Stats -->
    <div class="section">
        <div class="grid grid-3">
            <div class="card">
                <div class="card-h">📊 Thống Kê Pipeline</div>
                <div style="display:flex;flex-direction:column;gap:16px">
                    <div>
                        <div class="stat-label">Tổng giao dịch</div>
                        <div class="stat-value" style="color:#3b82f6">{db.get('total_transactions',0):,}</div>
                    </div>
                    <div>
                        <div class="stat-label">Gian lận phát hiện</div>
                        <div class="stat-value" style="color:#ef4444">{db.get('fraud_transactions',0):,}</div>
                    </div>
                    <div style="display:flex;gap:24px">
                        <div>
                            <div class="stat-label">Tỷ lệ gian lận</div>
                            <div style="font-size:1.1rem;font-weight:700;color:#f59e0b">{db.get('fraud_rate',0)}%</div>
                        </div>
                    </div>
                    <div>
                        <div class="stat-label">Cập nhật cuối</div>
                        <div style="font-size:0.82rem;color:var(--text)">{db.get('last_ingested','N/A')}</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-h">🤖 Mô Hình ML (Mới Nhất)</div>
                <table>
                    <tr><td style="color:var(--muted)">F1-Score</td>
                        <td style="color:#22c55e;font-weight:700;font-size:1.1rem;text-align:right">{gv(ml.get('f1_score',0))}</td></tr>
                    <tr><td style="color:var(--muted)">AUPRC</td>
                        <td style="font-weight:600;text-align:right">{gv(ml.get('auprc',0))}</td></tr>
                    <tr><td style="color:var(--muted)">AUC-ROC</td>
                        <td style="font-weight:600;text-align:right">{gv(ml.get('auc_roc',0))}</td></tr>
                    <tr><td style="color:var(--muted)">Precision</td>
                        <td style="font-weight:600;text-align:right">{gv(ml.get('precision',0))}</td></tr>
                    <tr><td style="color:var(--muted)">Recall</td>
                        <td style="font-weight:600;text-align:right">{gv(ml.get('recall',0))}</td></tr>
                </table>
            </div>

            <div class="card">
                <div class="card-h">🏴 Gian Lận Theo Loại GD</div>
                {fraud_type_items if fraud_type_items else '<div style="color:var(--muted);font-size:0.82rem">Chưa có dữ liệu</div>'}
            </div>
        </div>
    </div>

    <!-- Row 3: Recent Fraud + Top Fraud -->
    <div class="section">
        <div class="grid grid-2-1">
            <div class="card">
                <div class="card-h">🚨 Cảnh Báo Gian Lận Gần Đây</div>
                <table>
                    <thead><tr>
                        <th>Nguồn</th><th>Đích</th><th>Số Tiền</th>
                        <th>Loại</th><th>Lý Do</th><th>Thời Gian</th>
                    </tr></thead>
                    <tbody>
                        {recent_fraud_rows if recent_fraud_rows else '<tr><td colspan="6" style="color:var(--muted);text-align:center">Chưa có cảnh báo</td></tr>'}
                    </tbody>
                </table>
            </div>

            <div class="card">
                <div class="card-h">🏆 Top Tài Khoản Gian Lận</div>
                <table>
                    <thead><tr><th>#</th><th>Tài Khoản</th><th>Số Lần</th><th>Tổng Tiền</th></tr></thead>
                    <tbody>
                        {top_fraud_rows if top_fraud_rows else '<tr><td colspan="4" style="color:var(--muted);text-align:center">Chưa có dữ liệu</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Row 4: Docker Services -->
    <div class="section">
        <div class="card">
            <div class="card-h">
                🐳 Dịch Vụ Docker
                <span class="badge {'bg-ok' if running_count == total_count else 'bg-warn'}" style="margin-left:auto">
                    {running_count}/{total_count} đang chạy
                </span>
            </div>
            <table>
                <thead><tr style="color:var(--muted)">
                    <th>Tên Dịch Vụ</th><th>Image</th><th>Trạng Thái</th><th>Cổng</th><th>Khởi Động</th>
                </tr></thead>
                <tbody>{container_rows}</tbody>
            </table>
        </div>
    </div>

    <!-- Links -->
    <div class="links">
        <a href="/docs">📄 Swagger API</a>
        <a href="http://{os.getenv('HOST_IP','140.245.127.238')}:8501">📊 Streamlit Dashboard</a>
        <a href="http://{os.getenv('HOST_IP','140.245.127.238')}:5050">🧪 MLflow UI</a>
        <a href="http://{os.getenv('HOST_IP','140.245.127.238')}:9000">📡 Kafdrop (Kafka)</a>
    </div>

    <div style="text-align:center;margin-top:24px;font-size:0.65rem;color:var(--muted)">
        Fraud Detection System — Giám sát thời gian thực &copy; 2026
    </div>

    <!-- AJAX auto-refresh: chỉ cập nhật nội dung, KHÔNG reload toàn trang -->
    <script>
        let countdown = 5;
        const countdownEl = document.getElementById('countdown');
        const lastUpdateEl = document.getElementById('last-update');

        // Đếm ngược hiển thị
        setInterval(() => {{
            countdown--;
            if (countdown <= 0) countdown = 5;
            countdownEl.textContent = `Làm mới sau ${{countdown}}s`;
        }}, 1000);

        // Fetch nội dung mới mỗi 5s bằng AJAX
        async function refreshDashboard() {{
            try {{
                const resp = await fetch('/health', {{
                    headers: {{ 'X-Requested-With': 'XMLHttpRequest' }}
                }});
                if (!resp.ok) return;
                const html = await resp.text();

                // Parse HTML mới và chỉ thay nội dung body
                const parser = new DOMParser();
                const doc = parser.parseFromString(html, 'text/html');
                const newBody = doc.body;

                // Giữ nguyên script, chỉ cập nhật các phần nội dung
                const currentCards = document.querySelectorAll('.header, .grid, .section, .links');
                const newCards = newBody.querySelectorAll('.header, .grid, .section, .links');

                newCards.forEach((newEl, i) => {{
                    if (currentCards[i]) {{
                        currentCards[i].innerHTML = newEl.innerHTML;
                    }}
                }});

                // Cập nhật thời gian
                const now = new Date();
                const timeStr = now.toLocaleTimeString('vi-VN');
                if (lastUpdateEl) lastUpdateEl.textContent = timeStr;

                countdown = 5;
            }} catch (e) {{
                console.warn('[Dashboard] Lỗi cập nhật:', e);
            }}
        }}

        setInterval(refreshDashboard, 5000);
    </script>
</body></html>"""
        return html
    except Exception as e:
        error_info = traceback.format_exc()
        print(f"[Dashboard] Render Error: {error_info}")
        return f"<html><body style='background:#0a0e1a;color:#ef4444;padding:40px;font-family:monospace'><h1>⚠️ Lỗi Dashboard</h1><pre>{error_info}</pre></body></html>"
