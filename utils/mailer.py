import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import threading

def send_email_async(subject, recipient, body_html):
    """Sends an email asynchronously to avoid blocking the main thread."""
    def _send():
        smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
        sender_email = os.environ.get("SMTP_USER")
        sender_password = os.environ.get("SMTP_PASSWORD")

        if not sender_email or not sender_password:
            print("Warning: SMTP credentials not set. Email not sent.")
            return

        try:
            msg = MIMEMultipart()
            msg["From"] = sender_email
            msg["To"] = recipient
            msg["Subject"] = subject

            msg.attach(MIMEText(body_html, "html"))

            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
            
            print(f"Email sent successfully to {recipient}")
        except Exception as e:
            print(f"Failed to send email to {recipient}: {e}")

    # Run in a separate thread
    threading.Thread(target=_send, daemon=True).start()

def send_run_completion_email(user_email, run_id, status, start_time=None, run_url=None, tool_name="Pipeline"):
    """Composes and sends the pipeline completion email."""
    
    subject_status = "✅ Success" if status == "completed" else "❌ Failed" if status == "failed" else "⚠️ Cancelled"
    
    if tool_name.upper() == "BLAST":
         subject = f"BLAST {subject_status}: Run #{run_id}"
         header_text = f"BLAST Analysis {status.title()}"
    else:
         subject = f"Analysis {subject_status}: Run #{run_id}"
         header_text = f"Pipeline Analysis {status.title()}"
    
    color = "#10b981" if status == "completed" else "#ef4444" if status == "failed" else "#f59e0b"
    
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
            <div style="text-align: center; padding-bottom: 20px; border-bottom: 2px solid {color};">
                <h2 style="color: {color}; margin: 0;">{header_text}</h2>
            </div>
            
            <div style="padding: 20px 0;">
                <p>Hello,</p>
                <p>Your analysis pipeline has finished executing.</p>
                
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0; background: #f9fafb;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>Run ID:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;">{run_id}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>Status:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee; color: {color}; font-weight: bold;">{status.upper()}</td>
                    </tr>
                </table>
                
                
            </div>
            
            <div style="font-size: 12px; color: #666; text-align: center; margin-top: 30px; border-top: 1px solid #eee; padding-top: 10px;">
                <p>This is an automated message from your Gene Analysis Pipeline.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    send_email_async(subject, user_email, html_content)

def send_run_start_email(user_email, run_id, tool_name="BLAST", run_url=None):
    """Composes and sends the pipeline start email."""
    
    subject = f"🚀 Pipeline Started: {tool_name} Run #{run_id}"
    color = "#3b82f6" # Blue for started
    
    # Optional button link
    button_html = ""
    if run_url:
        button_html = f"""
        <div style="text-align: center; margin: 30px 0;">
            <a href="{run_url}" style="background-color: {color}; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">View Live Status</a>
        </div>
        """

    html_content = f"""
    <html>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
            <div style="text-align: center; padding-bottom: 20px; border-bottom: 2px solid {color};">
                <h2 style="color: {color}; margin: 0;">Analysis Started</h2>
            </div>
            
            <div style="padding: 20px 0;">
                <p>Hello,</p>
                <p>Your <strong>{tool_name}</strong> analysis pipeline has successfully started.</p>
                <p>We are processing your files now. You will receive another email when the analysis is complete.</p>
                
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0; background: #f8fafc; border-radius: 8px; overflow: hidden;">
                    <tr>
                        <td style="padding: 12px 15px; border-bottom: 1px solid #e2e8f0; color: #64748b;"><strong>Run ID:</strong></td>
                        <td style="padding: 12px 15px; border-bottom: 1px solid #e2e8f0; font-family: monospace;">{run_id}</td>
                    </tr>
                    <tr>
                        <td style="padding: 12px 15px; border-bottom: 1px solid #e2e8f0; color: #64748b;"><strong>Tool:</strong></td>
                        <td style="padding: 12px 15px; border-bottom: 1px solid #e2e8f0;">{tool_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 12px 15px; border-bottom: 1px solid #e2e8f0; color: #64748b;"><strong>Status:</strong></td>
                        <td style="padding: 12px 15px; border-bottom: 1px solid #e2e8f0; color: {color}; font-weight: bold;">RUNNING</td>
                    </tr>
                </table>
                
                {button_html}
            </div>
            
            <div style="font-size: 12px; color: #94a3b8; text-align: center; margin-top: 30px; border-top: 1px solid #e2e8f0; padding-top: 15px;">
                <p>This is an automated message from your MapNMark Pipeline.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    send_email_async(subject, user_email, html_content)
