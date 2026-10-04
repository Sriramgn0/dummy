# Website

A Flask and MongoDB order portal for customer print requests, admin quotations, UPI payment confirmation, and delivery tracking.

## Run locally

1. Start MongoDB locally or create a MongoDB Atlas database.
2. Install dependencies in the project virtual environment:

   ```sh
   .venv/bin/python -m pip install -r requirements.txt
   ```

3. Configure MongoDB and a session secret, then start Flask:

   ```sh
   export MONGO_URI='mongodb://127.0.0.1:27017/'
   export FLASK_SECRET_KEY='replace-with-a-long-random-value'
   .venv/bin/python 1.py
   ```

4. Open <http://127.0.0.1:5000>.

For local testing, first run seeds two accounts when the database is empty for those usernames:

- Customer: `customer` / `Print123!`
- Admin: `admin` / `Admin123!`

Customers can create their own accounts from the home page, or the admin can create accounts from the dashboard. Set `DEMO_ADMIN_USERNAME`, `DEMO_ADMIN_PASSWORD`, `DEMO_CUSTOMER_USERNAME`, and `DEMO_CUSTOMER_PASSWORD` before the first run to choose different demo credentials. Public signup creates customer accounts only; email verification is not configured.

## UPI payments

Set the shop's receiving UPI ID before starting the app:

```sh
export RAJU_UPI_ID='sriramgn0-1@oksbi'
export RAJU_UPI_NAME='Raju Printer'
```

Customers can open an installed UPI app with the order amount and tracking ID prefilled, then report that they sent payment. Orders remain unpaid until an admin checks the shop account and marks the payment received. Configure the standard delivery fee with the digital rate card in the admin dashboard. CAD quotations should include any delivery charge before they are sent.

## Printing categories and prices

The public homepage describes digital printing and CAD plotting. A signed-in customer sees order history and uses **New order** to open the separate order form. Digital printing displays a live total based on paper size, print mode, sheet count, and the admin-configured per-sheet rate. Delivery orders use the configured standard fee and start with the customer's registration address, which can be edited per order. CAD orders support A0, A1, A2, A4, or Custom; custom sizes require extra notes and are manually quoted. Each order receives a unique tracking ID.

The admin dashboard shows active orders. Digital and delivery rates are managed on a separate admin pricing screen at `/admin/prices/digital`. Delivered orders are in a separate archive filterable by customer ID and date range. Customer creation has its own admin screen. Homepage service photographs are stored locally in `static/` and sourced under the Unsplash License.

## Enable WhatsApp updates

The app uses the Meta WhatsApp Cloud API. Add a WhatsApp Business phone number, create an approved message template named `raju_printer_update` with two body placeholders (customer name and update text), and set:

```sh
export WHATSAPP_ACCESS_TOKEN='your-meta-access-token'
export WHATSAPP_PHONE_NUMBER_ID='your-business-phone-number-id'
export WHATSAPP_ADMIN_NUMBER='+919876543210'
export WHATSAPP_TEMPLATE_NAME='raju_printer_update'
export WHATSAPP_TEMPLATE_LANGUAGE='en_US'
```

Customer phone numbers use international format, for example `+919876543210`. Customers enter their number and opt in during registration; admins also collect both when creating an account. If the Meta credentials are missing or the API call fails, orders and payments still complete; notification failures are written to the app log.

## Before production

- Set `FLASK_SECRET_KEY` to a private random value and keep MongoDB/UPI/WhatsApp secrets out of source control.
- Set `RAJU_DEMO_MODE=false` to disable demo account seeding. On the first startup, set `BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_PASSWORD` to create the initial administrator; remove the password variable after that account exists.
- Run with `FLASK_DEBUG=false` behind a production WSGI server and HTTPS.
- Configure MongoDB network access/backups and private persistent storage for `uploads/`; uploads contain customer documents.
- Review local retention, access, payment, and WhatsApp consent requirements for your business.

Supported uploads are PDF, DOC, DOCX, JPG, and PNG, up to 20 MB. Uploads are stored on the app server and are only downloadable by the order owner or an administrator.
