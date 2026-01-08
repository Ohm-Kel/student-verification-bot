from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'fallback_secret_key')

# --- Config ---
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'students.db')
WHATSAPP_LINK_OFFICIAL = os.getenv('WHATSAPP_LINK_OFFICIAL', '')
WHATSAPP_LINK_UNOFFICIAL = os.getenv('WHATSAPP_LINK_UNOFFICIAL', '')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/verify', methods=['POST'])
def verify_student():
    app_id = request.form.get('app_id', '').strip()
    
    if not app_id:
        flash("Please enter your Application ID.", "error")
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    student = conn.execute('SELECT * FROM valid_students WHERE app_id = ?', (app_id,)).fetchone()
    conn.close()
    
    if student:
        session['verified_app_id'] = student['app_id']
        session['verified_name'] = student['full_name']
        session['verified_prog'] = student['programme']
        return redirect(url_for('confirm_identity'))
    else:
        flash("Access Denied. ID not found in Computer Engineering admission list.", "error")
        return redirect(url_for('index'))

@app.route('/confirm', methods=['GET', 'POST'])
def confirm_identity():
    if 'verified_app_id' not in session:
        return redirect(url_for('index'))
    
    name = session.get('verified_name')
    
    if request.method == 'POST':
        phone = request.form.get('phone_number', '').strip()
        
        if len(phone) < 10:
             flash("Please enter a valid phone number.", "error")
             return render_template('confirm.html', name=name)

        app_id = session['verified_app_id']
        
        try:
            conn = get_db_connection()
            conn.execute('INSERT OR REPLACE INTO whitelist (phone_number, app_id) VALUES (?, ?)', 
                         (phone, app_id))
            conn.commit()
            conn.close()
            
            session.pop('verified_app_id', None)
            
            return render_template('success.html', 
                                   whatsapp_link_official=WHATSAPP_LINK_OFFICIAL,
                                   whatsapp_link_unofficial=WHATSAPP_LINK_UNOFFICIAL)
            
        except Exception as e:
            flash(f"System Error: {e}", "error")
            return render_template('confirm.html', name=name)

    return render_template('confirm.html', name=name)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
