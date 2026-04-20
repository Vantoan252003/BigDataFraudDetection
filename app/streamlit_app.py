"""
streamlit_app.py — Secured Dashboard (Tiếng Việt)
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
    """Che ID tài khoản: C1234567890 → C1234******"""
    if not account_id or len(account_id) <= visible_chars + 1:
        return account_id
    prefix = account_id[:visible_chars + 1]
    masked = prefix + "*" * (len(account_id) - visible_chars - 1)
    return masked

def sanitize_input(user_input: str, max_length: int = 50) -> str:
    """Làm sạch đầu vào — chỉ giữ chữ cái và số"""
    if not user_input:
        return ""
    sanitized = user_input[:max_length]
    sanitized = re.sub(r"[^a-zA-Z0-9\s\-_]", "", sanitized)
    return sanitized.strip()

st.set_page_config(
    page_title="Hệ Thống Phát Hiện Gian Lận",
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
st.title("🛡️ Hệ Thống Phát Hiện Gian Lận Thời Gian Thực")
st.markdown("**Tập dữ liệu:** PaySim (6.3M giao dịch) | 🔒 **Bảo mật đã bật**")

# ── Sidebar: Manual injection & Settings ──────────────────────────
with st.sidebar:
    st.header("⚡ Tạo Giao Dịch Thủ Công")
    st.caption("Demo: gửi giao dịch trực tiếp vào hệ thống")

    if st.button("🔴 Gửi Giao Dịch GIAN LẬN", use_container_width=True, type="primary"):
        try:
            headers = {"X-API-Key": API_KEY} if API_KEY else {}
            resp = requests.post(f"{FASTAPI_URL}/blacklist-transaction", headers=headers)
            if resp.status_code == 200:
                st.success("✅ Đã gửi! Vui lòng kiểm tra bảng bên dưới")
            elif resp.status_code == 401:
                st.error("🔒 API Key không hợp lệ!")
            elif resp.status_code == 429:
                st.warning("⏳ Quá nhiều yêu cầu — thử lại sau 60 giây")
            else:
                st.error(f"Lỗi: {resp.status_code}")
        except Exception as e:
            st.error(f"Không kết nối được FastAPI: {e}")

    st.divider()
    st.header("📊 Thông Tin Mô Hình (ML)")

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
                metrics_list = runs["runs"][0]["data"].get("metrics", [])
                return {m["key"]: m["value"] for m in metrics_list}
            return None
        except Exception as e:
            return {"error": str(e)}

    metrics = fetch_mlflow_metrics()
    if metrics and "error" not in metrics:
        st.metric("Điểm F1 (F1-Score)", f"{metrics.get('f1_score', 0):.4f}")
        st.metric("AUPRC", f"{metrics.get('auprc', 0):.4f}")
        st.metric("AUC-ROC", f"{metrics.get('auc_roc', 0):.4f}")
    else:
        err_msg = metrics.get('error', 'Không tìm thấy run nào') if metrics else 'Không tìm thấy dữ liệu'
        st.info(f"Đang chờ MLflow training... ({err_msg})")

    st.divider()
    try:
        blacklist_count = r.scard("fraud:blacklist")
    except Exception:
        blacklist_count = 0
    st.metric("🚫 Tài Khoản Trong Sổ Đen", f"{blacklist_count:,}")

    st.divider()
    st.header("🔒 Trạng Thái Bảo Mật")
    st.caption(f"API Key: {'✅ Đã cấu hình' if API_KEY else '⚠️ Chưa cài đặt'}")
    st.caption(f"Redis Auth: {'✅ Đã bật' if REDIS_PASSWORD else '⚠️ Không có mật khẩu'}")

    st.divider()
    st.header("⚙️ Cài Đặt Hiển Thị")
    auto_refresh = st.checkbox("🔄 Tự động Làm mới Bảng Chính", value=True)
    refresh_interval = st.slider("⏳ Tốc độ làm mới (giây)", 2, 30, 5)

# ── Tabs Configuration ────────────────────────────────────────────
tab_dashboard, tab_explorer, tab_analytics = st.tabs(["🚀 Bảng Điều Khiển Real-Time", "🔍 Tìm Kiếm Giao Dịch", "📊 Thống Kê Phân Tích"])

# ==================================================================
# TAB 1: DASHBOARD
# ==================================================================
with tab_dashboard:
    @st.fragment(run_every=f"{refresh_interval}s" if auto_refresh else None)
    def render_realtime_dashboard():
        st.markdown("### 📡 Chỉ Số Hệ Thống")
        
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM shop.transactions")).scalar() or 0
            fraud_total = conn.execute(text("SELECT COUNT(*) FROM shop.fraud_transactions")).scalar() or 0
            fraud_rate = (fraud_total / total * 100) if total > 0 else 0
            avg_amount = conn.execute(text("SELECT AVG(amount) FROM shop.transactions")).scalar() or 0

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📦 Tổng Số Giao Dịch", f"{total:,}")
        col2.metric("🚨 Phát Hiện Gian Lận", f"{fraud_total:,}")
        col3.metric("📈 Tỷ Lệ Gian Lận", f"{fraud_rate:.3f}%")
        col4.metric("💰 Số Tiền G.Dịch TB", f"${avg_amount:,.2f}")
        st.divider()

        col_left, col_right = st.columns([3, 2])
        with col_left:
            st.subheader("🔴 Cảnh Báo Gian Lận Trực Tiếp")
            with engine.connect() as conn:
                fraud_df = pd.read_sql(text("""
                    SELECT "nameOrig", "nameDest", amount, type,
                           blacklist_flag, rule_fraud_flag, ingested_at
                    FROM shop.fraud_transactions
                    ORDER BY ingested_at DESC
                    LIMIT 20
                """), conn)

            if not fraud_df.empty:
                fraud_df["nameOrig"] = fraud_df["nameOrig"].apply(mask_account_id)
                fraud_df["nameDest"] = fraud_df["nameDest"].apply(mask_account_id)
                fraud_df["amount"] = fraud_df["amount"].apply(lambda x: f"${x:,.2f}")

                def get_reason_and_color(row):
                    if row.get("blacklist_flag") == 1:
                        return "🔴 Sổ Đen (Blacklist)"
                    elif row.get("rule_fraud_flag") == 1:
                        return "🟠 Chặn bằng Luật (Rule)"
                    else:
                        return "🟡 ML Model"

                fraud_df["Lý Do"] = fraud_df.apply(get_reason_and_color, axis=1)

                st.dataframe(
                    fraud_df[["nameOrig", "nameDest", "amount", "type", "Lý Do", "ingested_at"]].rename(columns={
                        "nameOrig": "Tài Khoản Gửi",
                        "nameDest": "Tài Khoản Nhận",
                        "amount": "Số Tiền",
                        "type": "Loại GD",
                        "ingested_at": "Thời Gian"
                    }),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Chưa có giao dịch gian lận nào được phát hiện...")

        with col_right:
            st.subheader("📊 Lượng Gian Lận & Tổng Theo Loại")
            with engine.connect() as conn:
                type_df = pd.read_sql(text("""
                    SELECT type, COUNT(*) as count,
                           SUM(CASE WHEN is_fraud_detected = 1 THEN 1 ELSE 0 END) as fraud_count
                    FROM shop.transactions
                    GROUP BY type
                    ORDER BY count DESC
                """), conn)
            if not type_df.empty:
                type_df.rename(columns={"count": "Tổng số GD", "fraud_count": "Số lần gian lận", "type": "Loại Giao Dịch"}, inplace=True)
                fig = px.bar(
                    type_df, x="Loại Giao Dịch", y=["Tổng số GD", "Số lần gian lận"],
                    barmode="overlay",
                    color_discrete_map={"Tổng số GD": "#4CAF50", "Số lần gian lận": "#F44336"},
                    labels={"value": "Số Lượng", "Loại Giao Dịch": "Loại Giao Dịch", "variable": "Thống kê"},
                )
                fig.update_layout(height=280, margin=dict(t=20, b=20), legend_title_text='')
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("📈 Biểu Đồ Gian Lận Theo Cập Nhật (Trong 1 giờ qua)")
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
                labels={"fraud_count": "Số Lượng Gian Lận", "minute": "Thời Gian"},
            )
            fig.update_layout(height=200, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Chưa có dữ liệu trong 1 giờ qua để vẽ biểu đồ.")

    # Call the fragment function
    render_realtime_dashboard()

# ==================================================================
# TAB 2: EXPLORER
# ==================================================================
with tab_explorer:
    st.markdown("### 🔍 Trình Tìm Kiếm Giao Dịch")
    st.caption("🔒 Tất cả câu truy vấn đã được bảo vệ khỏi tấn công SQL Injection")

    col_ds, col_tp, col_dm, col_sr = st.columns(4)
    data_source_opts = {"shop.transactions": "Toàn bộ hệ thống", "shop.fraud_transactions": "Chỉ xem Gian Lận"}
    selected_source_title = col_ds.selectbox("1. Nguồn Dữ Liệu", list(data_source_opts.values()), index=0)
    table_name = [k for k, v in data_source_opts.items() if v == selected_source_title][0]

    # Mapping for SQL Translation
    vi_to_en_map = {
        "Chuyển Khoản": "TRANSFER",
        "Rút Tiền Khách": "CASH_OUT",
        "Nạp Tiền": "CASH_IN",
        "Thanh Toán": "PAYMENT",
        "Ghi Nợ": "DEBIT"
    }
    
    filter_type = col_tp.multiselect("2. Loại Giao Dịch", options=list(vi_to_en_map.keys()))
    filter_method = col_dm.multiselect("3. Bộ Lọc Lý Do", ["Sổ Đen", "Chặn bằng Luật", "ML Model"])
    raw_search = col_sr.text_input("4. Tìm ID Tài Khoản (Gửi/Nhận)")

    search_term = sanitize_input(raw_search)

    col_sort, col_order, col_page = st.columns([1, 1, 2])
    ALLOWED_SORT_COLS = {"ingested_at", "amount", "step"}
    
    sort_opts_map = {"Vừa Cập Nhật": "ingested_at", "Số Tiền": "amount", "Theo Khung: Step": "step"}
    sort_display = col_sort.selectbox("Sắp Xếp Theo", list(sort_opts_map.keys()))
    sort_by = sort_opts_map[sort_display]
    
    sort_order_display = col_order.selectbox("Thứ Tự", ["Mới nhất/Cao nhất (DESC)", "Cũ nhất/Thấp nhất (ASC)"])
    sort_order = "DESC" if "DESC" in sort_order_display else "ASC"

    limit = 50
    page = col_page.number_input("Trang số", min_value=1, max_value=1000, value=1, step=1)
    offset = (page - 1) * limit

    where_clauses = []
    params = {"limit_val": limit, "offset_val": offset}

    if filter_type:
        where_clauses.append("type = ANY(:filter_types)")
        # Translate selected Vietnamese options back to English for DB query
        params["filter_types"] = [vi_to_en_map[vi_name] for vi_name in filter_type]

    if filter_method:
        method_conds = []
        if "Sổ Đen" in filter_method:
            method_conds.append("(blacklist_flag = 1)")
        if "Chặn bằng Luật" in filter_method:
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

                if "nameOrig" in df_explore.columns:
                    df_explore["nameOrig"] = df_explore["nameOrig"].apply(mask_account_id)
                if "nameDest" in df_explore.columns:
                    df_explore["nameDest"] = df_explore["nameDest"].apply(mask_account_id)

                df_explore.rename(columns={
                    "step": "Khung (Step)",
                    "type": "Loại",
                    "amount": "Số Tiền",
                    "nameOrig": "Tài Khoản Gửi",
                    "oldbalanceOrg": "Số Dư Gốc (Gửi)",
                    "newbalanceOrig": "Số Dư Mới (Gửi)",
                    "nameDest": "Tài Khoản Nhận",
                    "oldbalanceDest": "Số Dư Gốc (Nhận)",
                    "newbalanceDest": "Số Dư Mới (Nhận)",
                    "isFraud": "Gian Lận Thực Sư",
                    "isFlaggedFraud": "Đánh Dấu Lừa Đảo",
                    "balance_diff_orig": "Chênh Lệch Dư (Gửi)",
                    "balance_diff_dest": "Chênh Lệch Dư (Nhận)",
                    "is_transfer_or_cashout": "Loại Chuyển/Rút",
                    "amount_to_balance_ratio": "Tỷ Lệ Tiền/Dư",
                    "blacklist_flag": "Là Sổ Đen",
                    "rule_fraud_flag": "Vi Phạm Rule Kích Cỡ",
                    "is_fraud_detected": "Bắt Bởi Model",
                    "ingested_at": "Thời Gian Xử Lý"
                }, inplace=True)

                st.caption(f"Trang {page} - Đang hiển thị {len(df_explore)} dòng trên tổng số {total_rows_query:,} kết quả")
                if "Số Tiền" in df_explore.columns:
                    df_explore["Số Tiền"] = df_explore["Số Tiền"].apply(lambda x: f"${x:,.2f}")
                st.dataframe(df_explore, use_container_width=True)
            else:
                st.info("Không tìm thấy kết quả phù hợp với bộ lọc!")
        except Exception as e:
            st.error(f"Lỗi Query: Không thể truy vấn dữ liệu. Hãy thử lại.")

# ==================================================================
# TAB 3: ANALYTICS
# ==================================================================
with tab_analytics:
    st.markdown("### 📊 Thống Kê Phân Tích Chuyên Sâu")

    col_ch1, col_ch2 = st.columns(2)

    with col_ch1:
        st.markdown("**Phân Bố Giá Trị Số Tiền (Gian Lận vs Bình Thường)**")
        with engine.connect() as conn:
            hist_df = pd.read_sql(text("""
                SELECT amount, is_fraud_detected
                FROM shop.transactions
                WHERE amount < 2000000
                ORDER BY RANDOM()
                LIMIT 15000
            """), conn)
        if not hist_df.empty:
            hist_df["Loại"] = hist_df["is_fraud_detected"].apply(lambda x: "Là Gian Lận" if x == 1 else "Bình Thường")
            fig_hist = px.histogram(
                hist_df, x="amount", color="Loại", nbins=50,
                color_discrete_map={"Bình Thường": "#4CAF50", "Là Gian Lận": "#F44336"},
                barmode="overlay", opacity=0.75, range_x=[0, 1000000],
                labels={"amount": "Số Tiền Giao Dịch ($)", "count": "Số Lượng"}
            )
            fig_hist.update_layout(margin=dict(t=10), legend_title_text='')
            st.plotly_chart(fig_hist, use_container_width=True)

    with col_ch2:
        st.markdown("**Số Lần Gian Lận Theo Khung Giờ (Chu kỳ 24 Khung)**")
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
                labels={"hour": "Khung Thời Gian Tập Dữ Liệu (0-23)", "fraud_count": "Số Lần Bị Phá"},
                color_discrete_sequence=["#FF9800"]
            )
            fig_bar.update_xaxes(tickmode="linear", dtick=1)
            fig_bar.update_layout(margin=dict(t=10))
            st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()
    st.markdown("**🏆 Top 10 Tài Khoản Gian Lận Khủng Nhất (Đã che tên)**")
    with engine.connect() as conn:
        top_acc_df = pd.read_sql(text("""
            SELECT "nameOrig" as "Tài Khoản Gửi", COUNT(*) as "Số Lần Gian Lận", SUM(amount) as "Tổng Tiền Lừa Đảo"
            FROM shop.fraud_transactions
            GROUP BY "nameOrig"
            ORDER BY "Số Lần Gian Lận" DESC
            LIMIT 10
        """), conn)
    if not top_acc_df.empty:
        top_acc_df["Tài Khoản Gửi"] = top_acc_df["Tài Khoản Gửi"].apply(mask_account_id)
        top_acc_df["Tổng Tiền Lừa Đảo"] = top_acc_df["Tổng Tiền Lừa Đảo"].apply(lambda x: f"${x:,.2f}")
        st.table(top_acc_df)