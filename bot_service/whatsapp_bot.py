"""
WhatsApp Bot for Auto-Approving Verified Students
==================================================
This bot monitors TWO WhatsApp groups (Official & Unofficial) for pending
join requests and automatically approves students whose phone numbers
are in the verification whitelist.

IMPORTANT: This bot uses Selenium to control WhatsApp Web.
You must keep the browser window open and logged in.
"""

import time
import sqlite3
import os
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

# --- Configuration ---
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'students.db')

# UPDATE THESE WITH YOUR ACTUAL GROUP NAMES
GROUPS = [
    "COE 1 {Official}",      # Official Group Name
    "COE 1 {Unofficial}"     # Unofficial Group Name
]

CHECK_INTERVAL = 60  # Seconds between checks
MAX_APPROVALS_PER_CYCLE = 10  # Safety limit

# --- Database Functions ---
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_whitelist():
    """Fetch all whitelisted phone numbers and normalize them."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phone_number, app_id FROM whitelist")
    rows = cursor.fetchall()
    conn.close()
    
    whitelist = {}
    for row in rows:
        normalized = normalize_phone(row['phone_number'])
        whitelist[normalized] = row['app_id']
    return whitelist

def normalize_phone(phone):
    """
    Normalize phone number to a consistent format.
    Handles: +233XXXXXXXXX, 0XXXXXXXXX, 233XXXXXXXXX
    Returns: 233XXXXXXXXX (no plus, no leading zero)
    """
    if not phone:
        return ""
    
    # Remove all non-digits
    digits = re.sub(r'\D', '', phone)
    
    # Handle Ghana format
    if digits.startswith('0') and len(digits) == 10:
        digits = '233' + digits[1:]
    elif digits.startswith('233') and len(digits) == 12:
        pass  # Already correct
    elif len(digits) == 9:
        digits = '233' + digits
    
    return digits

def is_already_approved(phone, group_name):
    """Check if this phone was already approved for this group (idempotency)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create tracking table if not exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS approvals_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT,
            group_name TEXT,
            approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(phone_number, group_name)
        )
    ''')
    conn.commit()
    
    cursor.execute(
        'SELECT 1 FROM approvals_log WHERE phone_number = ? AND group_name = ?',
        (phone, group_name)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None

def log_approval(phone, group_name):
    """Log that we approved this phone for this group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT OR IGNORE INTO approvals_log (phone_number, group_name) VALUES (?, ?)',
            (phone, group_name)
        )
        conn.commit()
    except Exception as e:
        print(f"[!] Error logging approval: {e}")
    finally:
        conn.close()

# --- WhatsApp Web Interaction ---
def extract_phone_from_element(element):
    """
    Extract phone number from a pending request element.
    WhatsApp typically shows the phone number in the title or text.
    """
    try:
        # Try to get phone from title attribute
        title = element.get_attribute('title')
        if title:
            return normalize_phone(title)
        
        # Try to get from text content
        text = element.text
        # Look for phone pattern
        phone_match = re.search(r'[\+]?[\d\s\-]{9,15}', text)
        if phone_match:
            return normalize_phone(phone_match.group())
    except Exception:
        pass
    return ""

def process_group(driver, wait, group_name, whitelist):
    """Process pending requests for a single group."""
    approvals = 0
    
    try:
        # 1. Search for the group
        search_box = wait.until(EC.presence_of_element_located(
            (By.XPATH, '//div[@contenteditable="true"][@data-tab="3"]')
        ))
        search_box.click()
        time.sleep(0.5)
        search_box.clear()
        search_box.send_keys(group_name)
        time.sleep(2)
        
        # 2. Click the group
        try:
            group_element = wait.until(EC.element_to_be_clickable(
                (By.XPATH, f'//span[@title="{group_name}"]')
            ))
            group_element.click()
            print(f"[*] Opened: {group_name}")
            time.sleep(2)
        except TimeoutException:
            print(f"[!] Group not found: {group_name}")
            return 0
        
        # 3. Open group info (click header)
        try:
            header = driver.find_element(By.CSS_SELECTOR, 'header')
            header.click()
            time.sleep(2)
        except NoSuchElementException:
            print("[!] Could not find group header")
            return 0
        
        # 4. Look for "Pending participants" section
        try:
            # Various possible selectors for pending participants
            pending_selectors = [
                '//div[contains(text(), "Pending")]',
                '//span[contains(text(), "Pending")]',
                '//*[contains(text(), "Waiting")]',
                '//div[contains(@class, "pending")]'
            ]
            
            pending_btn = None
            for selector in pending_selectors:
                try:
                    pending_btn = driver.find_element(By.XPATH, selector)
                    break
                except NoSuchElementException:
                    continue
            
            if not pending_btn:
                print(f"    -> No pending requests for {group_name}")
                # Close side panel
                close_panel(driver)
                return 0
            
            pending_btn.click()
            time.sleep(2)
            
        except Exception as e:
            print(f"    -> No pending participants: {e}")
            close_panel(driver)
            return 0
        
        # 5. Process pending requests
        try:
            # Find all pending request items
            # Note: Exact selectors may change with WhatsApp Web updates
            request_items = driver.find_elements(
                By.CSS_SELECTOR, 
                '[data-testid="cell-frame-container"]'
            )
            
            if not request_items:
                # Try alternative selector
                request_items = driver.find_elements(
                    By.XPATH,
                    '//div[contains(@class, "participant")]'
                )
            
            print(f"    Found {len(request_items)} pending request(s)")
            
            for item in request_items[:MAX_APPROVALS_PER_CYCLE]:
                try:
                    phone = extract_phone_from_element(item)
                    
                    if not phone:
                        print(f"       [?] Could not extract phone from request")
                        continue
                    
                    # Check whitelist
                    if phone in whitelist:
                        # Check idempotency
                        if is_already_approved(phone, group_name):
                            print(f"       [=] Already approved: {phone}")
                            continue
                        
                        # Find and click approve button
                        try:
                            approve_btn = item.find_element(
                                By.CSS_SELECTOR, 
                                '[data-testid="approve"]'
                            )
                            approve_btn.click()
                            time.sleep(1)
                            
                            # Log the approval
                            log_approval(phone, group_name)
                            approvals += 1
                            print(f"       [+] APPROVED: {phone} (ID: {whitelist[phone]})")
                            
                        except NoSuchElementException:
                            # Try alternative approve button selector
                            try:
                                approve_btn = item.find_element(
                                    By.XPATH, 
                                    './/span[@data-icon="checkmark"]/..'
                                )
                                approve_btn.click()
                                time.sleep(1)
                                log_approval(phone, group_name)
                                approvals += 1
                                print(f"       [+] APPROVED: {phone}")
                            except:
                                print(f"       [!] Could not find approve button for {phone}")
                    else:
                        print(f"       [-] NOT in whitelist: {phone}")
                        
                except Exception as e:
                    print(f"       [!] Error processing request: {e}")
                    continue
                    
        except Exception as e:
            print(f"    [!] Error scanning requests: {e}")
        
        # Close the side panel
        close_panel(driver)
        
    except Exception as e:
        print(f"[!] Error processing group {group_name}: {e}")
    
    return approvals

def close_panel(driver):
    """Close the side info panel."""
    try:
        # Press Escape to close
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
        time.sleep(1)
    except:
        pass

def run_bot():
    """Main bot loop."""
    print("=" * 50)
    print("  ACES WhatsApp Auto-Approval Bot")
    print("=" * 50)
    print(f"[*] Monitoring groups: {GROUPS}")
    print(f"[*] Check interval: {CHECK_INTERVAL}s")
    print("[*] Opening Chrome - please wait for QR code...\n")

    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--window-size=1200,800")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    print("[*] Launching Chrome...")
    try:
        driver = webdriver.Chrome(
            service=ChromeService(ChromeDriverManager().install()), 
            options=chrome_options
        )
    except Exception as e:
        print(f"[!] Failed to start Chrome: {e}")
        print("[!] Make sure Chrome browser is installed and up to date.")
        return
    
    try:
        driver.get("https://web.whatsapp.com")
        
        # Wait for login (up to 2 minutes for QR scan)
        wait = WebDriverWait(driver, 120)
        print("[*] Waiting for WhatsApp Web login...")
        
        wait.until(EC.presence_of_element_located(
            (By.XPATH, '//div[@contenteditable="true"][@data-tab="3"]')
        ))
        print("[*] Logged in successfully!\n")

        # Main monitoring loop
        cycle = 0
        while True:
            cycle += 1
            print(f"\n{'='*40}")
            print(f"[Cycle {cycle}] {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*40}")
            
            # Refresh whitelist each cycle
            whitelist = get_whitelist()
            print(f"[*] Whitelist has {len(whitelist)} verified numbers")
            
            total_approvals = 0
            
            for group_name in GROUPS:
                approvals = process_group(driver, wait, group_name, whitelist)
                total_approvals += approvals
            
            if total_approvals > 0:
                print(f"\n[*] Total approved this cycle: {total_approvals}")
            
            print(f"\n[*] Sleeping for {CHECK_INTERVAL}s...")
            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\n[*] Bot stopped by user.")
    except Exception as e:
        print(f"\n[!] Critical Error: {e}")
    finally:
        driver.quit()
        print("[*] Browser closed.")

if __name__ == "__main__":
    run_bot()
