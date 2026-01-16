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
    
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    # 日付をYYYYMMDD形式に変換
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
    """
    乖離ポイントに応じた文字色を返す関数
    青: +10pt超
    黒: 0 ～ +10pt
    黄: -10 ～ 0pt
    赤: -10pt未満（危険）
    """
    if val > 10:
        return 'color: blue; font-weight: bold;'
    elif 0 <= val <= 10:
        return 'color: black;'
    elif -10 <= val < 0:
        return 'color: #D4AC0D; font-weight: bold;' # 読みやすい濃い黄色
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

                # キャンペーンIDで集計
                agg_df = perf_df.groupby('campaign_id')[numeric_cols].sum().reset_index()
                
                # 3. マスタと実績を結合
                merged_df = pd.merge(agg_df, master_df, on='campaign_id', how='left')
                
                # --- 理想進捗率(Standard Pacing)の計算 ---
                # 終了日の月の日数を取得
                year = end_date.year
                month = end_date.month
                _, num_days_in_month = calendar.monthrange(year, month)
                days_elapsed = end_date.day
                
                # 理想進捗率 = (経過日数 / 月の全日数) * 100
                standard_pacing = (days_elapsed / num_days_in_month) * 100
                
                # 実際の進捗率
                merged_df['progress_percent'] = merged_df.apply(
                    lambda x: (x['gross'] / x['monthly_budget'] * 100) if x['monthly_budget'] > 0 else 0, axis=1
                )
                
                # 乖離(Diff) = 実績 - 理想
                merged_df['diff_point'] = merged_df['progress_percent'] - standard_pacing

                # 表示用データの整形
                display_df = merged_df[[
                    'account_name', 'campaign_name', 
                    'monthly_budget', 'gross', 'progress_percent', 'diff_point',
                    'impression', 'click'
                ]].copy()
                
                display_df.columns = [
                    'アカウント名', 'キャンペーン名', 
                    '当月予算', '消化額(Gross)', '進捗率(%)', '乖離(pt)',
                    'IMP', 'Click'
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

                # --- 全体サマリ ---
                st.markdown("---")
                col1, col2, col3, col4 = st.columns(4)
                
                # 全体サマリに「理想進捗率」を表示
                col1.metric("当月の理想進捗率", f"{standard_pacing:.1f}%", f"現在: {end_date.month}月{end_date.day}日時点")
                col2.metric("合計消化額 (Gross)", f"¥{display_df['消化額(Gross)'].sum():,.0f}")
                col3.metric("合計インプレッション", f"{display_df['IMP'].sum():,.0f}")
                
                avg_progress = display_df[display_df['当月予算'] > 0]['進捗率(%)'].mean()
                col4.metric("平均実績進捗率", f"{avg_progress:.1f}%", delta=f"{avg_progress - standard_pacing:.1f} pt")

                # --- 詳細テーブル ---
                st.markdown("### 📋 キャンペーン別詳細（色分け表示）")
                st.caption(f"色の意味： 🟦ハイペース(>+10) | ⬛順調(0~+10) | 🟨警戒(-10~0) | 🟥危険(<-10)")
                
                # スタイルの適用
                styled_df = display_df.style.format({
                    '当月予算': '¥{:,.0f}',
                    '消化額(Gross)': '¥{:,.0f}',
                    '進捗率(%)': '{:.1f}%',
                    '乖離(pt)': '{:+.1f}', # プラスマイナスを表示
                    'IMP': '{:,.0f}',
                    'Click': '{:,.0f}'
                }).map(color_diff, subset=['乖離(pt)']) # 乖離列に色を適用

                st.dataframe(
                    styled_df,
                    use_container_width=True,
                    height=600
                )