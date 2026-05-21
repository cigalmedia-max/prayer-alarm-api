from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
import logging
import os
import time
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

app = Flask(__name__)

# Pull credentials from Render environment settings
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
RECEIVER_EMAIL = os.environ.get('RECEIVER_EMAIL')

# Force system to use London Time
os.environ['TZ'] = 'Europe/London'
time.tzset()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [UK TIME] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def send_email_alert(error_message):
    """Sends an automated fallback email if the web scraper fails."""
    if not all([SENDGRID_API_KEY, SENDER_EMAIL, RECEIVER_EMAIL]):
        logger.critical("Email environment variables are missing! Cannot send alert.")
        return

    message = Mail(
        from_email=SENDER_EMAIL,
        to_emails=RECEIVER_EMAIL,
        subject='⚠️ PRAYER ALARM FAILURE ALERT!',
        plain_text_content=f"The East End Islamic Centre alarm scraper has failed.\n\n"
                           f"Reason: {error_message}\n"
                           f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                           f"Please check and set your morning alarms manually!"
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"Alert email sent successfully. Status code: {response.status_code}")
    except Exception as email_error:
        logger.critical(f"Failed to send alert email: {str(email_error)}")

def subtract_buffer(time_str, buffer_mins, is_pm=False):
    try:
        hours, minutes = map(int, time_str.split(':'))
        if is_pm and hours < 12:
            hours += 12
        base_time = datetime.strptime(f"{hours:02d}:{minutes:02d}", "%H:%M")
        alarm_time = base_time - timedelta(minutes=buffer_mins)
        return alarm_time.strftime("%H:%M")
    except Exception:
        return None

@app.route('/get-all-alarms', methods=['GET'])
def get_all_alarms():
    logger.info("iPhone shortcut triggered! Scraping East End Islamic Centre website...")
    
    try:
        url = "https://eastendislamic.co.uk"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            error_msg = f"Masjid website returned HTTP error code {response.status_code}"
            logger.error(error_msg)
            send_email_alert(error_msg)
            return jsonify({"success": False, "error": "Masjid website down"}), 500
            
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text()
        
        match = re.search(r"Jama'ah\s+(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})", page_text)
        
        if not match:
            error_msg = "Could not parse timetable matrix. The website layout might have changed."
            logger.error(error_msg)
            send_email_alert(error_msg)
            return jsonify({"success": False, "error": "Could not parse timetable matrix"}), 404
            
        raw_fajr, raw_zuhr, raw_asr, raw_maghrib, raw_isha = match.groups()
        
        # Adjust individual prayer alarm buffers here (in minutes)
        alarms = {
            "Fajr":    subtract_buffer(raw_fajr,    buffer_mins=20, is_pm=False),
            "Zuhr":    subtract_buffer(raw_zuhr,    buffer_mins=15, is_pm=True),
            "Asr":     subtract_buffer(raw_asr,     buffer_mins=20, is_pm=True),
            "Maghrib": subtract_buffer(raw_maghrib, buffer_mins=10, is_pm=True),
            "Isha":    subtract_buffer(raw_isha,    buffer_mins=15, is_pm=True)
        }
        
        logger.info(f"Successfully calculated alarms. Fajr set to {alarms['Fajr']}.")
        return jsonify({"success": True, "buffered_alarms": alarms})
        
    except Exception as e:
        error_msg = f"Unexpected Server Exception: {str(e)}"
        logger.critical(error_msg)
        send_email_alert(error_msg)
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
