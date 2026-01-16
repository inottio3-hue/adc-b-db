import streamlit as st
import pandas as pd
import requests
import datetime

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
        "report_type": "campaign"  # キャンペーン単位で取得
    }
    
    try:
        # 仕様通りの特殊なGETリクエスト
        response = requests.request("GET", url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        return None

# --- メイン処理 ---
if st.sidebar.button("データ取得"):
    if not api_key:
        st.warning("API Keyを入力してください。")
    else:
        with st.spinner("データを取得中..."):
            data = get_microad_data(api_key, start_date, end_date)
            
        if data:
            # 1. マスタデータの作成（キャンペーン情報）
            campaigns = []
            # アカウントが複数ある場合に対応してループ
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
                
                # 数値型に変換
                numeric_cols = ['net', 'gross', 'impression', 'click']
                for col in numeric_cols:
                    if col in perf_df.columns:
                        perf_df[col] = pd.to_numeric(perf_df[col], errors='coerce').fillna(0)

                # キャンペーンIDで集計（日別データを期間合計に）
                agg_df = perf_df.groupby('campaign_id')[numeric_cols].sum().reset_index()
                
                # 3. マスタと実績を結合
                merged_df = pd.merge(agg_df, master_df, on='campaign_id', how='left')
                
                # 予算進捗率の計算
                merged_df['progress_percent'] = merged_df.apply(
                    lambda x: (x['gross'] / x['monthly_budget'] * 100) if x['monthly_budget'] > 0 else 0, axis=1
                )
                
                # 表示用にカラムを整理
                display_df = merged_df[[
                    'account_name', 'campaign_name', 
                    'monthly_budget', 'gross', 'progress_percent', 
                    'impression', 'click'
                ]].copy()
                
                # カラム名の日本語化
                display_df.columns = [
                    'アカウント名', 'キャンペーン名', 
                    '当月予算', '消化額(Gross)', '進捗率(%)', 
                    'IMP', 'Click'
                ]

                # --- フィルタ機能（ここを追加しました） ---
                st.markdown("### 🔍 フィルタリング")
                
                # キャンペーン名リストを作成
                all_campaign_names = display_df['キャンペーン名'].unique()
                
                # マルチセレクトボックス（Excelのフィルタのように複数選択可能）
                selected_campaigns = st.multiselect(
                    "キャンペーン名で絞り込み（選択しない場合は全表示）",
                    options=all_campaign_names
                )
                
                # 選択されていたらデータを絞り込む
                if selected_campaigns:
                    display_df = display_df[display_df['キャンペーン名'].isin(selected_campaigns)]

                # --- 全体サマリ表示 ---
                st.markdown("---")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("合計消化額 (Gross)", f"¥{display_df['消化額(Gross)'].sum():,.0f}")
                col2.metric("合計インプレッション", f"{display_df['IMP'].sum():,.0f}")
                col3.metric("合計クリック", f"{display_df['Click'].sum():,.0f}")
                
                avg_progress = display_df[display_df['当月予算'] > 0]['進捗率(%)'].mean()
                col4.metric("平均予算進捗率", f"{avg_progress:.1f}%")

                # --- 詳細テーブル（ソート機能付き） ---
                st.markdown("### 📋 キャンペーン別詳細")
                st.info("💡 表の「項目名」をクリックすると、昇順・降順に並び替えできます。")
                
                # データフレームの表示設定
                st.dataframe(
                    display_df.style.format({
                        '当月予算': '¥{:,.0f}',
                        '消化額(Gross)': '¥{:,.0f}',
                        '進捗率(%)': '{:.1f}%',
                        'IMP': '{:,.0f}',
                        'Click': '{:,.0f}'
                    }).background_gradient(subset=['進捗率(%)'], cmap="Reds", vmin=0, vmax=120),
                    use_container_width=True,
                    height=500
                )