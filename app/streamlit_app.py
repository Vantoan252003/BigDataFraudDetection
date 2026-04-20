"""
streamlit_app.py — Secured Dashboard
Hiển thị live fraud feed + model metrics + blacklist stats, Transaction Explorer & Analytics
Features: Parameterized Queries, PII Masking, Cached Queries
"""
import os
import sys
import time
import re
import redis
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine, text

# ── PII Masking helper ────────────────────────────────────────────
def mask_account_id(account_id: str, visible_chars: int = 4) -> str:
    """Mask account ID: C1234567890 → C1234******"""
    if not account_id or len(account_id) <= visible_chars + 1:
        return account_id
    prefix = account_id[:visible_chars + 1]
    masked = prefix + "*" * (len(account_id) - visible_chars - 1)
    return masked

def sanitize_input(user_input: str, max_length: int = 50) -> str:
    """Sanitize user input — chỉ giữ alphanumeric"""
    if not user_input:
        return ""
    sanitized = user_input[:max_length]
    sanitized = re.sub(r"[^a-zA-Z0-9\s\-_]", "", sanitized)
    return sanitized.strip()

st.set_page_config(
    page_title="Fraud Detection Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Config ────────────────────────────────────────────────────────
DB_URL = os.getenv("DATABASE_URL", "postgresql://fraud_user:fraud_pass@postgres:5432/fraud_db")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://fastapi:8000")
API_KEY = os.getenv("FRAUD_API_KEY", "")

engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=300)
r = redis.Redis(host=REDIS_HOST, port=6379, password=REDIS_PASSWORD, decode_responses=True)

# ── Header ────────────────────────────────────────────────────────
st.title("🛡️ Real-Time Fraud Detection System")
st.markdown("**Dataset:** PaySim (6.3M giao dịch ví điện tử) | 🔒 **Security Enabled**")

# ── Sidebar: Manual injection & Settings ──────────────────────────
with st.sidebar:
    st.header("⚡ Manual Transaction Injection")
    st.caption("Demo: gửi giao dịch trực tiếp vào pipeline")

    if st.button("🔴 Gửi Giao Dịch GIAN LẬN", use_container_width=True, type="primary"):
        try:
            headers = {"X-API-Key": API_KEY} if API_KEY else {}
            resp = requests.post(f"{FASTAPI_URL}/blacklist-transaction", headers=headers)
            if resp.status_code == 200:
                st.success("✅ Đã gửi! Kiểm tra Live Feed bên dưới")
            elif resp.status_code == 401:
                st.error("🔒 API Key không hợp lệ!")
            elif resp.status_code == 429:
                st.warning("⏳ Rate limit — thử lại sau 60 giây")
            else:
                st.error(f"Lỗi: {resp.status_code}")
        except Exception as e:
            st.error(f"Không kết nối được FastAPI: {e}")

    st.divider()
    st.header("📊 Model Info")

    @st.cache_data(ttl=60)
    def fetch_mlflow_metrics():
        try:
            resp = requests.post(
                f"{MLFLOW_URL}/api/2.0/mlflow/runs/search",
                json={"experiment_ids": ["0", "1", "2"], "max_results": 1,
                      "order_by": ["start_time DESC"]},
                timeout=5
            )
            resp.raise_for_status()
            runs = resp.json()
            if runs.get("runs"):
                metrics_list = runs["runs"][0]["data"]["metrics"]
                return {m["key"]: m["value"] for m in metrics_list}
            return None
        except Exception as e:
            return {"error": str(e)}

    metrics = fetch_mlflow_metrics()
    if metrics and "error" not in metrics:
        st.metric("F1-Score", f"{metrics.get('f1_score', 0):.4f}")
        st.metric("AUPRC", f"{metrics.get('auprc', 0):.4f}")
        st.metric("AUC-ROC", f"{metrics.get('auc_roc', 0):.4f}")
    else:
        err_msg = metrics.get('error', 'No runs found') if metrics else 'No runs found'
        st.info(f"Đang chờ MLflow training... ({err_msg})")

    st.divider()
    try:
        blacklist_count = r.scard("fraud:blacklist")
    except Exception:
        blacklist_count = 0
    st.metric("🚫 Blacklisted Accounts", f"{blacklist_count:,}")

    st.divider()
    st.header("🔒 Security Info")
    st.caption(f"API Key: {'✅ Configured' if API_KEY else '⚠️ Not set'}")
    st.caption(f"Redis Auth: {'✅ Enabled' if REDIS_PASSWORD else '⚠️ No password'}")

    st.divider()
    st.header("⚙️ View Settings")
    auto_refresh = st.checkbox("🔄 Auto-refresh Dashboard", value=True)
    refresh_interval = st.slider("⏳ Refresh (giây)", 2, 30, 5)
    st.caption("Tắt auto-refresh khi dùng Explorer/Analytics để tránh bị render lại lúc đang thao tác.")

# ── Metrics Pre-fetch ─────────────────────────────────────────────
with engine.connect() as conn:
    total = conn.execute(text("SELECT COUNT(*) FROM shop.transactions")).scalar() or 0
    fraud_total = conn.execute(text("SELECT COUNT(*) FROM shop.fraud_transactions")).scalar() or 0
    fraud_rate = (fraud_total / total * 100) if total > 0 else 0
    avg_amount = conn.execute(text("SELECT AVG(amount) FROM shop.transactions")).scalar() or 0

# ── Tabs Configuration ────────────────────────────────────────────
tab_dashboard, tab_explorer, tab_analytics = st.tabs(["🚀 Real-Time Dashboard", "🔍 Transaction Explorer", "📊 Analytics"])

# ==================================================================
# TAB 1: DASHBOARD
# ==================================================================
with tab_dashboard:
    st.markdown("### 📡 System Metrics")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📦 Total Transactions", f"{total:,}")
    col2.metric("🚨 Fraud Detected", f"{fraud_total:,}")
    col3.metric("📈 Fraud Rate", f"{fraud_rate:.3f}%")
    col4.metric("💰 Avg Amount", f"${avg_amount:,.2f}")
    st.divider()

    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.subheader("🔴 Live Fraud Alerts")
        with engine.connect() as conn:
            fraud_df = pd.read_sql(text("""
                SELECT "nameOrig", "nameDest", amount, type,
                       blacklist_flag, rule_fraud_flag, ingested_at
                FROM shop.fraud_transactions
                ORDER BY ingested_at DESC
                LIMIT 20
            """), conn)

        if not fraud_df.empty:
            # PII Masking — mask account IDs on display
            fraud_df["nameOrig"] = fraud_df["nameOrig"].apply(mask_account_id)
            fraud_df["nameDest"] = fraud_df["nameDest"].apply(mask_account_id)
            fraud_df["amount"] = fraud_df["amount"].apply(lambda x: f"${x:,.2f}")

            def get_reason_and_color(row):
                if row.get("blacklist_flag") == 1:
                    return "🔴 Blacklist"
                elif row.get("rule_fraud_flag") == 1:
                    return "🟠 Rule chặn"
                else:
                    return "🟡 ML Model"

            fraud_df["Lý Do"] = fraud_df.apply(get_reason_and_color, axis=1)

            st.dataframe(
                fraud_df[["nameOrig", "nameDest", "amount", "type", "Lý Do", "ingested_at"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Chưa có fraud transaction nào được phát hiện...")

    with col_right:
        st.subheader("📊 Transaction Types")
        with engine.connect() as conn:
            type_df = pd.read_sql(text("""
                SELECT type, COUNT(*) as count,
                       SUM(CASE WHEN is_fraud_detected = 1 THEN 1 ELSE 0 END) as fraud_count
                FROM shop.transactions
                GROUP BY type
                ORDER BY count DESC
            """), conn)
        if not type_df.empty:
            fig = px.bar(
                type_df, x="type", y=["count", "fraud_count"],
                barmode="overlay",
                color_discrete_map={"count": "#4CAF50", "fraud_count": "#F44336"},
                labels={"value": "Count", "type": "Transaction Type"},
            )
            fig.update_layout(height=280, margin=dict(t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("📈 Cumulative Fraud Detections (Last 1 hour)")
    with engine.connect() as conn:
        time_df = pd.read_sql(text("""
            WITH minute_counts AS (
                SELECT date_trunc('minute', ingested_at) as minute,
                       COUNT(*) as fraud_count
                FROM shop.fraud_transactions
                WHERE ingested_at >= NOW() - INTERVAL '1 hour'
                GROUP BY minute
            )
            SELECT minute, SUM(fraud_count) OVER (ORDER BY minute) as fraud_count
            FROM minute_counts
            ORDER BY minute
        """), conn)
    if not time_df.empty:
        fig = px.area(
            time_df, x="minute", y="fraud_count",
            color_discrete_sequence=["#F44336"],
            labels={"fraud_count": "Fraud Count", "minute": "Time"},
        )
        fig.update_layout(height=200, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

# ==================================================================
# TAB 2: EXPLORER  (PARAMETERIZED QUERIES — NO SQL INJECTION)
# ==================================================================
with tab_explorer:
    st.markdown("### 🔍 Transaction Explorer")
    st.caption("🔒 All queries use parameterized binding — safe from SQL injection")

    col_ds, col_tp, col_dm, col_sr = st.columns(4)
    data_source_opts = {"shop.transactions": "Toàn bộ hệ thống", "shop.fraud_transactions": "Chỉ Fraud"}
    selected_source_title = col_ds.selectbox("1. Data Source", list(data_source_opts.values()), index=0)
    table_name = [k for k, v in data_source_opts.items() if v == selected_source_title][0]

    filter_type = col_tp.multiselect("2. Loại Giao Dịch", ["TRANSFER", "CASH_OUT", "CASH_IN", "PAYMENT", "DEBIT"])
    filter_method = col_dm.multiselect("3. Bộ Lọc Lý Do", ["Blacklist", "Rule-based", "ML Model"])
    raw_search = col_sr.text_input("4. Tìm Account ID (Orig/Dest)")

    # Sanitize search input
    search_term = sanitize_input(raw_search)

    col_sort, col_order, col_page = st.columns([1, 1, 2])
    ALLOWED_SORT_COLS = {"ingested_at", "amount", "step"}
    sort_by = col_sort.selectbox("Sắp Xếp Theo", list(ALLOWED_SORT_COLS))
    sort_order = col_order.selectbox("Thứ Tự", ["DESC", "ASC"])

    limit = 50
    page = col_page.number_input("Trang số", min_value=1, max_value=1000, value=1, step=1)
    offset = (page - 1) * limit

    # ── Build parameterized query ─────────────────────────────────
    where_clauses = []
    params = {"limit_val": limit, "offset_val": offset}

    if filter_type:
        where_clauses.append("type = ANY(:filter_types)")
        params["filter_types"] = filter_type

    if filter_method:
        method_conds = []
        if "Blacklist" in filter_method:
            method_conds.append("(blacklist_flag = 1)")
        if "Rule-based" in filter_method:
            method_conds.append("(rule_fraud_flag = 1 AND blacklist_flag = 0)")
        if "ML Model" in filter_method:
            method_conds.append("(is_fraud_detected = 1 AND blacklist_flag = 0 AND rule_fraud_flag = 0)")
        if method_conds:
            where_clauses.append("(" + " OR ".join(method_conds) + ")")

    if search_term:
        where_clauses.append("""("nameOrig" ILIKE :search_pattern OR "nameDest" ILIKE :search_pattern)""")
        params["search_pattern"] = f"%{search_term}%"

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    # Validate sort column (whitelist only)
    if sort_by not in ALLOWED_SORT_COLS:
        sort_by = "ingested_at"
    if sort_order not in ("ASC", "DESC"):
        sort_order = "DESC"

    # Table name is from a hardcoded dict, not user input — safe
    query = f"""
        SELECT * FROM {table_name}
        {where_sql}
        ORDER BY "{sort_by}" {sort_order}
        LIMIT :limit_val OFFSET :offset_val
    """

    count_query = f"SELECT COUNT(*) FROM {table_name} {where_sql}"

    with engine.connect() as conn:
        try:
            total_rows_query = conn.execute(text(count_query), params).scalar() or 0
            if total_rows_query > 0:
                df_explore = pd.read_sql(text(query), conn, params=params)

                # PII Masking
                if "nameOrig" in df_explore.columns:
                    df_explore["nameOrig"] = df_explore["nameOrig"].apply(mask_account_id)
                if "nameDest" in df_explore.columns:
                    df_explore["nameDest"] = df_explore["nameDest"].apply(mask_account_id)

                st.caption(f"Trang {page} - Hiển thị {len(df_explore)} dòng trên tổng số {total_rows_query:,} kết quả")
                if "amount" in df_explore.columns:
                    df_explore["amount"] = df_explore["amount"].apply(lambda x: f"${x:,.2f}")
                st.dataframe(df_explore, use_container_width=True)
            else:
                st.info("Không tìm thấy kết quả phù hợp với bộ lọc!")
        except Exception as e:
            st.error(f"Lỗi Query Explorer: Không thể truy vấn dữ liệu. Thử lại sau.")

# ==================================================================
# TAB 3: ANALYTICS
# ==================================================================
with tab_analytics:
    st.markdown("### 📊 Deep Analytics")

    col_ch1, col_ch2 = st.columns(2)

    with col_ch1:
        st.markdown("**Amount Distribution (Fraud vs Normal)**")
        with engine.connect() as conn:
            hist_df = pd.read_sql(text("""
                SELECT amount, is_fraud_detected
                FROM shop.transactions
                WHERE amount < 2000000
                ORDER BY RANDOM()
                LIMIT 15000
            """), conn)
        if not hist_df.empty:
            hist_df["Type"] = hist_df["is_fraud_detected"].apply(lambda x: "Fraud" if x == 1 else "Normal")
            fig_hist = px.histogram(
                hist_df, x="amount", color="Type", nbins=50,
                color_discrete_map={"Normal": "#4CAF50", "Fraud": "#F44336"},
                barmode="overlay", opacity=0.75, range_x=[0, 1000000],
                labels={"amount": "Transaction Amount ($)"}
            )
            fig_hist.update_layout(margin=dict(t=10))
            st.plotly_chart(fig_hist, use_container_width=True)

    with col_ch2:
        st.markdown("**Fraud Count By Hour (Step % 24)**")
        with engine.connect() as conn:
            hour_df = pd.read_sql(text("""
                SELECT MOD(step, 24) as hour, COUNT(*) as fraud_count
                FROM shop.fraud_transactions
                GROUP BY hour
                ORDER BY hour
            """), conn)
        if not hour_df.empty:
            fig_bar = px.bar(
                hour_df, x="hour", y="fraud_count",
                labels={"hour": "Hour of Day (0-23)", "fraud_count": "Fraud Count"},
                color_discrete_sequence=["#FF9800"]
            )
            fig_bar.update_xaxes(tickmode="linear", dtick=1)
            fig_bar.update_layout(margin=dict(t=10))
            st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()
    st.markdown("**🏆 Top 10 Accounts With Most Fraud (Masked)**")
    with engine.connect() as conn:
        top_acc_df = pd.read_sql(text("""
            SELECT "nameOrig" as "Account ID", COUNT(*) as "Total Fraud Instances", SUM(amount) as "Total Stolen Amount"
            FROM shop.fraud_transactions
            GROUP BY "nameOrig"
            ORDER BY "Total Fraud Instances" DESC
            LIMIT 10
        """), conn)
    if not top_acc_df.empty:
        # PII Masking
        top_acc_df["Account ID"] = top_acc_df["Account ID"].apply(mask_account_id)
        top_acc_df["Total Stolen Amount"] = top_acc_df["Total Stolen Amount"].apply(lambda x: f"${x:,.2f}")
        st.table(top_acc_df)

if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()