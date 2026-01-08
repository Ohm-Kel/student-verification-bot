"""
ACES Freshmen Verification Web App
===================================
Verifies students against the admission database and collects
their WhatsApp number for auto-approval in the group.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import os
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'fallback_secret_key_change_in_production')

# --- Config ---
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'students.db')
WHATSAPP_LINK_OFFICIAL = os.getenv('WHATSAPP_LINK_OFFICIAL', '')
WHATSAPP_LINK_UNOFFICIAL = os.getenv('WHATSAPP_LINK_UNOFFICIAL', '')


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_phone(phone):
    """
    Normalize phone number to consistent format for matching.
    Handles: +233XXXXXXXXX, 0XXXXXXXXX, 233XXXXXXXXX
    Returns: 233XXXXXXXXX
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


def is_already_verified(app_id):
    """Check if this application ID already has a phone number registered."""
    conn = get_db_connection()
    result = conn.execute(
        'SELECT phone_number FROM whitelist WHERE app_id = ?', 
        (app_id,)
    ).fetchone()
    conn.close()
    return result is not None


def validate_phone(phone):
    """Validate phone number format."""
    digits = re.sub(r'\D', '', phone)
    
    # Must be 9-12 digits
    if len(digits) < 9 or len(digits) > 12:
        return False, "Phone number must be 9-12 digits"
    
    # Should start with expected prefixes for Ghana
    if digits.startswith('0'):
        if len(digits) != 10:
            return False, "Local numbers should be 10 digits (e.g., 0551234567)"
    elif digits.startswith('233'):
        if len(digits) != 12:
            return False, "International format should be 12 digits (e.g., 233551234567)"
    
    return True, ""


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/verify', methods=['POST'])
def verify_student():
    app_id = request.form.get('app_id', '').strip()
    
    if not app_id:
        flash("Please enter your Application ID.", "error")
        return redirect(url_for('index'))
    
    # Remove any spaces or dashes from ID
    app_id = re.sub(r'[\s\-]', '', app_id)
    
    conn = get_db_connection()
    student = conn.execute(
        'SELECT * FROM valid_students WHERE app_id = ?', 
        (app_id,)
    ).fetchone()
    conn.close()
    
    if student:
        # Check if already verified (idempotency)
        if is_already_verified(app_id):
            flash("You have already verified! Use the links you received earlier.", "info")
            return render_template('success.html', 
                                   whatsapp_link_official=WHATSAPP_LINK_OFFICIAL,
                                   whatsapp_link_unofficial=WHATSAPP_LINK_UNOFFICIAL)
        
        # Store in session for next step
        session['verified_app_id'] = student['app_id']
        session['verified_name'] = student['full_name']
        session['verified_prog'] = student['programme']
        return redirect(url_for('confirm_identity'))
    else:
        flash("Access Denied. Your ID was not found in the Computer Engineering admission list.", "error")
        return redirect(url_for('index'))


@app.route('/confirm', methods=['GET', 'POST'])
def confirm_identity():
    # Security check: must have verified ID in session
    if 'verified_app_id' not in session:
        flash("Please verify your Application ID first.", "error")
        return redirect(url_for('index'))
    
    name = session.get('verified_name')
    app_id = session['verified_app_id']
    
    if request.method == 'POST':
        phone = request.form.get('phone_number', '').strip()
        
        # Validate phone
        is_valid, error_msg = validate_phone(phone)
        if not is_valid:
            flash(error_msg, "error")
            return render_template('confirm.html', name=name)
        
        # Normalize phone for storage
        normalized_phone = normalize_phone(phone)
        
        try:
            conn = get_db_connection()
            
            # Check if this phone is already used by someone else
            existing = conn.execute(
                'SELECT app_id FROM whitelist WHERE phone_number = ? AND app_id != ?',
                (normalized_phone, app_id)
            ).fetchone()
            
            if existing:
                conn.close()
                flash("This phone number is already registered by another student.", "error")
                return render_template('confirm.html', name=name)
            
            # Save to whitelist (INSERT OR REPLACE handles re-verification)
            conn.execute(
                'INSERT OR REPLACE INTO whitelist (phone_number, app_id) VALUES (?, ?)', 
                (normalized_phone, app_id)
            )
            conn.commit()
            conn.close()
            
            # Clear session
            session.pop('verified_app_id', None)
            session.pop('verified_name', None)
            session.pop('verified_prog', None)
            
            return render_template('success.html', 
                                   whatsapp_link_official=WHATSAPP_LINK_OFFICIAL,
                                   whatsapp_link_unofficial=WHATSAPP_LINK_UNOFFICIAL)
            
        except Exception as e:
            flash(f"An error occurred. Please try again.", "error")
            print(f"[!] Database error: {e}")
            return render_template('confirm.html', name=name)

    return render_template('confirm.html', name=name)


@app.route('/health')
def health_check():
    """Health check endpoint for monitoring."""
    try:
        conn = get_db_connection()
        count = conn.execute('SELECT COUNT(*) FROM valid_students').fetchone()[0]
        conn.close()
        return {"status": "healthy", "students_in_db": count}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}, 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
