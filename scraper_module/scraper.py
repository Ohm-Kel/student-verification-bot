import sqlite3
import time
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
BASE_URL = "https://apps.knust.edu.gh/admissions/check/Home/Undergraduates"
TARGET_PROGRAMME = "Computer Eng" # Matches 'Computer Eng.' and 'Computer Engineering' 

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

# --- Scraper Logic ---
def run_scraper():
    print("[*] Starting Scraper with Search Optimization...")
    
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    # Suppress logging
    chrome_options.add_argument("--log-level=3")

    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        driver.get(BASE_URL)
        print(f"[*] Loaded {BASE_URL}")
        wait = WebDriverWait(driver, 20)

        # Updated Selectors based on inspection
        category_ids = [
            "v-pills-international-applicants-tab",
            "v-pills-fee-paying-other-applicants-tab",
            "v-pills-mature-applicants-tab",
            "v-pills-wassce-applicants-tab",
            "v-pills-fee-paying-wassce-applicants-tab",
            "v-pills-less-endowed-applicants-tab",
            "v-pills-nmtc-upgrade-tab"  # Added NMTC Upgrade
        ]

        total_saved = 0

        for cat_id in category_ids:
            try:
                # 1. Click Category Tab
                print(f"\n[-] Processing Category ID: {cat_id}")
                tab_element = wait.until(EC.element_to_be_clickable((By.ID, cat_id)))
                
                # Scroll into view to avoid clicks being intercepted
                driver.execute_script("arguments[0].scrollIntoView(true);", tab_element)
                time.sleep(1) # Small pause for scroll stability
                tab_element.click()
                
                # 2. Identify the active pane and its Search Box
                # The panes use ID: cat_id minus '-tab'
                pane_id = cat_id.replace('-tab', '')
                pane_selector = f"#{pane_id}"
                
                # Wait for pane to be visible
                wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, pane_selector)))
                
                # Find the search box inside this pane's dataTables wrapper
                # It's usually: input[type='search'] inside the wrapper. 
                # We need to be careful to get the one for *this* table. 
                # We can scope the search to the pane.
                pane_element = driver.find_element(By.CSS_SELECTOR, pane_selector)
                
                # DataTables injects the control outside the table but often inside the wrapper inside the pane?
                # Looking at DOM dump: <div id="DataTables_Table_0_filter" ...><input search></div>
                # The ID increments (Table_0, Table_1...). 
                # Safer to find input type='search' *visible* on page (since tabs hide others).
                
                # Wait a moment for DataTables to initialize if it's lazy loaded
                time.sleep(2) 
                
                search_box = pane_element.find_element(By.CSS_SELECTOR, "input[type='search']")
                
                # 3. Enter Filter: "Computer Engineering"
                search_box.clear()
                search_box.send_keys(TARGET_PROGRAMME)
                print(f"    -> Filtered by '{TARGET_PROGRAMME}'")
                
                # Wait for filter to apply (Table rows update)
                time.sleep(2) 
                
                # 4. Scrape Rows
                # Find the table in this pane
                try:
                    table = pane_element.find_element(By.CSS_SELECTOR, "table.dataTable")
                    rows = table.find_elements(By.TAG_NAME, "tr")
                except:
                    print("    [!] No table found in this pane.")
                    continue

                count_in_cat = 0
                for row in rows:
                    cols = row.find_elements(By.TAG_NAME, "td")
                    if len(cols) < 5:
                        continue # Header or empty
                    
                    # Columns: #, ID, Name, Programme, Action
                    app_id = cols[1].text.strip()
                    name = cols[2].text.strip()
                    prog = cols[3].text.strip()
                    
                    if TARGET_PROGRAMME.lower() in prog.lower():
                        if save_student(app_id, name, prog, cat_id):
                            count_in_cat += 1
                            print(f"       + Saved: {name} ({app_id})")
                
                # Check for 'Next' button if we have many results (Optimization: Assuming <10 per cat with filter, but checking)
                # If "No matching records found" is typically a row with colspan.
                if count_in_cat == 0:
                    print("    -> No students found.")
                else:
                    total_saved += count_in_cat
                    
            except Exception as e:
                print(f"    [!] Error processing category {cat_id} or no search box: {e}")

        print("\n" + "="*30)
        print(f"[*] Scrape Complete. Total Students Saved: {total_saved}")
        print("="*30)

    except Exception as e:
        print(f"[!] Critical Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    init_db()
    run_scraper()
