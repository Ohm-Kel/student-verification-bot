import time
import sqlite3
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

# --- Configuration ---
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'students.db')
GROUP_NAME = "Computer Engineering Freshmen 2026" # EXACT Name of the group
CHECK_INTERVAL = 60 # Check every 60 seconds

def get_whitelist():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT phone_number FROM whitelist")
    numbers = [row[0] for row in cursor.fetchall()]
    conn.close()
    # Normalize numbers (remove spaces, etc if needed)
    return [n.replace(" ", "").replace("+", "") for n in numbers] # Simple normalization

def run_bot():
    print("[*] Starting WhatsApp Bot...")
    print("[*] Please scan the QR code to login.")

    chrome_options = Options()
    # chrome_options.add_argument("--headless=new") # CANNOT be headless for WhatsApp Web usually (need QR scan)
    # Use existing profile if possible to avoid re-scan, but for now simple start
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--start-maximized")

    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        driver.get("https://web.whatsapp.com")
        
        # Wait for user to scan QR and load (look for side pane)
        wait = WebDriverWait(driver, 120)
        print("[*] Waiting for Login...")
        wait.until(EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true"][@data-tab="3"]')))
        print("[*] Logged in!")

        while True:
            try:
                # 1. Search for the Group
                search_box = driver.find_element(By.XPATH, '//div[@contenteditable="true"][@data-tab="3"]')
                search_box.clear()
                search_box.send_keys(GROUP_NAME)
                time.sleep(2)
                
                # 2. Click the group (first result)
                # XPath to find a chat title matching GROUP_NAME
                group_xpath = f'//span[@title="{GROUP_NAME}"]'
                group_element = driver.find_element(By.XPATH, group_xpath)
                group_element.click()
                print(f"[*] Opened Group: {GROUP_NAME}")
                time.sleep(2)

                # 3. Check for "Pending Requests" banner or info
                # This depends on WhatsApp Web UI updates. 
                # Usually need to click Group Info -> Pending Participants.
                
                # Click Header to open Group Info
                header = driver.find_element(By.CSS_SELECTOR, 'header')
                header.click()
                time.sleep(2)
                
                # Locate "Pending Participants" in the side drawer
                # Text content "Pending participants"
                try:
                    pending_btn = driver.find_element(By.XPATH, '//div[contains(text(), "Pending participants")]')
                    pending_btn.click()
                    time.sleep(2)
                    
                    # 4. Scan List
                    # Logic: Find all pending users. Get their phone number (title or text).
                    # Check whitelist. If match, click approve (tick/check button).
                    
                    # Placeholder loop for requests
                    # requests = driver.find_elements(By.CSS_SELECTOR, '.pending-request-item') 
                    # For now, just print "Monitoring" as I can't simulate this easily without real WhatsApp.
                    print("[?] Checking for pending requests...")
                    
                    whitelist = get_whitelist()
                    print(f"    dWhitelist: {whitelist}")
                    
                    # Verification Logic would go here
                    # For each request:
                    #   phone = extract_phone(request_element)
                    #   if phone in whitelist:
                    #       click_approve(request_element)
                    #   else:
                    #       print(f"Ignoring {phone}")
                    
                    # Go back to chat
                    # close_btn = driver.find_element(By.CSS_SELECTOR, 'div[data-icon="x"]')
                    # close_btn.click()
                    
                except Exception as e:
                    print("    -> No pending participants found or UI changed.")
                
            except Exception as outer_e:
                print(f"[!] Loop Error: {outer_e}")
            
            print(f"[*] Sleeping for {CHECK_INTERVAL}s...")
            time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"[!] Critical Bot Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_bot()
