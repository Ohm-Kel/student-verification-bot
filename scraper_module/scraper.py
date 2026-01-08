import sqlite3
import time
import os
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException, ElementClickInterceptedException

# --- Configuration ---
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'students.db')
BASE_URL = "https://apps.knust.edu.gh/admissions/check/Home/Undergraduates"

# We search for "Computer" to be safe, then filter for "Computer Eng" in Python
# This handles "BSc. Computer Eng", "Computer Engineering", etc.
SEARCH_TERM = "Computer"  
TARGET_KEYWORDS = ["COMPUTER ENG", "COMPUTER ENGINEERING"] 

# --- Database Setup ---
def init_db():
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS valid_students (
                app_id TEXT PRIMARY KEY,
                full_name TEXT,
                programme TEXT,
                category TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS whitelist (
                phone_number TEXT PRIMARY KEY,
                app_id TEXT,
                FOREIGN KEY(app_id) REFERENCES valid_students(app_id)
            )
        ''')
        conn.commit()
        conn.close()
        print(f"[*] Database initialized at {DB_PATH}")
    except Exception as e:
        print(f"[!] DB Init Error: {e}")

def save_student(app_id, name, programme, category):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR REPLACE INTO valid_students (app_id, full_name, programme, category)
            VALUES (?, ?, ?, ?)
        ''', (app_id, name, programme, category))
        conn.commit()
        return True
    except Exception as e:
        print(f"[!] Error saving {name}: {e}")
        return False
    finally:
        conn.close()

def is_target_programme(prog_text):
    """Check if programme matches our target criteria."""
    if not prog_text:
        return False
    prog_upper = prog_text.upper()
    return any(keyword in prog_upper for keyword in TARGET_KEYWORDS)

# --- Scraper Logic ---
def run_scraper():
    print("[*] Starting Comprehensive Scraper...")
    print(f"[*] Expecting at least 438 students.")

    chrome_options = Options()
    # chrome_options.add_argument("--headless=new") # Run visible to debug if needed, or headless
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--log-level=3")

    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        driver.get(BASE_URL)
        print(f"[*] Loaded {BASE_URL}")
        wait = WebDriverWait(driver, 20)

        category_ids = [
            "v-pills-international-applicants-tab",
            "v-pills-fee-paying-other-applicants-tab",
            "v-pills-mature-applicants-tab",
            "v-pills-wassce-applicants-tab",
            "v-pills-fee-paying-wassce-applicants-tab",
            "v-pills-less-endowed-applicants-tab",
            "v-pills-nmtc-upgrade-tab"
        ]

        total_saved_session = 0

        for cat_id in category_ids:
            print(f"\n{'='*50}")
            print(f"[-] Processing Category: {cat_id}")
            print(f"{'='*50}")

            try:
                # 1. Activate Tab
                tab_element = wait.until(EC.element_to_be_clickable((By.ID, cat_id)))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tab_element)
                time.sleep(1)
                try:
                    tab_element.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", tab_element)
                
                # 2. Find Search Box for this pane
                pane_id = cat_id.replace('-tab', '')
                pane_selector = f"#{pane_id}"
                
                wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, pane_selector)))
                pane_element = driver.find_element(By.CSS_SELECTOR, pane_selector)
                
                # Wait for table to be ready (look for input)
                time.sleep(2)
                
                # DataTables search input
                # Usually: div.dataTables_filter input
                try:
                    search_box = pane_element.find_element(By.CSS_SELECTOR, "input[type='search']")
                except NoSuchElementException:
                    # Sometimes structure is slightly different or global
                    # Try finding ANY search input visible
                    inputs = pane_element.find_elements(By.TAG_NAME, "input")
                    search_box = None
                    for inp in inputs:
                        if inp.get_attribute("type") == "search":
                            search_box = inp
                            break
                    if not search_box:
                        print(f"    [!] Could not find search box for {cat_id}")
                        continue

                # 3. Enter Broad Search Term
                search_box.clear()
                search_box.send_keys(SEARCH_TERM)
                print(f"    -> Searching for '{SEARCH_TERM}'...")
                
                # Wait for filter to apply
                time.sleep(3)

                # 4. Pagination Loop
                page_num = 1
                cat_count = 0
                
                while True:
                    # Scrape current page rows
                    try:
                        # Re-locate table to avoid stale elements
                        updated_pane = driver.find_element(By.CSS_SELECTOR, pane_selector)
                        table = updated_pane.find_element(By.CSS_SELECTOR, "table.dataTable")
                        rows = table.find_elements(By.TAG_NAME, "tr")
                    except Exception as e:
                        print(f"    [!] Error locating table: {e}")
                        break

                    rows_scraped_on_page = 0
                    for row in rows:
                        try:
                            cols = row.find_elements(By.TAG_NAME, "td")
                            if len(cols) < 5:
                                continue # Header or empty
                            
                            # Columns: #, ID, Name, Programme, Action
                            app_id = cols[1].text.strip()
                            name = cols[2].text.strip()
                            prog = cols[3].text.strip()
                            
                            # Filter strictly for Computer Engineering
                            if is_target_programme(prog):
                                if save_student(app_id, name, prog, cat_id):
                                    cat_count += 1
                                    rows_scraped_on_page += 1
                                    # Optional: print specific students or just progress
                                    # print(f"       + Saved: {name} ({app_id})")
                        except StaleElementReferenceException:
                            continue # Skip row if stale

                    # print(f"    -> Page {page_num}: Found {rows_scraped_on_page} relevant students")

                    # Check for Next Button
                    # Selector: .paginate_button.next
                    # It must NOT have class 'disabled'
                    try:
                        # Need to find the pagination controls SPECIFIC to this pane
                        # Usually follows the table
                        # ID for wrapper often ends in _wrapper
                        
                        # Simpler: Find visible "Next" button inside this pane (or global if ID based)
                        # DataTables IDs are dynamic (DataTables_Table_0_paginate)
                        
                        # Find the pagination container within the pane
                        # Usually: .dataTables_paginate
                        
                        # Finding the "Next" button
                        next_btn_candidates = updated_pane.find_elements(By.CSS_SELECTOR, ".paginate_button.next")
                        
                        next_btn = None
                        for btn in next_btn_candidates:
                            if btn.is_displayed():
                                next_btn = btn
                                break
                        
                        if not next_btn:
                            # print("    [|] No Next button found (single page?)")
                            break
                        
                        # Check if disabled
                        classes = next_btn.get_attribute("class")
                        if "disabled" in classes:
                            # print("    [|] Next button disabled - Reached last page.")
                            break
                        
                        # Click Next
                        # print(f"    [>] Moving to Page {page_num + 1}...")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                        time.sleep(0.5)
                        next_btn.click()
                        
                        page_num += 1
                        time.sleep(2) # Wait for page load
                        
                    except Exception as e:
                        print(f"    [!] Pagination error: {e}")
                        break

                print(f"    [+] Category Complete. Total: {cat_count}")
                total_saved_session += cat_count

            except Exception as e:
                print(f"    [!] Critical error in category {cat_id}: {e}")

        print("\n" + "="*30)
        print(f"[*] SCRAPE COMPLETE.")
        print(f"[*] Total Students Found in this session: {total_saved_session}")
        
        # Verify Total DB Count
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM valid_students")
        final_count = c.fetchone()[0]
        print(f"[*] Total Database Count: {final_count}")
        conn.close()
        
        print("="*30)

    except Exception as e:
        print(f"[!] Critical Driver Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    init_db()
    run_scraper()
