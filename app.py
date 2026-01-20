import streamlit as st
import pandas as pd
import requests
import datetime
import calendar
import plotly.graph_objects as go # グラフ描画用ライブラリ
from plotly.subplots import make_subplots

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

# --- 色分けロジック ---
def color_diff_pacing(val):
    if val > 10: return 'color: blue; font-weight: bold;'
    elif 0 <= val <= 10: return 'color: black;'
    elif -10 <= val < 0: return 'color: #D4AC0D; font-weight: bold;'
    else: return 'color: red; font-weight: bold;'

def color_day_diff(val):
    if val > 0: return 'color: blue; font-weight: bold;'
    elif val < 0: return 'color: red; font-weight: bold;'
    else: return 'color: black;'

# --- メイン処理 ---
if st.sidebar.button("データ取得"):
    if not api_key:
        st.warning("API Keyを入力してください。")
    else:
        with st.spinner("データを取得中..."):
            data = get_microad_data(api_key, start_date, end_date)
            
        if data:
            # 1. マスタ作成
            campaigns = []
            if 'account' in data:
                for acc in data['account']:
                    acc_name = acc.get('name', 'Unknown')
                    if 'campaign' in acc:
                        for camp in acc['campaign']:
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

            # 2. 実績データ作成
            records = []
            if 'report' in data and 'records' in data['report']:
                records = data['report']['records']
            
            if not records:
                st.warning("指定期間の配信実績データがありません。")
            else:
                perf_df = pd.DataFrame(records)
                numeric_cols = ['net', 'gross', 'impression', 'click']
                for col in numeric_cols:
                    if col in perf_df.columns:
                        perf_df[col] = pd.to_numeric(perf_df[col], errors='coerce').fillna(0)
                
                if 'target_date' in perf_df.columns:
                    perf_df['target_date'] = pd.to_datetime(perf_df['target_date'].astype(str))
                
                # 集計処理
                agg_df = perf_df.groupby('campaign_id')[numeric_cols].sum().reset_index()
                
                # 前日比計算
                if 'target_date' in perf_df.columns and not perf_df.empty:
                    latest_date = perf_df['target_date'].max()
                    prev_date = latest_date - datetime.timedelta(days=1)
                    
                    target_cols = ['gross', 'impression', 'click']
                    latest_df = perf_df[perf_df['target_date'] == latest_date].groupby('campaign_id')[target_cols].sum().reset_index()
                    prev_df = perf_df[perf_df['target_date'] == prev_date].groupby('campaign_id')[target_cols].sum().reset_index()
                    
                    # リネーム
                    latest_df = latest_df.rename(columns={'gross':'l_gross', 'impression':'l_imp', 'click':'l_click'})
                    prev_df = prev_df.rename(columns={'gross':'p_gross', 'impression':'p_imp', 'click':'p_click'})
                    
                    daily_diff_df = pd.merge(latest_df, prev_df, on='campaign_id', how='left').fillna(0)
                    daily_diff_df['diff_gross'] = daily_diff_df['l_gross'] - daily_diff_df['p_gross']
                    daily_diff_df['diff_imp'] = daily_diff_df['l_imp'] - daily_diff_df['p_imp']
                    daily_diff_df['diff_click'] = daily_diff_df['l_click'] - daily_diff_df['p_click']
                    
                    # 列名をマージ用に整える
                    daily_diff_df = daily_diff_df[['campaign_id', 'l_gross', 'diff_gross', 'l_imp', 'diff_imp', 'l_click', 'diff_click']]
                    daily_diff_df = daily_diff_df.rename(columns={'l_gross':'latest_gross', 'l_imp':'latest_imp', 'l_click':'latest_click'})
                else:
                    daily_diff_df = pd.DataFrame(columns=['campaign_id', 'latest_gross', 'diff_gross', 'latest_imp', 'diff_imp', 'latest_click', 'diff_click'])

                # 結合
                merged_df = pd.merge(agg_df, master_df, on='campaign_id', how='left')
                merged_df = pd.merge(merged_df, daily_diff_df, on='campaign_id', how='left')
                
                # 進捗計算
                year = end_date.year
                month = end_date.month
                _, num_days_in_month = calendar.monthrange(year, month)
                days_elapsed = end_date.day
                standard_pacing = (days_elapsed / num_days_in_month) * 100
                
                merged_df['progress_percent'] = merged_df.apply(lambda x: (x['gross']/x['monthly_budget']*100) if x['monthly_budget']>0 else 0, axis=1)
                merged_df['daily_progress_diff'] = merged_df.apply(lambda x: (x['latest_gross']/x['monthly_budget']*100) if x['monthly_budget']>0 else 0, axis=1)
                merged_df['diff_point'] = merged_df['progress_percent'] - standard_pacing

                # 表示用DF
                display_df = merged_df[[
                    'account_name', 'campaign_name', 'monthly_budget', 'gross', 
                    'progress_percent', 'daily_progress_diff', 'diff_point',
                    'latest_gross', 'diff_gross', 'impression', 'click',
                    'latest_imp', 'diff_imp', 'latest_click', 'diff_click'
                ]].copy()
                
                display_df.columns = [
                    'アカウント名', 'キャンペーン名', '当月予算', '期間消化額', 
                    '進捗率(%)', '進捗前日比', '乖離(pt)',
                    '昨日消化', '消化前日比', '期間IMP', '期間Click',
                    '昨日IMP', 'IMP前日比', '昨日Click', 'Click前日比'
                ]

                # --- フィルタリング ---
                st.markdown("### 🔍 フィルタリング")
                all_campaign_names = display_df['キャンペーン名'].unique()
                selected_campaigns = st.multiselect("キャンペーン名で絞り込み", options=all_campaign_names)
                if selected_campaigns:
                    display_df = display_df[display_df['キャンペーン名'].isin(selected_campaigns)]

                # --- 全体サマリ ---
                st.markdown("---")
                st.markdown("##### 💰 予算・消化状況")
                r1c1, r1c2, r1c3, r1c4 = st.columns(4)
                r1c1.metric("当月の理想進捗率", f"{standard_pacing:.1f}%", f"{end_date.month}/{end_date.day} 時点")
                r1c2.metric("合計消化額 (Gross)", f"¥{display_df['期間消化額'].sum():,.0f}")
                r1c3.metric("昨日の合計消化額", f"¥{display_df['昨日消化'].sum():,.0f}", f"{display_df['消化前日比'].sum():+,.0f} 円")
                avg_prog = display_df[display_df['当月予算']>0]['進捗率(%)'].mean()
                r1c4.metric("平均実績進捗率", f"{avg_prog:.1f}%", delta=f"{avg_prog - standard_pacing:.1f} pt")

                st.markdown("##### 👁️ インプレッション・クリック状況")
                r2c1, r2c2, r2c3, r2c4 = st.columns(4)
                r2c1.metric("今月の合計IMP", f"{display_df['期間IMP'].sum():,.0f}")
                r2c2.metric("今月の合計Click", f"{display_df['期間Click'].sum():,.0f}")
                r2c3.metric("昨日のIMP", f"{display_df['昨日IMP'].sum():,.0f}", f"{display_df['IMP前日比'].sum():+,.0f}")
                r2c4.metric("昨日のClick", f"{display_df['昨日Click'].sum():,.0f}", f"{display_df['Click前日比'].sum():+,.0f}")

                # --- 詳細テーブル ---
                st.markdown("---")
                st.markdown("### 📋 キャンペーン別詳細")
                st.caption("乖離： 🟦ハイペース(>+10) | ⬛順調 | 🟨警戒 | 🟥危険(<-10)")
                
                styled_df = display_df.style.format({
                    '当月予算': '¥{:,.0f}', '期間消化額': '¥{:,.0f}',
                    '進捗率(%)': '{:.1f}%', '進捗前日比': '{:+.1f}pt', '乖離(pt)': '{:+.1f}',
                    '昨日消化': '¥{:,.0f}', '消化前日比': '{:+,.0f}',
                    '期間IMP': '{:,.0f}', '期間Click': '{:,.0f}',
                    '昨日IMP': '{:,.0f}', 'IMP前日比': '{:+,.0f}',
                    '昨日Click': '{:,.0f}', 'Click前日比': '{:+,.0f}'
                }).map(color_diff_pacing, subset=['乖離(pt)'])\
                  .map(color_day_diff, subset=['消化前日比', 'IMP前日比', 'Click前日比'])

                st.dataframe(styled_df, use_container_width=True, height=500)

                # ========================================================
                # 📈 グラフ描画セクション（ここを追加！）
                # ========================================================
                st.markdown("---")
                st.markdown("### 📈 詳細分析（グラフ）")
                
                # グラフを表示するキャンペーンを選択
                # （デフォルトはリストの最初の1つ）
                graph_options = display_df['キャンペーン名'].unique()
                if len(graph_options) > 0:
                    selected_graph_camp = st.selectbox("グラフを表示するキャンペーンを選択してください", graph_options)
                    
                    # 選択されたキャンペーンのIDを取得
                    target_camp_id = master_df[master_df['campaign_name'] == selected_graph_camp]['campaign_id'].values[0]
                    target_budget = master_df[master_df['campaign_name'] == selected_graph_camp]['monthly_budget'].values[0]
                    
                    # そのキャンペーンの日別データを抽出
                    daily_data = perf_df[perf_df['campaign_id'] == target_camp_id].copy()
                    
                    if not daily_data.empty:
                        # 日付順に並べ替え
                        daily_data = daily_data.sort_values('target_date')
                        
                        # 累積データの計算 (cumsum)
                        daily_data['cum_gross'] = daily_data['gross'].cumsum()
                        daily_data['cum_imp'] = daily_data['impression'].cumsum()
                        daily_data['cum_click'] = daily_data['click'].cumsum()
                        
                        # 進捗率の計算
                        if target_budget > 0:
                            daily_data['actual_progress'] = (daily_data['cum_gross'] / target_budget) * 100
                        else:
                            daily_data['actual_progress'] = 0

                        # 理想進捗ラインの作成
                        # 月初〜月末までの日付リストを作成
                        last_day_of_month = calendar.monthrange(start_date.year, start_date.month)[1]
                        month_dates = [datetime.date(start_date.year, start_date.month, d) for d in range(1, last_day_of_month + 1)]
                        
                        ideal_df = pd.DataFrame({'date': month_dates})
                        ideal_df['date'] = pd.to_datetime(ideal_df['date'])
                        # 理想進捗率（1日ごとに均等に増える）
                        ideal_df['ideal_progress'] = (ideal_df.index + 1) / last_day_of_month * 100

                        # グラフの作成（2段構成）
                        fig = make_subplots(rows=2, cols=1, 
                                            shared_xaxes=True, 
                                            vertical_spacing=0.1,
                                            subplot_titles=("進捗率の推移 (実績 vs 理想)", "インプレッション・クリックの累積推移"),
                                            specs=[[{"secondary_y": False}], [{"secondary_y": True}]])

                        # --- 上段：進捗率グラフ ---
                        # 理想ライン（青点線）
                        fig.add_trace(go.Scatter(
                            x=ideal_df['date'], y=ideal_df['ideal_progress'],
                            mode='lines', name='理想進捗率',
                            line=dict(color='blue', dash='dot', width=1)
                        ), row=1, col=1)
                        
                        # 実績ライン（赤実線）
                        fig.add_trace(go.Scatter(
                            x=daily_data['target_date'], y=daily_data['actual_progress'],
                            mode='lines+markers', name='実績進捗率',
                            line=dict(color='red', width=3)
                        ), row=1, col=1)

                        # --- 下段：IMP・Clickグラフ ---
                        # インプレッション（棒グラフ or 面グラフ）
                        fig.add_trace(go.Bar(
                            x=daily_data['target_date'], y=daily_data['cum_imp'],
                            name='累積IMP', opacity=0.3, marker_color='gray'
                        ), row=2, col=1, secondary_y=False)

                        # クリック（折れ線グラフ）
                        fig.add_trace(go.Scatter(
                            x=daily_data['target_date'], y=daily_data['cum_click'],
                            name='累積Click', mode='lines+markers',
                            line=dict(color='orange', width=2)
                        ), row=2, col=1, secondary_y=True)

                        # レイアウト調整
                        fig.update_layout(height=700, showlegend=True, hovermode="x unified")
                        fig.update_yaxes(title_text="進捗率 (%)", range=[0, 110], row=1, col=1)
                        fig.update_yaxes(title_text="累積IMP", row=2, col=1, secondary_y=False)
                        fig.update_yaxes(title_text="累積Click", row=2, col=1, secondary_y=True)

                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("このキャンペーンの日別データがありません。")