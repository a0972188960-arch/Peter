import time
import os
import glob
import random
import pandas as pd
import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

# ================= 設定區 (由 GitHub Secrets 讀取) =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(BASE_DIR, 'gcp-key.json')
SHEET_NAME = '迪品欠貨通知追蹤表' 

# 從環境變數讀取敏感資訊 (優先讀取 GitHub Secrets，保護帳密不外流)
USALE_USER = os.getenv("USALE_USER", "peter")
USALE_PW = os.getenv("USALE_PW", "Jd86P9Pff")
ONESHOP_USER = os.getenv("ONESHOP_USER", "0905035715")
ONESHOP_PW = os.getenv("ONESHOP_PW", "peter53606")
LINE_ACCESS_TOKEN = "CIM3KD9Wkl13WlWCbEkYe+Z6Z1+aJxHLz5JgR8Orfs3biF287HAlamKYZT0zyVWWPvJx3k/176/T2b7mdVxn9EX+aEDYsSL6oV305ZUrKNB6EtoUBrA92v5AKDyqC9+5r9jX5gWk2BlPnwHouzK2CwdB04t89/1O/w1cDnyilFU="
GROUP_ID = "Cafceaafbed8c94dbe31840a9dcb80840"

USALE_LOGIN_URL = "https://ec.mallbic.com/Module/0_Login/Login.aspx?sid=wc1vp80o"
USALE_ORDER_PAGE = "https://ec.mallbic.com/Module/1_Main/Main.aspx#frame=mode_order"
ONESHOP_LOGIN_URL = "https://admin.1shop.tw/login"

SHOPS_TO_PROCESS = ["SHANER山人", "ColorFan", "宅人"]

SHOP_MESSAGES = {
    "SHANER山人": {
        "email_subject": "【SHANER山人】缺貨/超賣通知",
        "email_body": "您訂購的SHANER山人商品有缺貨問題，目前您的訂單無法出貨請盡速聯繫客服https://lin.ee/Zj9MAMQ",
        "sms_body": "【SHANER】您好，您訂購的SHANER山人商品有缺貨問題，目前您的訂單無法出貨請盡速聯繫客服https://lin.ee/Zj9MAMQ"
    },
    "ColorFan": {
        "email_subject": "【ColorFan】缺貨/超賣通知",
        "email_body": "您訂購的ColorFan卡樂芬商品有缺貨問題，目前您的訂單無法出貨請盡速聯繫客服https://lin.ee/oIy0cF8",
        "sms_body": "【ColorFan】您訂購的ColorFan卡樂芬商品有缺貨問題，目前您的訂單無法出貨請盡速聯繫客服https://lin.ee/oIy0cF8"
    },
    "宅人": {
        "email_subject": "【宅人】缺貨/超賣通知",
        "email_body": "您訂購的Homebody宅人商品有缺貨問題，目前您的訂單無法出貨請盡速聯繫客服https://lin.ee/qeSkFnL",
        "sms_body": "【宅人】您好，您訂購的Homebody宅人商品有缺貨問題，目前您的訂單無法出貨請盡速聯繫客服https://lin.ee/qeSkFnL"
    }
}

# GitHub Actions 環境路徑通常在 /home/runner/
DOWNLOAD_PATH = os.path.join(os.path.expanduser("~"), "Downloads")
# =====================================================

def send_line_report(message):
    """LINE Notify 通報函數"""
    if not LINE_TOKEN:
        print("⚠️ 未偵測到 LINE_TOKEN，跳過通報。")
        return
    try:
        url = "https://notify-api.line.me/api/notify"
        headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
        data = {"message": f"\n{message}"}
        requests.post(url, headers=headers, data=data)
    except Exception as e:
        print(f"LINE 通報失敗: {e}")

def sync_to_cloud_after_notice(order_list):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1
        all_data = sheet.get_all_values()
        existing_orders = {str(row[0]).strip(): idx + 1 for idx, row in enumerate(all_data) if idx > 0}

        print(f"📊 [雲端同步] 開始處理 {len(order_list)} 筆...")
        for i, oid in enumerate(order_list):
            # 針對 429 錯誤增加延遲
            if i > 0 and i % 2 == 0: time.sleep(3) 
            
            if oid in existing_orders:
                row_idx = existing_orders[oid]
                current_val = sheet.cell(row_idx, 2).value
                current_count = int(current_val) if str(current_val).isdigit() else 0
                new_count = current_count + 1
                new_status = "待取消" if new_count >= 3 else "需通知"
                sheet.update_cell(row_idx, 2, new_count)
                sheet.update_cell(row_idx, 3, new_status)
            else:
                sheet.append_row([oid, 1, "需通知"])
        return True
    except Exception as e:
        print(f"❌ 雲端寫入失敗: {e}")
        return False

def slow_type(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))

def force_js_click_by_text(driver, text):
    script = f'var elements = document.querySelectorAll("li, div, span, button, a, .shop-name"); for (var i = 0; i < elements.length; i++) {{ if (elements[i].innerText.trim().includes("{text}")) {{ elements[i].scrollIntoView({{block: "center"}}); elements[i].click(); return "✅ OK"; }} }} return "❌ Fail";'
    return driver.execute_script(script)

def force_js_click_v_popper_confirm(driver):
    script = 'var popperBtn = document.querySelector(".v-popper button.btn-primary.ms-1"); if (popperBtn && popperBtn.innerText.includes("確認")) { popperBtn.click(); return "✅ OK"; } return "❌ Fail";'
    return driver.execute_script(script)

def process_notifications(driver, wait, shop_name, search_numbers):
    try:
        msg_config = SHOP_MESSAGES.get(shop_name, SHOP_MESSAGES["SHANER山人"])
        driver.get(f"https://admin.1shop.tw/shop/order/all?order_number={search_numbers}")
        time.sleep(8)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "label[for='checkbox-all']"))).click()
        time.sleep(1)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '更多批次功能')]"))).click()
        time.sleep(2)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '寄送Email')]"))).click()
        time.sleep(8) 
        wait.until(EC.visibility_of_element_located((By.ID, "subject"))).send_keys(msg_config["email_subject"])
        body_email = driver.find_element(By.ID, "body")
        body_email.click()
        body_email.send_keys(Keys.END + Keys.ENTER)
        slow_type(body_email, msg_config["email_body"])
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-primary.ms-1"))).click()
        time.sleep(4)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-default.ms-1"))).click()
        time.sleep(3)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '更多批次功能')]"))).click()
        time.sleep(2)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '寄送簡訊')]"))).click()
        time.sleep(8)
        sms_body = wait.until(EC.visibility_of_element_located((By.ID, "body")))
        sms_body.click()
        sms_text = msg_config["sms_body"]
        driver.execute_script(f"arguments[0].value = '{sms_text}';", sms_body)
        sms_body.send_keys(Keys.SPACE)
        time.sleep(2)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-primary.ms-1"))).click()
        time.sleep(4)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-default.ms-1"))).click()
        return True
    except Exception as e:
        print(f"⚠️ {shop_name} 通知異常: {e}")
        return False

def switch_to_next_shop(driver, wait, target_name):
    try:
        top_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.header-icon.link-style.shop-name")))
        top_btn.click()
        time.sleep(2) 
        force_js_click_v_popper_confirm(driver)
        wait.until(EC.url_contains("switch"))
        time.sleep(2)
        wait.until(EC.element_to_be_clickable((By.XPATH, f"//div[@class='shop-name'][text()='{target_name}']"))).click()
        time.sleep(6)
        return True
    except: return False

def run_full_automation():
    options = webdriver.ChromeOptions()
    # --- GitHub 執行必備設定 ---
    options.add_argument("--headless")           
    options.add_argument("--no-sandbox")          
    options.add_argument("--disable-dev-shm-usage") 
    options.add_argument("--disable-gpu")         
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    # 讓 GitHub 也能下載檔案
    prefs = {"download.default_directory": DOWNLOAD_PATH}
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 30)
    
    try:
        print("1️⃣ [uSale] 開始匯出...")
        driver.get(USALE_LOGIN_URL)
        wait.until(EC.presence_of_element_located((By.ID, "user_name"))).send_keys(USALE_USER)
        driver.find_element(By.ID, "user_pswd").send_keys(USALE_PW)
        driver.find_element(By.NAME, "submit").click()
        time.sleep(3); driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
        
        driver.get(USALE_ORDER_PAGE)
        time.sleep(12); driver.switch_to.default_content()
        try: wait.until(EC.frame_to_be_available_and_switch_to_it(0))
        except: pass
        wait.until(EC.element_to_be_clickable((By.ID, "tpage8"))).click()
        time.sleep(5); force_js_click_by_text(driver, "客服_通知缺換貨")
        time.sleep(10); force_js_click_by_text(driver, "匯出訂單")
        time.sleep(5); force_js_click_by_text(driver, "1shop要出貨訂單編號")
        time.sleep(15)

        print("2️⃣ [Data] 處理 CSV...")
        if not os.path.exists(DOWNLOAD_PATH): os.makedirs(DOWNLOAD_PATH)
        all_files = glob.glob(os.path.join(DOWNLOAD_PATH, "*.csv"))
        valid_files = [f for f in all_files if not os.path.basename(f).startswith("~$") and "_已處理" not in f]
        if not valid_files: raise Exception("找不到匯出的 CSV 檔案")
        
        latest_file = max(valid_files, key=os.path.getmtime)
        try: df = pd.read_csv(latest_file, encoding='utf-8-sig')
        except: df = pd.read_csv(latest_file, encoding='big5')
        order_list = df[df.columns[0]].astype(str).str.strip().tolist()
        search_numbers = "%2C".join(order_list)

        print("3️⃣ [1Shop] 登入中...")
        driver.get(ONESHOP_LOGIN_URL)
        slow_type(wait.until(EC.presence_of_element_located((By.ID, "user_mobile"))), ONESHOP_USER)
        slow_type(driver.find_element(By.ID, "user_password"), ONESHOP_PW)
        driver.find_element(By.CSS_SELECTOR, "button.btn-primary.btn-cons").click()
        
        wait.until(EC.presence_of_element_located((By.XPATH, f"//div[@class='shop-name'][text()='{SHOPS_TO_PROCESS[0]}']")))
        wait.until(EC.element_to_be_clickable((By.XPATH, f"//div[@class='shop-name'][text()='{SHOPS_TO_PROCESS[0]}']"))).click()
        time.sleep(5)

        all_shops_success = True
        for i, shop in enumerate(SHOPS_TO_PROCESS):
            if not process_notifications(driver, wait, shop, search_numbers):
                all_shops_success = False; break
            if i < len(SHOPS_TO_PROCESS) - 1:
                if not switch_to_next_shop(driver, wait, SHOPS_TO_PROCESS[i+1]):
                    all_shops_success = False; break
        
        if all_shops_success:
            sync_to_cloud_after_notice(order_list)
            send_line_report(f"🚀 [Step 1] 執行成功\n店鋪: {', '.join(SHOPS_TO_PROCESS)}\n訂單數: {len(order_list)}\n雲端紀錄已更新。")
        else:
            raise Exception("部分店鋪通知發送失敗")

        driver.quit()
        return True

    except Exception as e:
        send_line_report(f"❌ [Step 1] 發生錯誤\n原因: {str(e)}")
        driver.quit()
        raise e 

def run_step1():
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if run_full_automation(): return True
        except Exception as e:
            if attempt == max_retries - 1: return False
            time.sleep(10)
    return False

if __name__ == "__main__":
    run_step1()
