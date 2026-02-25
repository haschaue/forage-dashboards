"""
Forage Kitchen - Email Daily Dashboard
Sends the daily_dashboard.html as an email attachment and inline preview.

Usage: python email_dashboard.py
       (Usually called automatically by refresh_dashboard.bat)

Requires: SMTP AUTH enabled on your Microsoft 365 account.
If you get auth errors, you may need to enable SMTP AUTH in Microsoft 365 admin.
"""
import smtplib
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

# ============================================================
# EMAIL CONFIG
# ============================================================
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587
SMTP_USER = "henry@foragekombucha.com"
# You'll need to set your password below or use an app password.
# For security, we read it from an environment variable first,
# falling back to the hardcoded value.
SMTP_PASSWORD = os.environ.get("FORAGE_EMAIL_PASSWORD", "")

SENDER = "henry@foragekombucha.com"
RECIPIENTS = [
    "eric@eatforage.com",
    "darlene@eatforage.com",
    "ben@eatforage.com",
    "alexia@eatforage.com",
    "bryan@foragemadison.com",
]

DASHBOARD_PATH = os.path.join(
    "C:/Users/ascha/OneDrive/Desktop/forage-data",
    "daily_dashboard.html"
)


def send_dashboard():
    if not SMTP_PASSWORD:
        print("ERROR: No email password configured.")
        print("Set FORAGE_EMAIL_PASSWORD environment variable, or edit email_dashboard.py")
        print("To set it permanently, run this in Command Prompt (as admin):")
        print('  setx FORAGE_EMAIL_PASSWORD "your_password_here"')
        sys.exit(1)

    if not os.path.exists(DASHBOARD_PATH):
        print(f"ERROR: Dashboard not found at {DASHBOARD_PATH}")
        print("Run daily_dashboard.py first.")
        sys.exit(1)

    # Read the dashboard HTML
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()

    today = datetime.now()
    subject = f"Forage Kitchen Daily Sales Dashboard - {today.strftime('%m/%d/%Y')}"

    # Build email
    msg = MIMEMultipart("mixed")
    msg["From"] = SENDER
    msg["To"] = ", ".join(RECIPIENTS)
    msg["Subject"] = subject

    # Email body - simple summary with link suggestion
    body_html = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333;">
    <h2 style="color: #22c55e;">Forage Kitchen - Daily Sales Dashboard</h2>
    <p>Attached is today's sales dashboard for <strong>{today.strftime('%A, %B %d, %Y')}</strong>.</p>
    <p>Download and open the attached HTML file in your browser for the full interactive dashboard
    with charts, store breakdowns, and daily detail.</p>
    <p style="color: #666; font-size: 12px;">
    Data source: Toast POS &bull; Generated {today.strftime('%m/%d/%Y %I:%M %p')}
    </p>
    </body></html>
    """
    msg.attach(MIMEText(body_html, "html"))

    # Attach the HTML dashboard file
    attachment = MIMEBase("text", "html")
    attachment.set_payload(html_content.encode("utf-8"))
    encoders.encode_base64(attachment)
    filename = f"Forage_Dashboard_{today.strftime('%Y%m%d')}.html"
    attachment.add_header("Content-Disposition", f"attachment; filename={filename}")
    msg.attach(attachment)

    # Send
    print(f"  Connecting to {SMTP_SERVER}:{SMTP_PORT}...")
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"  Dashboard emailed to {len(RECIPIENTS)} recipients:")
        for r in RECIPIENTS:
            print(f"    - {r}")
        print(f"  Subject: {subject}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"  AUTH ERROR: {e}")
        print("  Possible fixes:")
        print("  1. Check your password is correct")
        print("  2. Enable SMTP AUTH in Microsoft 365 admin center:")
        print("     Admin > Users > Active Users > henry@ > Mail > Manage email apps > check 'Authenticated SMTP'")
        print("  3. If using MFA, create an App Password in your Microsoft account security settings")
        return False
    except Exception as e:
        print(f"  EMAIL ERROR: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("  Forage Kitchen - Emailing Dashboard")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)
    send_dashboard()
