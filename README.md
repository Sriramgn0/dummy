# Website

A Flask and MongoDB order portal for customer print requests, admin quotations, UPI payment confirmation, and delivery tracking.

## Run locally

1. Start MongoDB locally or create a MongoDB Atlas database.
2. If `.env` does not exist, copy `.env.example` to `.env`. The local `.env` is ignored by Git. Fill in `MONGO_URI` from your MongoDB Atlas driver connection string and replace `FLASK_SECRET_KEY` with a long random value. Special characters in the database password must be URL-encoded.

3. Install dependencies in the project virtual environment:

   ```sh
   .venv/bin/python -m pip install -r requirements.txt
   ```

4. Start Flask:

   ```sh
   .venv/bin/python 1.py
   ```

   In Atlas, add the machine running this app to **Network Access** and confirm that the database user exists under **Database Access**. Never commit `.env` or share its contents.

5. Open <http://127.0.0.1:5000>.

To serve HTTPS directly from Flask when you already have a TLS certificate and matching private key, set `HTTPS_CERTIFICATE` and `HTTPS_PRIVATE_KEY` in `.env`:

```dotenv
HTTPS_CERTIFICATE=/path/to/fullchain.pem
HTTPS_PRIVATE_KEY=/path/to/private-key.pem
```

Open <https://127.0.0.1:5000> (or use the hostname covered by your certificate). Both variables are required together; when neither is set, the app continues to use HTTP. Keep the private key secret. Flask's built-in server is for development; for production, terminate HTTPS at a production web server or reverse proxy.

## Login sessions

Signed-in sessions expire after 30 minutes without activity by default. Set `SESSION_IDLE_TIMEOUT_MINUTES` in `.env` to change the inactivity timeout. Signing out revokes the current session.

For local testing, `.env.example` enables demo mode and displays its configured demo credentials on the login screen. Set unique values for `DEMO_ADMIN_PASSWORD` and `DEMO_CUSTOMER_PASSWORD` in `.env`; on first run, the app creates the demo administrator if that username is not already present. Disable demo mode outside local testing. Public signup creates customer accounts only; email verification is not configured.

## UPI payments

Set the shop's receiving UPI ID in `.env`:

```dotenv
RAJU_UPI_ID=shop@upi
RAJU_UPI_NAME=Raju Printer
```

Customers can open an installed UPI app with the order amount and tracking ID prefilled, then report that they sent payment. Orders remain unpaid until an admin checks the shop account and marks the payment received. Admins can mark an order paid directly from the active queue after checking the receipt, then set it to work in progress, record an expected delivery date, and mark it delivered. Status and date changes are added to the order timeline and sent to opted-in customers. Configure the standard delivery fee with the digital rate card in the admin dashboard. CAD quotations should include any delivery charge before they are sent.

## Printing categories and prices

The public homepage describes digital printing and CAD plotting. A signed-in customer sees active orders only; cancelled and delivered orders are hidden from the customer dashboard. Customers use **New order** to open the separate order form. Digital printing displays a live total based on paper size, print mode, sheet count, and the admin-configured per-sheet rate. Delivery orders use the configured standard fee and start with the customer's registration address, which can be edited per order. CAD orders support A0, A1, A2, A4, or Custom; custom sizes require extra notes and are manually quoted. Each order receives a unique tracking ID.

The admin dashboard shows active orders. Digital and delivery rates are managed on a separate admin pricing screen at `/admin/prices/digital`. Delivered orders are in a separate archive filterable by customer ID and date range. Customer creation has its own admin screen. Homepage service photographs are stored locally in `static/` and sourced under the Unsplash License.

## Enable WhatsApp updates

The app uses the Meta WhatsApp Cloud API. Add a WhatsApp Business phone number, create an approved message template named `raju_printer_update` with two body placeholders (customer name and update text), then set these values in `.env`:

```dotenv
WHATSAPP_ACCESS_TOKEN=your-meta-access-token
WHATSAPP_PHONE_NUMBER_ID=your-business-phone-number-id
WHATSAPP_ADMIN_NUMBER=+919876543210
WHATSAPP_TEMPLATE_NAME=raju_printer_update
WHATSAPP_TEMPLATE_LANGUAGE=en_US
```

Customer phone numbers use international format, for example `+919876543210`. Customers enter their number and opt in during registration; admins also collect both when creating an account. If the Meta credentials are missing or the API call fails, orders and payments still complete; notification failures are written to the app log.

## Before production

- Set a private `FLASK_SECRET_KEY` and keep `.env` out of source control.
- Set `RAJU_DEMO_MODE=false` and `FLASK_DEBUG=false` in `.env`. On the first startup, set `BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_PASSWORD` to create the initial administrator; clear the password variable after that account exists.
- Run behind a production WSGI server and HTTPS.
- Configure MongoDB network access/backups and private persistent storage for `uploads/`; uploads contain customer documents.
- Review local retention, access, payment, and WhatsApp consent requirements for your business.

Supported uploads are multiple PDF, DOC, DOCX, JPG, and PNG documents, up to 20 MB total per order. Digital printing is estimated as the number of uploaded files multiplied by prints per file and the configured price per print, plus any delivery fee. Each file is listed and downloaded individually. Uploads are stored on the app server and are only downloadable by the order owner or an administrator.
