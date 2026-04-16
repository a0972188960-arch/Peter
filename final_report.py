import datetime
import requests
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount

# ========================= 1. 專案核心設定區 =========================
# LINE 設定
LINE_ACCESS_TOKEN = "CIM3KD9Wkl13WlWCbEkYe+Z6Z1+aJxHLz5JgR8Orfs3biF287HAlamKYZT0zyVWWPvJx3k/176/T2b7mdVxn9EX+aEDYsSL6oV305ZUrKNB6EtoUBrA92v5AKDyqC9+5r9jX5gWk2BlPnwHouzK2CwdB04t89/1O/w1cDnyilFU="
GROUP_ID = "Cafceaafbed8c94dbe31840a9dcb80840"

# Meta 設定
META_TOKEN = "EAANmE0npM14BRBDJU6ZBlndYi6bXZBqRISTelEcPADCaHU6hLdTO7uqdeWxTxYZAje5UWOYSboZCnly6hMDcdBQga3MaaZCZBZA6uvUVgo2H3f1Mr9usEfxZBQCCzh2gaO5waZBhKaOY7ySzislflKiGGi5Pbc0RGFhaCPjqTx7ocjZCDhxIk5HaOMg2lZBakZCtDWfh0DPW"

# 廣告帳號 ID 清單
AD_ACCOUNT_IDS = [
    "act_911086531288099",
    "act_2034121714024854",
    "act_1101617182125267",
    "act_2098863870567244",
    "act_1121642359439067",
    "act_999450340629571",
    "act_1214706415596456"
]
# =====================================================================

def get_realtime_exchange_rate():
    """自動抓取最新美金對台幣匯率"""
    try:
        # 使用免 Key 的匯率 API
        url = "https://open.er-api.com/v6/latest/USD"
        res = requests.get(url, timeout=10)
        data = res.json()
        rate = data['rates']['TWD']
        print(f"💱 取得今日動態匯率：1 USD = {rate} TWD")
        return rate
    except Exception as e:
        print(f"⚠️ 匯率抓取失敗，使用保底匯率 32.5。錯誤: {e}")
        return 32.5

def send_final_report(msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN.strip()}"}
    payload = {"to": GROUP_ID, "messages": [{"type": "text", "text": msg}]}
    res = requests.post(url, headers=headers, json=payload)
    return res.status_code

def main():
    try:
        # 0. 抓取動態匯率
        usd_to_twd = get_realtime_exchange_rate()
        
        FacebookAdsApi.init(access_token=META_TOKEN)
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        
        total_spend_twd = 0.0
        total_revenue_twd = 0.0
        processed_count = 0
        
        print(f"🔄 開始整合 {len(AD_ACCOUNT_IDS)} 個帳號數據...")

        for acc_id in AD_ACCOUNT_IDS:
            try:
                account = AdAccount(acc_id)
                fields = ['spend', 'account_currency', 'action_values']
                params = {'time_range': {'since': yesterday, 'until': yesterday}, 'level': 'account'}
                insights = account.get_insights(fields=fields, params=params)

                if insights:
                    data = insights[0]
                    spend = float(data['spend'])
                    currency = data['account_currency']
                    
                    revenue = 0.0
                    if 'action_values' in data:
                        for action in data['action_values']:
                            if 'purchase' in action['action_type'].lower():
                                revenue = float(action['value'])
                                break

                    # 使用動態匯率轉換
                    if currency == 'USD':
                        spend *= usd_to_twd
                        revenue *= usd_to_twd
                    
                    total_spend_twd += spend
                    total_revenue_twd += revenue
                    processed_count += 1
                else:
                    print(f"⚠️ {acc_id} 昨日無數據")
            except Exception as acc_e:
                print(f"❌ {acc_id} 出錯: {acc_e}")

        final_roas = (total_revenue_twd / total_spend_twd) if total_spend_twd > 0 else 0

        report_content = (
            f"🚀 【迪品大爆賣】自動化戰報 3.0\n"
            f"━━━━━━━━━━━━\n"
            f"📅 統計日期：{yesterday}\n"
            f"🏦 成功整合：{processed_count} 個帳號\n"
            f"💱 今日匯率：1:{usd_to_twd:.2f}\n"
            f"💰 總花費 (TWD)：${total_spend_twd:,.0f}\n"
            f"📈 總 ROAS 表現：{final_roas:.2f}\n"
            f"━━━━━━━━━━━━\n"
            f"🦾 數據已根據每日匯率自動校準"
        )
        
        if send_final_report(report_content) == 200:
            print(f"🎉 報表發送成功！")

    except Exception as e:
        print(f"❌ 系統出錯：{e}")

if __name__ == "__main__":
    main()