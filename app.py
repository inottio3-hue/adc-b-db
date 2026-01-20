import streamlit as st
import pandas as pd
import requests
import datetime
import calendar

# ページ設定
st.set_page_config(page_title="案件進捗管理ダッシュボード", layout="wide")

# タイトル
st.title("📊 案件進捗管理ダッシュボード")

# --- サイドバー設定 ---
st.sidebar.header("設定 / フィルタ")

# 1. API Key入力
api_key = st.sidebar.text_input("MicroAd API Key", type="password")

# 2. 期間選択
today = datetime.date.today()
first_day = today.replace(day=1)
start_date = st.sidebar.date_input("開始日", first_day)
end_date = st.sidebar.date_input("終了日", today - datetime.timedelta(days=1))

# ★追加：表示モードの切替
st.sidebar.markdown("---")
view_mode = st.sidebar.radio(
    "表示単位を選択",
    ("キャンペーン別", "アカウント別（顧客合計）")
)

# --- データ取得関数 ---
def get_microad_data(api_key, start, end):
    url = "https://report.ads-api.universe.microad.jp/v2/reports"
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "start_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "report_type": "campaign"
    }
    try:
        response = requests.request("GET", url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        return None

# --- 色分けロジック関数 ---
def color_diff(val):
    if val > 10:
        return 'color: blue; font-weight: bold;'
    elif 0 <= val <= 10:
        return 'color: black;'
    elif -10 <= val < 0:
        return 'color: #D4AC0D; font-weight: bold;'
    else:
        return 'color: red; font-weight: bold;'

# --- メイン処理 ---
if st.sidebar.button("データ取得"):
    if not api_key:
        st.warning("API Keyを入力してください。")
    else:
        with st.spinner("データを取得中..."):
            data = get_microad_data(api_key, start_date, end_date)
            
        if data:
            # 1. マスタデータの作成
            campaigns = []
            if 'account' in data:
                for acc in data['account']:
                    acc_name = acc.get('name', 'Unknown')
                    if 'campaign' in acc:
                        for camp in acc['campaign']:
                            # 予算取得
                            target_month = start_date.strftime("%Y%m")
                            monthly_limit = 0
                            if 'campaign_monthly_charge_limit' in camp:
                                for limit in camp['campaign_monthly_charge_limit']:
                                    if limit.get('month') == target_month:
                                        monthly_limit = limit.get('charge_limit', 0)
                                        break
                            
                            campaigns.append({
                                'campaign_id': camp['id'],
                                'account_name': acc_name,
                                'campaign_name': camp['name'],
                                'monthly_budget': monthly_limit
                            })
            
            master_df = pd.DataFrame(campaigns)

            # 2. 実績データの作成
            records = []
            if 'report' in data and 'records' in data['report']:
                records = data['report']['records']
            
            if not records:
                st.warning("指定期間の配信実績データがありません。")
            else:
                perf_df = pd.DataFrame(records)
                
                # 数値変換
                numeric_cols = ['net', 'gross', 'impression', 'click']
                for col in numeric_cols:
                    if col in perf_df.columns:
                        perf_df[col] = pd.to_numeric(perf_df[col], errors='coerce').fillna(0)
                
                # 日付変換
                if 'target_date' in perf_df.columns:
                    perf_df['target_date'] = pd.to_datetime(perf_df['target_date'].astype(str))
                
                # --- A. 期間合計の集計 ---
                agg_df = perf_df.groupby('campaign_id')[numeric_cols].sum().reset_index()
                
                # --- B. 前日比データの作成 ---
                if 'target_date' in perf_df.columns and not perf_df.empty:
                    latest_date = perf_df['target_date'].max()
                    prev_date = latest_date - datetime.timedelta(days=1)
                    
                    target_cols = ['gross', 'impression', 'click']
                    
                    # 昨日
                    latest_df = perf_df[perf_df['target_date'] == latest_date].groupby('campaign_id')[target_cols].sum().reset_index()
                    latest_df = latest_df.rename(columns={'gross':'latest_gross', 'impression':'latest_imp', 'click':'latest_click'})
                    
                    # 一昨日
                    prev_df = perf_df[perf_df['target_date'] == prev_date].groupby('campaign_id')[target_cols].sum().reset_index()
                    prev_df = prev_df.rename(columns={'gross':'prev_gross', 'impression':'prev_imp', 'click':'prev_click'})
                    
                    daily_diff_df = pd.merge(latest_df, prev_df, on='campaign_id', how='left').fillna(0)
                    daily_diff_df['diff_gross'] = daily_diff_df['latest_gross'] - daily_diff_df['prev_gross']
                    daily_diff_df['diff_imp'] = daily_diff_df['latest_imp'] - daily_diff_df['prev_imp']
                    daily_diff_df['diff_click'] = daily_diff_df['latest_click'] - daily_diff_df['prev_click']
                else:
                    daily_diff_df = pd.DataFrame(columns=['campaign_id', 'latest_gross', 'diff_gross', 'latest_imp', 'diff_imp', 'latest_click', 'diff_click'])

                # 3. 全データを結合（キャンペーンレベル）
                merged_df = pd.merge(agg_df, master_df, on='campaign_id', how='left')
                merged_df = pd.merge(merged_df, daily_diff_df, on='campaign_id', how='left')
                
                # ==========================================
                # ★ここで表示モードによる分岐処理
                # ==========================================
                if view_mode == "アカウント別（顧客合計）":
                    # アカウント名で集計（合計する）
                    # 数値項目を全部足し合わせる
                    sum_cols = [
                        'monthly_budget', 'gross', 
                        'latest_gross', 'diff_gross', 
                        'latest_imp', 'diff_imp',
                        'latest_click', 'diff_click',
                        'impression', 'click'
                    ]
                    display_df = merged_df.groupby('account_name')[sum_cols].sum().reset_index()
                    # キャンペーン名は「(アカウント計)」などの表記にするか、列を削除
                    display_df['campaign_name'] = '（アカウント合計）'
                    
                    # フィルタ用カラム設定
                    filter_col_name = 'account_name'
                    filter_label = "アカウント名で絞り込み"
                    
                else:
                    # キャンペーン別（そのまま）
                    display_df = merged_df.copy()
                    filter_col_name = 'campaign_name'
                    filter_label = "キャンペーン名で絞り込み"

                # ------------------------------------------
                # 共通計算処理（進捗率・乖離などは集計後に再計算する）
                # ------------------------------------------
                
                # 理想進捗率
                year = end_date.year
                month = end_date.month
                _, num_days_in_month = calendar.monthrange(year, month)
                days_elapsed = end_date.day
                standard_pacing = (days_elapsed / num_days_in_month) * 100
                
                # 実績進捗率 (再計算)
                display_df['progress_percent'] = display_df.apply(
                    lambda x: (x['gross'] / x['monthly_budget'] * 100) if x['monthly_budget'] > 0 else 0, axis=1
                )
                
                # 進捗前日比 (再計算)
                display_df['daily_progress_diff'] = display_df.apply(
                    lambda x: (x['latest_gross'] / x['monthly_budget'] * 100) if x['monthly_budget'] > 0 else 0, axis=1
                )
                
                # 乖離 (再計算)
                display_df['diff_point'] = display_df['progress_percent'] - standard_pacing

                # --- 表示用カラム整理 ---
                final_df = display_df[[
                    'account_name', 'campaign_name', 
                    'monthly_budget', 
                    'gross', 
                    'progress_percent', 'daily_progress_diff',
                    'diff_point',
                    'latest_gross', 'diff_gross', 
                    'latest_imp', 'diff_imp',
                    'latest_click', 'diff_click'
                ]].copy()
                
                final_df.columns = [
                    'アカウント名', 'キャンペーン名', 
                    '当月予算', 
                    '期間消化額', 
                    '進捗率(%)', '進捗前日比',
                    '乖離(pt)',
                    '昨日消化', '消化前日比',
                    '昨日IMP', 'IMP前日比',
                    '昨日Click', 'Click前日比'
                ]

                # --- フィルタ機能 ---
                st.markdown("### 🔍 フィルタリング")
                
                # 表示モードに合わせてフィルタの選択肢を変える
                if view_mode == "アカウント別（顧客合計）":
                    target_col = 'アカウント名'
                else:
                    target_col = 'キャンペーン名'
                    
                all_names = final_df[target_col].unique()
                selected_names = st.multiselect(
                    f"{target_col}で絞り込み",
                    options=all_names
                )
                if selected_names:
                    final_df = final_df[final_df[target_col].isin(selected_names)]

                # --- 全体サマリ ---
                st.markdown("---")
                col1, col2, col3, col4 = st.columns(4)
                
                col1.metric("当月の理想進捗率", f"{standard_pacing:.1f}%", f"{end_date.month}/{end_date.day} 時点")
                col2.metric("合計消化額 (Gross)", f"¥{final_df['期間消化額'].sum():,.0f}")
                
                total_latest_gross = final_df['昨日消化'].sum()
                total_diff_gross = final_df['消化前日比'].sum()
                col3.metric("昨日の合計消化額", f"¥{total_latest_gross:,.0f}", f"{total_diff_gross:+,.0f} 円 (前日比)")
                
                avg_progress = final_df[final_df['当月予算'] > 0]['進捗率(%)'].mean()
                col4.metric("平均実績進捗率", f"{avg_progress:.1f}%", delta=f"{avg_progress - standard_pacing:.1f} pt")

                # --- 詳細テーブル ---
                st.markdown(f"### 📋 詳細データ（{view_mode}）")
                st.caption(f"乖離の色分け： 🟦ハイペース(>+10) | ⬛順調(0~+10) | 🟨警戒(-10~0) | 🟥危険(<-10)")
                
                styled_df = final_df.style.format({
                    '当月予算': '¥{:,.0f}',
                    '期間消化額': '¥{:,.0f}',
                    '進捗率(%)': '{:.1f}%',
                    '進捗前日比': '{:+.1f}pt',
                    '乖離(pt)': '{:+.1f}',
                    '昨日消化': '¥{:,.0f}',
                    '消化前日比': '{:+,.0f}',
                    '昨日IMP': '{:,.0f}',
                    'IMP前日比': '{:+,.0f}',
                    '昨日Click': '{:,.0f}',
                    'Click前日比': '{:+,.0f}'
                }).map(color_diff, subset=['乖離(pt)'])

                st.dataframe(
                    styled_df,
                    use_container_width=True,
                    height=600
                )