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
# デフォルトは「今月1日〜昨日」
start_date = st.sidebar.date_input("開始日", first_day)
end_date = st.sidebar.date_input("終了日", today - datetime.timedelta(days=1))

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

# --- 色分けロジック1：乖離ポイント用 ---
def color_diff_pacing(val):
    """
    理想進捗との乖離
    """
    if val > 10:
        return 'color: blue; font-weight: bold;'
    elif 0 <= val <= 10:
        return 'color: black;'
    elif -10 <= val < 0:
        return 'color: #D4AC0D; font-weight: bold;' # 濃い黄色
    else:
        return 'color: red; font-weight: bold;'

# --- 色分けロジック2：前日比用（指示：マイナス赤、プラス青） ---
def color_day_diff(val):
    """
    前日比の色分け
    プラス(増加) -> 青
    マイナス(減少) -> 赤
    """
    if val > 0:
        return 'color: blue; font-weight: bold;'
    elif val < 0:
        return 'color: red; font-weight: bold;'
    else:
        return 'color: black;'

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
                            # 当月の予算を探す
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
                
                # --- B. 前日比の計算処理 ---
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
                    
                    # マージして差分計算
                    daily_diff_df = pd.merge(latest_df, prev_df, on='campaign_id', how='left').fillna(0)
                    daily_diff_df['diff_gross'] = daily_diff_df['latest_gross'] - daily_diff_df['prev_gross']
                    daily_diff_df['diff_imp'] = daily_diff_df['latest_imp'] - daily_diff_df['prev_imp']
                    daily_diff_df['diff_click'] = daily_diff_df['latest_click'] - daily_diff_df['prev_click']
                else:
                    daily_diff_df = pd.DataFrame(columns=['campaign_id', 'latest_gross', 'diff_gross', 'latest_imp', 'diff_imp', 'latest_click', 'diff_click'])

                # 3. マスタ + 期間合計 + 前日比データを結合
                merged_df = pd.merge(agg_df, master_df, on='campaign_id', how='left')
                merged_df = pd.merge(merged_df, daily_diff_df, on='campaign_id', how='left')
                
                # --- 理想進捗率(Standard Pacing)の計算 ---
                year = end_date.year
                month = end_date.month
                _, num_days_in_month = calendar.monthrange(year, month)
                days_elapsed = end_date.day
                
                standard_pacing = (days_elapsed / num_days_in_month) * 100
                
                # 実際の進捗率
                merged_df['progress_percent'] = merged_df.apply(
                    lambda x: (x['gross'] / x['monthly_budget'] * 100) if x['monthly_budget'] > 0 else 0, axis=1
                )

                # 進捗率の前日比（昨日の進捗増加分）
                merged_df['daily_progress_diff'] = merged_df.apply(
                    lambda x: (x['latest_gross'] / x['monthly_budget'] * 100) if x['monthly_budget'] > 0 else 0, axis=1
                )
                
                # 乖離(Diff)
                merged_df['diff_point'] = merged_df['progress_percent'] - standard_pacing

                # --- 表示用データの整形 ---
                display_df = merged_df[[
                    'account_name', 'campaign_name', 
                    'monthly_budget', 
                    'gross', 
                    'progress_percent', 'daily_progress_diff', # 進捗
                    'diff_point',
                    'latest_gross', 'diff_gross',  # 消化金額
                    'impression', 'click',         # ★期間合計IMP/Clickを追加
                    'latest_imp', 'diff_imp',      # IMP前日比
                    'latest_click', 'diff_click'   # Click前日比
                ]].copy()
                
                # カラム名の日本語化
                display_df.columns = [
                    'アカウント名', 'キャンペーン名', 
                    '当月予算', 
                    '期間消化額', 
                    '進捗率(%)', '進捗前日比',
                    '乖離(pt)',
                    '昨日消化', '消化前日比',
                    '期間IMP', '期間Click',  # ★ここに追加
                    '昨日IMP', 'IMP前日比',
                    '昨日Click', 'Click前日比'
                ]

                # --- フィルタ機能 ---
                st.markdown("### 🔍 フィルタリング")
                all_campaign_names = display_df['キャンペーン名'].unique()
                selected_campaigns = st.multiselect(
                    "キャンペーン名で絞り込み",
                    options=all_campaign_names
                )
                if selected_campaigns:
                    display_df = display_df[display_df['キャンペーン名'].isin(selected_campaigns)]

                # --- 全体サマリ (2段構成) ---
                st.markdown("---")
                
                # 上段：金額・進捗系
                st.markdown("##### 💰 予算・消化状況")
                row1_col1, row1_col2, row1_col3, row1_col4 = st.columns(4)
                
                row1_col1.metric("当月の理想進捗率", f"{standard_pacing:.1f}%", f"{end_date.month}/{end_date.day} 時点")
                row1_col2.metric("合計消化額 (Gross)", f"¥{display_df['期間消化額'].sum():,.0f}")
                
                total_latest_gross = display_df['昨日消化'].sum()
                total_diff_gross = display_df['消化前日比'].sum()
                row1_col3.metric("昨日の合計消化額", f"¥{total_latest_gross:,.0f}", f"{total_diff_gross:+,.0f} 円")
                
                avg_progress = display_df[display_df['当月予算'] > 0]['進捗率(%)'].mean()
                row1_col4.metric("平均実績進捗率", f"{avg_progress:.1f}%", delta=f"{avg_progress - standard_pacing:.1f} pt")

                # 下段：IMP・Click系（ここに追加）
                st.markdown("##### 👁️ インプレッション・クリック状況")
                row2_col1, row2_col2, row2_col3, row2_col4 = st.columns(4)

                total_imp = display_df['期間IMP'].sum()
                row2_col1.metric("今月の合計IMP", f"{total_imp:,.0f}")

                total_click = display_df['期間Click'].sum()
                row2_col2.metric("今月の合計Click", f"{total_click:,.0f}")

                total_latest_imp = display_df['昨日IMP'].sum()
                total_diff_imp = display_df['IMP前日比'].sum()
                row2_col3.metric("昨日のIMP", f"{total_latest_imp:,.0f}", f"{total_diff_imp:+,.0f}")

                total_latest_click = display_df['昨日Click'].sum()
                total_diff_click = display_df['Click前日比'].sum()
                row2_col4.metric("昨日のClick", f"{total_latest_click:,.0f}", f"{total_diff_click:+,.0f}")

                # --- 詳細テーブル ---
                st.markdown("---")
                st.markdown("### 📋 キャンペーン別詳細")
                st.caption("乖離： 🟦ハイペース(>+10) | ⬛順調 | 🟨警戒 | 🟥危険(<-10)")
                st.caption("前日比： 🟦プラス(増加) | 🟥マイナス(減少)")
                
                # スタイルの適用
                styled_df = display_df.style.format({
                    '当月予算': '¥{:,.0f}',
                    '期間消化額': '¥{:,.0f}',
                    '進捗率(%)': '{:.1f}%',
                    '進捗前日比': '{:+.1f}pt',
                    '乖離(pt)': '{:+.1f}',
                    '昨日消化': '¥{:,.0f}',
                    '消化前日比': '{:+,.0f}',
                    '期間IMP': '{:,.0f}',   # 追加
                    '期間Click': '{:,.0f}', # 追加
                    '昨日IMP': '{:,.0f}',
                    'IMP前日比': '{:+,.0f}',
                    '昨日Click': '{:,.0f}',
                    'Click前日比': '{:+,.0f}'
                }).map(color_diff_pacing, subset=['乖離(pt)'])\
                  .map(color_day_diff, subset=['消化前日比', 'IMP前日比', 'Click前日比'])

                st.dataframe(
                    styled_df,
                    use_container_width=True,
                    height=600
                )