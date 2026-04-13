"""
streamlit_app.py — Dashboard nâng cấp
Hiển thị live fraud feed + model metrics + blacklist stats, Transaction Explorer & Analytics
"""
import os
import time
import redis
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

st.set_page_config(
    page_title="Bảng Điều Khiển Phát Hiện Gian Lận",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Config ────────────────────────────────────────────────────────
DB_URL = os.getenv("DATABASE_URL", "postgresql://fraud_user:fraud_pass@postgres:5432/fraud_db")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://fastapi:8000")

engine = create_engine(DB_URL)
r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

# ── Header ────────────────────────────────────────────────────────
st.title("🛡️ Hệ Thống Phát Hiện Gian Lận Thời Gian Thực")
st.markdown("**Tập Dữ Liệu:** PaySim (6.3M giao dịch ví điện tử)")

# ── Sidebar: Manual injection & Settings ──────────────────────────
with st.sidebar:
    st.header("⚡ Nhập Giao Dịch Thủ Công")
    st.caption("Demo: gửi giao dịch trực tiếp vào pipeline")
    
    if st.button("🔴 Gửi Giao Dịch GIAN LẬN", use_container_width=True, type="primary"):
        try:
            resp = requests.post(f"{FASTAPI_URL}/blacklist-transaction")
            if resp.status_code == 200:
                st.success("✅ Đã gửi! Kiểm tra Live Feed bên dưới")
            else:
                st.error(f"Lỗi: {resp.text}")
        except Exception as e:
            st.error(f"Không kết nối được FastAPI: {e}")

    st.divider()
    st.header("📊 Thông Tin Mô Hình")
    try:
        runs = requests.post(
            f"{MLFLOW_URL}/api/2.0/mlflow/runs/search",
            json={"experiment_ids": ["0", "1", "2"], "max_results": 1,
                  "order_by": ["metrics.f1_score DESC"]}
        ).json()
        if runs.get("runs"):
            metrics_list = runs["runs"][0]["data"]["metrics"]
            metrics = {m["key"]: m["value"] for m in metrics_list}
            st.metric("Điểm F1", f"{metrics.get('f1_score', 0):.4f}")
            st.metric("Chỉ số AUPRC", f"{metrics.get('auprc', 0):.4f}")
            st.metric("Chỉ số AUC-ROC", f"{metrics.get('auc_roc', 0):.4f}")
    except Exception as e:
        st.info(f"MLflow chưa có model run hoặc lỗi: {e}")

    st.divider()
    blacklist_count = r.scard("fraud:blacklist")
    st.metric("🚫 Tài Khoản Blacklist", f"{blacklist_count:,}")
    
    st.divider()
    st.header("⚙️ Cài Đặt Hiển Thị")
    auto_refresh = st.checkbox("🔄 Tự Động Làm Mới", value=True)
    refresh_interval = st.slider("⏳ Refresh (giây)", 2, 30, 5)
    st.caption("Tắt auto-refresh khi dùng Explorer/Analytics để tránh bị render lại lúc đang thao tác.")

# ── Pre-Init Schema ───────────────────────────────────────────────
try:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS shop;"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS shop.transactions (
                step BIGINT, type VARCHAR(50), amount DOUBLE PRECISION,
                "nameOrig" VARCHAR(50), "oldbalanceOrg" DOUBLE PRECISION, "newbalanceOrig" DOUBLE PRECISION,
                "nameDest" VARCHAR(50), "oldbalanceDest" DOUBLE PRECISION, "newbalanceDest" DOUBLE PRECISION,
                "isFraud" INTEGER, "isFlaggedFraud" INTEGER,
                ingested_at TIMESTAMP, balance_diff_orig DOUBLE PRECISION, balance_diff_dest DOUBLE PRECISION,
                is_transfer_or_cashout INTEGER, amount_to_balance_ratio DOUBLE PRECISION,
                blacklist_flag INTEGER, rule_fraud_flag INTEGER, is_fraud_detected INTEGER
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS shop.fraud_transactions (
                step BIGINT, type VARCHAR(50), amount DOUBLE PRECISION,
                "nameOrig" VARCHAR(50), "oldbalanceOrg" DOUBLE PRECISION, "newbalanceOrig" DOUBLE PRECISION,
                "nameDest" VARCHAR(50), "oldbalanceDest" DOUBLE PRECISION, "newbalanceDest" DOUBLE PRECISION,
                "isFraud" INTEGER, "isFlaggedFraud" INTEGER,
                ingested_at TIMESTAMP, balance_diff_orig DOUBLE PRECISION, balance_diff_dest DOUBLE PRECISION,
                is_transfer_or_cashout INTEGER, amount_to_balance_ratio DOUBLE PRECISION,
                blacklist_flag INTEGER, rule_fraud_flag INTEGER, is_fraud_detected INTEGER
            );
        """))
except Exception as e:
    st.error(f"Khởi tạo bảng thất bại: {e}")

# ── Metrics Pre-fetch ─────────────────────────────────────────────
with engine.connect() as conn:
    total = conn.execute(text("SELECT COUNT(*) FROM shop.transactions")).scalar() or 0
    fraud_total = conn.execute(text("SELECT COUNT(*) FROM shop.fraud_transactions")).scalar() or 0
    fraud_rate = (fraud_total / total * 100) if total > 0 else 0
    avg_amount = conn.execute(text("SELECT AVG(amount) FROM shop.transactions")).scalar() or 0

# ── Tabs Configuration ────────────────────────────────────────────
tab_dashboard, tab_explorer, tab_analytics = st.tabs(["🚀 Dashboard Thời Gian Thực", "🔍 Khám Phá Giao Dịch", "📊 Phân Tích"])

# ==================================================================
# TAB 1: DASHBOARD
# ==================================================================
with tab_dashboard:
    st.markdown("### 📡 Các Chỉ Số Hệ Thống")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📦 Tổng Số Giao Dịch", f"{total:,}")
    col2.metric("🚨 Gian Lận Đã Phát Hiện", f"{fraud_total:,}")
    col3.metric("📈 Tỷ Lệ Gian Lận", f"{fraud_rate:.3f}%")
    col4.metric("💰 Số Tiền Trung Bình", f"${avg_amount:,.2f}")
    st.divider()

    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.subheader("🔴 Cảnh Báo Gian Lận Trực Tiếp")
        with engine.connect() as conn:
            fraud_df = pd.read_sql("""
                SELECT "nameOrig", "nameDest", amount, type,
                       blacklist_flag, rule_fraud_flag, ingested_at
                FROM shop.fraud_transactions
                ORDER BY ingested_at DESC
                LIMIT 20
            """, conn)
            
        if not fraud_df.empty:
            fraud_df["amount"] = fraud_df["amount"].apply(lambda x: f"${x:,.2f}")
            # Color logic based on method
            def get_reason_and_color(row):
                if row.get("blacklist_flag") == 1:
                    return "🔴 Danh sách đen"
                elif row.get("rule_fraud_flag") == 1:
                    return "🟠 Quy tắc chặn"
                else:
                    return "🟡 Mô hình ML"
            
            fraud_df["Lý Do"] = fraud_df.apply(get_reason_and_color, axis=1)
            
            display_fraud_df = fraud_df[["nameOrig", "nameDest", "amount", "type", "Lý Do", "ingested_at"]].rename(columns={
                "nameOrig": "TK Gửi", "nameDest": "TK Nhận", "amount": "Số Tiền",
                "type": "Loại", "ingested_at": "Thời Gian"
            })
            st.dataframe(
                display_fraud_df,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Chưa có giao dịch gian lận nào được phát hiện...")

    with col_right:
        st.subheader("📊 Các Loại Giao Dịch")
        with engine.connect() as conn:
            type_df = pd.read_sql("""
                SELECT type, COUNT(*) as count,
                       SUM(CASE WHEN is_fraud_detected = 1 THEN 1 ELSE 0 END) as fraud_count
                FROM shop.transactions
                GROUP BY type
                ORDER BY count DESC
            """, conn)
        if not type_df.empty:
            fig = px.bar(
                type_df, x="type", y=["count", "fraud_count"],
                barmode="overlay",
                color_discrete_map={"count": "#4CAF50", "fraud_count": "#F44336"},
                labels={"value": "Số lượng", "type": "Loại Giao Dịch"},
            )
            fig.update_layout(height=280, margin=dict(t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("📈 Lượng Gian Lận Tích Lũy (1 giờ qua)")
    with engine.connect() as conn:
        time_df = pd.read_sql("""
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
        """, conn)
    if not time_df.empty:
        fig = px.area(
            time_df, x="minute", y="fraud_count",
            color_discrete_sequence=["#F44336"],
            labels={"fraud_count": "Số lượng Gian Lận", "minute": "Thời gian"},
        )
        fig.update_layout(height=200, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

# ==================================================================
# TAB 2: EXPLORER
# ==================================================================
with tab_explorer:
    st.markdown("### 🔍 Khám Phá Giao Dịch")
    
    col_ds, col_tp, col_dm, col_sr = st.columns(4)
    data_source_opts = {"shop.transactions": "Toàn bộ hệ thống", "shop.fraud_transactions": "Chỉ Gian Lận"}
    selected_source_title = col_ds.selectbox("1. Nguồn Dữ Liệu", list(data_source_opts.values()), index=0)
    table_name = [k for k, v in data_source_opts.items() if v == selected_source_title][0]
    
    type_mapping = {"Chuyển khoản": "TRANSFER", "Rút tiền": "CASH_OUT", "Nạp tiền": "CASH_IN", "Thanh toán": "PAYMENT", "Ghi nợ": "DEBIT"}
    selected_types = col_tp.multiselect("2. Loại Giao Dịch", list(type_mapping.keys()))
    filter_type = [type_mapping[t] for t in selected_types]
    
    method_mapping = {"Danh sách đen": "Blacklist", "Quy tắc": "Rule-based", "Mô hình ML": "ML Model"}
    selected_methods = col_dm.multiselect("3. Bộ Lọc Lý Do", list(method_mapping.keys()))
    filter_method = [method_mapping[m] for m in selected_methods]
    
    search_term = col_sr.text_input("4. Tìm ID Tài Khoản (Gửi/Nhận)")
    
    col_sort, col_order, col_page = st.columns([1, 1, 2])
    sort_mapping = {"Thời gian nhập": "ingested_at", "Số tiền": "amount", "Bước": "step"}
    sort_display = col_sort.selectbox("Sắp Xếp Theo", list(sort_mapping.keys()))
    sort_by = sort_mapping[sort_display]
    
    order_mapping = {"Giảm dần": "DESC", "Tăng dần": "ASC"}
    order_display = col_order.selectbox("Thứ Tự", list(order_mapping.keys()))
    sort_order = order_mapping[order_display]
    
    limit = 50
    page = col_page.number_input("Trang số", min_value=1, value=1, step=1)
    offset = (page - 1) * limit
    
    where_clauses = []
    
    if filter_type:
        types_str = ", ".join([f"'{t}'" for t in filter_type])
        where_clauses.append(f"type IN ({types_str})")
        
    if filter_method:
        method_conds = []
        if "Blacklist" in filter_method:
            method_conds.append("(blacklist_flag = 1)")
        if "Rule-based" in filter_method:
            method_conds.append("(rule_fraud_flag = 1 AND blacklist_flag = 0)")
        if "ML Model" in filter_method:
            # Assumed ML model logic fallback
            method_conds.append("(is_fraud_detected = 1 AND blacklist_flag = 0 AND rule_fraud_flag = 0)")
        if method_conds:
            where_clauses.append("(" + " OR ".join(method_conds) + ")")
            
    if search_term:
        where_clauses.append(f'("nameOrig" ILIKE \'%%{search_term}%%\' OR "nameDest" ILIKE \'%%{search_term}%%\')')

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)
        
    query = f"""
        SELECT * FROM {table_name}
        {where_sql}
        ORDER BY "{sort_by}" {sort_order}
        LIMIT {limit} OFFSET {offset}
    """
    
    count_query = f"SELECT COUNT(*) FROM {table_name} {where_sql}"
    
    with engine.connect() as conn:
        try:
            total_rows_query = conn.execute(text(count_query)).scalar() or 0
            if total_rows_query > 0:
                df_explore = pd.read_sql(text(query), conn)
                st.caption(f"Trang {page} - Hiển thị 50 dòng trên tổng số {total_rows_query:,} kết quả")
                df_explore["amount"] = df_explore["amount"].apply(lambda x: f"${x:,.2f}")
                col_rename_map = {
                    "step": "Bước", "type": "Loại", "amount": "Số Tiền",
                    "nameOrig": "TK Gửi", "oldbalanceOrg": "Số Dư Cũ (Gửi)",
                    "newbalanceOrig": "Số Dư Mới (Gửi)", "nameDest": "TK Nhận",
                    "oldbalanceDest": "Số Dư Cũ (Nhận)", "newbalanceDest": "Số Dư Mới (Nhận)",
                    "isFraud": "Gian Lận", "isFlaggedFraud": "Cờ Gian Lận",
                    "ingested_at": "Thời Gian Nhập",
                    "balance_diff_orig": "Chênh Lệch SD Gửi",
                    "balance_diff_dest": "Chênh Lệch SD Nhận",
                    "is_transfer_or_cashout": "Chuyển/Rút Tiền",
                    "amount_to_balance_ratio": "Tỷ Lệ Tiền/Số Dư",
                    "blacklist_flag": "Cờ Blacklist", "rule_fraud_flag": "Cờ Quy Tắc",
                    "is_fraud_detected": "Phát Hiện Gian Lận"
                }
                df_explore = df_explore.rename(columns=col_rename_map)
                st.dataframe(df_explore, use_container_width=True)
            else:
                st.info("Không tìm thấy kết quả phù hợp với bộ lọc!")
        except Exception as e:
            st.error(f"Lỗi Query Explorer: {e}")

# ==================================================================
# TAB 3: ANALYTICS
# ==================================================================
with tab_analytics:
    st.markdown("### 📊 Phân Tích Chuyên Sâu")
    
    col_ch1, col_ch2 = st.columns(2)
    
    with col_ch1:
        st.markdown("**Phân Bổ Số Tiền (Gian Lận vs Bình Thường)**")
        with engine.connect() as conn:
            hist_df = pd.read_sql("""
                SELECT amount, is_fraud_detected
                FROM shop.transactions
                WHERE amount < 2000000
                ORDER BY RANDOM()
                LIMIT 15000
            """, conn)
        if not hist_df.empty:
            hist_df["Phân Loại"] = hist_df["is_fraud_detected"].apply(lambda x: "Gian Lận" if x == 1 else "Bình Thường")
            fig_hist = px.histogram(
                hist_df, x="amount", color="Phân Loại", nbins=50,
                color_discrete_map={"Bình Thường": "#4CAF50", "Gian Lận": "#F44336"},
                barmode="overlay", opacity=0.75, range_x=[0, 1000000],
                labels={"amount": "Số Tiền Giao Dịch ($)"}
            )
            fig_hist.update_layout(margin=dict(t=10))
            st.plotly_chart(fig_hist, use_container_width=True)
            
    with col_ch2:
        st.markdown("**Số Lượng Gian Lận Theo Giờ (Step % 24)**")
        with engine.connect() as conn:
            hour_df = pd.read_sql("""
                SELECT MOD(step, 24) as hour, COUNT(*) as fraud_count
                FROM shop.fraud_transactions
                GROUP BY hour
                ORDER BY hour
            """, conn)
        if not hour_df.empty:
            fig_bar = px.bar(
                hour_df, x="hour", y="fraud_count",
                labels={"hour": "Giờ trong ngày (0-23)", "fraud_count": "Số lượng Gian Lận"},
                color_discrete_sequence=["#FF9800"]
            )
            fig_bar.update_xaxes(tickmode="linear", dtick=1)
            fig_bar.update_layout(margin=dict(t=10))
            st.plotly_chart(fig_bar, use_container_width=True)
            
    st.divider()
    st.markdown("**🏆 Top 10 Tài Khoản (nameOrig) Có Nhiều Gian Lận Nhất**")
    with engine.connect() as conn:
        top_acc_df = pd.read_sql("""
            SELECT "nameOrig" as "Tài Khoản", COUNT(*) as "Tổng Số Lần Gian Lận", SUM(amount) as "Tổng Số Tiền Bị Đánh Cắp"
            FROM shop.fraud_transactions
            GROUP BY "nameOrig"
            ORDER BY "Tổng Số Lần Gian Lận" DESC
            LIMIT 10
        """, conn)
    if not top_acc_df.empty:
        top_acc_df["Tổng Số Tiền Bị Đánh Cắp"] = top_acc_df["Tổng Số Tiền Bị Đánh Cắp"].apply(lambda x: f"${x:,.2f}")
        st.table(top_acc_df)

if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()