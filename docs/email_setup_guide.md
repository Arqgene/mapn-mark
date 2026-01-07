# 📧 How to Setup Email Notifications (Gmail)

The application uses **SMTP** to send emails. For Gmail, you cannot use your regular password. You must use an **App Password**.

## Step 1: Create/Prepare Gmail Account
1.  Go to [Google Account Settings](https://myaccount.google.com/).
2.  Select **Security** from the left menu.
3.  Scroll to **"How you sign in to Google"**.
4.  Enable **2-Step Verification** (if not already on).

## Step 2: Generate App Password
1.  In the same **Security** section, search for **"App passwords"** (you can use the search bar at the top).
2.  Create a new app name: e.g., `GenePipeline`.
3.  Click **Create**.
4.  Google will show you a **16-character code** (e.g., `abcd efgh ijkl mnop`).
    *   **COPY THIS CODE.** It is your "SMTP_PASSWORD".

## Step 3: Configure Application
1.  Open the file `d:\gene\.env` in your project folder.
2.  Add or update the following lines:

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop
```
*(Replace `your_email` with your actual address and the password with the 16-char code you just copied).*

## Step 4: Restart
Restart the application for changes to take effect:
1.  Close the running terminal (`Ctrl+C`).
2.  Run `python main.py` again.

---
### Troubleshooting
*   **Authentication Failed?** Check that you copied the 16-char code correctly without extra spaces.
*   **Port Error?** Ensure `SMTP_PORT` is set to `587`.
