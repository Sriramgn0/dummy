import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from uuid import uuid4

import requests
from bson import ObjectId
from bson.errors import InvalidId
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from pymongo import DESCENDING, MongoClient
from pymongo.errors import PyMongoError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
UPLOAD_FOLDER = ROOT / "uploads"
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "jpg", "jpeg", "png"}
MAX_UPLOAD_SIZE = 20 * 1024 * 1024
DIGITAL_SIZES = ("A4", "A3", "A5", "Letter")
CAD_SIZES = ("A0", "A1", "A2", "A4", "Custom")
PRINT_TYPES = ("black_white", "color")
ORDER_STATUS_LABELS = {
    "pending_quote": "Awaiting quote",
    "awaiting_payment": "Payment due",
    "payment_submitted": "Payment sent · awaiting confirmation",
    "payment_submitted": "Payment sent · awaiting confirmation",
    "paid": "Paid",
    "confirmed": "Confirmed",
    "printing": "Printing",
    "ready_for_pickup": "Ready for pickup",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
}
FULFILLMENT_RANK = {
    "paid": 0,
    "confirmed": 1,
    "printing": 2,
    "ready_for_pickup": 3,
    "out_for_delivery": 4,
    "delivered": 5,
}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "local-development-key-change-me"),
    MONGO_URI=os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/"),
    MONGO_DATABASE=os.environ.get("MONGO_DATABASE", "raju_printer"),
    UPI_ID=os.environ.get("RAJU_UPI_ID", ""),
    UPI_PAYEE_NAME=os.environ.get("RAJU_UPI_NAME", "Raju Printer"),
    WHATSAPP_ACCESS_TOKEN=os.environ.get("WHATSAPP_ACCESS_TOKEN", ""),
    WHATSAPP_PHONE_NUMBER_ID=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
    WHATSAPP_ADMIN_NUMBER=os.environ.get("WHATSAPP_ADMIN_NUMBER", ""),
    WHATSAPP_TEMPLATE_NAME=os.environ.get("WHATSAPP_TEMPLATE_NAME", "raju_printer_update"),
    WHATSAPP_TEMPLATE_LANGUAGE=os.environ.get("WHATSAPP_TEMPLATE_LANGUAGE", "en_US"),
    WHATSAPP_API_VERSION=os.environ.get("WHATSAPP_API_VERSION", "v23.0"),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_SIZE,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RAJU_ENV", "").lower() == "production",
)
UPLOAD_FOLDER.mkdir(exist_ok=True)


def get_database():
    if "database" not in app.extensions:
        client = MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        database = client[app.config["MONGO_DATABASE"]]
        database.users.create_index("username", unique=True)
        database.orders.create_index([("user_id", 1), ("created_at", DESCENDING)])
        database.orders.create_index("status")
        database.digital_prices.create_index(
            [("service", 1), ("size", 1), ("print_type", 1)], unique=True
        )
        database.orders.create_index("tracking_id", unique=True, sparse=True)
        app.extensions["mongo_client"] = client
        app.extensions["database"] = database
        seed_initial_accounts(database)
    return app.extensions["database"]


def seed_initial_accounts(database):
    demo_mode = os.environ.get("RAJU_DEMO_MODE", "true").lower() == "true"
    admin_password = os.environ.get("DEMO_ADMIN_PASSWORD", "Admin123!") if demo_mode else os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    accounts = []
    if admin_password:
        accounts.append(
            {
                "username": os.environ.get(
                    "BOOTSTRAP_ADMIN_USERNAME",
                    os.environ.get("DEMO_ADMIN_USERNAME", "admin") if demo_mode else "admin",
                ).lower(),
                "name": "Raju Printer Admin",
                "password": admin_password,
                "role": "admin",
            }
        )
    if demo_mode:
        accounts.append(
            {
                "username": os.environ.get("DEMO_CUSTOMER_USERNAME", "customer").lower(),
                "name": "Demo Customer",
                "password": os.environ.get("DEMO_CUSTOMER_PASSWORD", "Print123!"),
                "role": "customer",
            }
        )
    for account in accounts:
        database.users.update_one(
            {"username": account["username"]},
            {
                "$setOnInsert": {
                    "username": account["username"],
                    "name": account["name"],
                    "password_hash": generate_password_hash(account["password"]),
                    "role": account["role"],
                    "whatsapp_number": os.environ.get("DEMO_CUSTOMER_WHATSAPP", "")
                    if account["role"] == "customer"
                    else "",
                    "created_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )


def normalize_whatsapp_number(value):
    number = re.sub(r"[\s().-]", "", value or "")
    return number if re.fullmatch(r"\+[1-9]\d{7,14}", number) else ""


def send_whatsapp(recipient, name, message):
    recipient = normalize_whatsapp_number(recipient)
    access_token = app.config["WHATSAPP_ACCESS_TOKEN"]
    phone_number_id = app.config["WHATSAPP_PHONE_NUMBER_ID"]
    if not recipient or not access_token or not phone_number_id:
        return False
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient[1:],
        "type": "template",
        "template": {
            "name": app.config["WHATSAPP_TEMPLATE_NAME"],
            "language": {"code": app.config["WHATSAPP_TEMPLATE_LANGUAGE"]},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": (name or "there")[:80]},
                        {"type": "text", "text": message[:900]},
                    ],
                }
            ],
        },
    }
    try:
        response = requests.post(
            f"https://graph.facebook.com/{app.config['WHATSAPP_API_VERSION']}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
            timeout=8,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as error:
        app.logger.warning("WhatsApp notification failed: %s", error)
        return False


def notify_customer(user_id, message):
    customer = get_database().users.find_one({"_id": user_id})
    if customer and customer.get("whatsapp_opt_in"):
        return send_whatsapp(customer.get("whatsapp_number", ""), customer.get("name"), message)
    return False


def notify_admin(message):
    return send_whatsapp(
        app.config["WHATSAPP_ADMIN_NUMBER"], "Raju Printer", message
    )


def order_update(status, note):
    return {"status": status, "note": note, "created_at": datetime.now(timezone.utc)}


app.jinja_env.filters["status_label"] = lambda status: ORDER_STATUS_LABELS.get(
    status, status.replace("_", " ").title()
)


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def protect_forms():
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        provided = request.form.get("csrf_token", "") or request.headers.get(
            "X-CSRF-Token", ""
        )
        if not expected or not hmac.compare_digest(expected, provided):
            abort(400, description="Your session expired. Refresh the page and try again.")


@app.context_processor
def inject_user():
    return {"current_user": g.get("user")}


@app.before_request
def load_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id:
        try:
            g.user = get_database().users.find_one({"_id": ObjectId(user_id)})
        except (PyMongoError, ValueError):
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def money(paise):
    return f"{(paise or 0) / 100:,.2f}"


def digital_price_map(database):
    prices = {
        size: {print_type: None for print_type in PRINT_TYPES}
        for size in DIGITAL_SIZES
    }
    for rate in database.digital_prices.find({"service": "digital_printing"}):
        if rate.get("size") in prices and rate.get("print_type") in PRINT_TYPES:
            prices[rate["size"]][rate["print_type"]] = rate["price_paise"]
    delivery = database.digital_prices.find_one(
        {"service": "delivery_fee", "size": "flat", "print_type": "all"}
    )
    prices["delivery_fee_paise"] = delivery.get("price_paise", 0) if delivery else 0
    return prices


def tracking_id_for(order_id):
    return f"RP-{datetime.now(timezone.utc):%y%m%d}-{str(order_id)[-8:].upper()}"


app.jinja_env.filters["money"] = money


def mongo_unavailable():
    return render_template("unavailable.html"), 503


@app.errorhandler(PyMongoError)
def handle_database_error(_error):
    return mongo_unavailable()


@app.errorhandler(413)
def upload_too_large(_error):
    flash("That file is over the 20 MB upload limit.", "error")
    return redirect(url_for("dashboard"))


@app.route("/", methods=["GET"])
def home():
    if g.user:
        return redirect(url_for("dashboard"))
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = get_database().users.find_one({"username": username})
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = str(user["_id"])
            session["csrf_token"] = secrets.token_urlsafe(32)
            return redirect(url_for("dashboard"))
        flash("That username and password do not match.", "error")
    demo_mode = os.environ.get("RAJU_DEMO_MODE", "true").lower() == "true"
    return render_template(
        "login.html",
        demo_mode=demo_mode,
        demo_admin_username=os.environ.get("DEMO_ADMIN_USERNAME", "admin"),
        demo_admin_password=os.environ.get("DEMO_ADMIN_PASSWORD", "Admin123!"),
        demo_customer_username=os.environ.get("DEMO_CUSTOMER_USERNAME", "customer"),
        demo_customer_password=os.environ.get("DEMO_CUSTOMER_PASSWORD", "Print123!"),
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("dashboard"))
    form_data = {
        "name": "",
        "username": "",
        "address": "",
        "whatsapp_number": "",
        "whatsapp_opt_in": False,
    }
    form_error = None
    response_status = 200
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        address = request.form.get("address", "").strip()
        whatsapp_number = request.form.get("whatsapp_number", "").strip()
        whatsapp_opt_in = request.form.get("whatsapp_opt_in") == "yes"
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        form_data.update(
            name=name,
            username=username,
            address=address,
            whatsapp_number=whatsapp_number,
            whatsapp_opt_in=whatsapp_opt_in,
        )

        if not name or len(name) > 100:
            form_error = "Enter your name (up to 100 characters)."
        elif not address or len(address) > 500:
            form_error = "Enter your delivery address (up to 500 characters)."
        elif not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,59}", username):
            form_error = "Username must be 3–60 characters and use letters, numbers, dots, dashes, or underscores."
        elif not normalize_whatsapp_number(whatsapp_number):
            form_error = "Enter a WhatsApp number with country code, such as +919876543210."
        elif not whatsapp_opt_in:
            form_error = "Please agree to receive order updates on WhatsApp."
        elif len(password) < 8:
            form_error = "Choose a password with at least 8 characters."
        elif password != password_confirm:
            form_error = "Those passwords do not match."

        if not form_error:
            database = get_database()
            if database.users.find_one({"username": username}):
                form_error = "That username is already in use. Try signing in instead."
                response_status = 409
            else:
                try:
                    result = database.users.insert_one(
                        {
                            "name": name,
                            "address": address,
                            "username": username,
                            "password_hash": generate_password_hash(password),
                            "role": "customer",
                            "whatsapp_number": normalize_whatsapp_number(whatsapp_number),
                            "whatsapp_opt_in": True,
                            "whatsapp_opted_in_at": datetime.now(timezone.utc),
                            "created_at": datetime.now(timezone.utc),
                        }
                    )
                except PyMongoError as error:
                    if getattr(error, "code", None) == 11000:
                        form_error = "That username is already in use. Try signing in instead."
                        response_status = 409
                    else:
                        raise
                else:
                    session.clear()
                    session["user_id"] = str(result.inserted_id)
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    return redirect(url_for("dashboard"))
    return render_template("signup.html", form_data=form_data, form_error=form_error), response_status


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    database = get_database()
    if g.user["role"] == "admin":
        active_statuses = [
            "pending_quote",
            "awaiting_payment",
            "payment_submitted",
            "paid",
            "confirmed",
            "printing",
            "ready_for_pickup",
            "out_for_delivery",
        ]
        orders = list(
            database.orders.find({"status": {"$in": active_statuses}})
            .sort("created_at", DESCENDING)
            .limit(100)
        )
        counts = {
            "open": database.orders.count_documents({"status": "pending_quote"}),
            "payment": database.orders.count_documents(
                {"status": {"$in": ["awaiting_payment", "payment_submitted"]}}
            ),
            "paid": database.orders.count_documents(
                {"status": {"$in": ["paid", "confirmed", "printing", "ready_for_pickup", "out_for_delivery"]}}
            ),
        }
        return render_template(
            "admin.html",
            orders=orders,
            counts=counts,
            digital_prices=digital_price_map(database),
            digital_sizes=DIGITAL_SIZES,
            print_types=PRINT_TYPES,
        )
    orders = list(
        database.orders.find({"user_id": g.user["_id"]}).sort("created_at", DESCENDING)
    )
    return render_template(
        "customer.html",
        orders=orders,
        upi_id=app.config["UPI_ID"],
        upi_payee_name=app.config["UPI_PAYEE_NAME"],
    )


@app.get("/admin/orders/completed")
@admin_required
def completed_orders():
    database = get_database()
    query = {"status": "delivered"}
    customer_id = request.args.get("customer_id", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    try:
        if customer_id:
            query["user_id"] = ObjectId(customer_id)
        if start_date:
            start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            query.setdefault("created_at", {})["$gte"] = start
        if end_date:
            end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            query.setdefault("created_at", {})["$lt"] = end + timedelta(days=1)
    except (InvalidId, ValueError, TypeError):
        abort(400, description="Choose a valid customer and date range.")
    orders = list(database.orders.find(query).sort("created_at", DESCENDING).limit(500))
    customers = list(
        database.users.find({"role": "customer"}, {"password_hash": 0}).sort("name", 1)
    )
    return render_template(
        "completed_orders.html",
        orders=orders,
        customers=customers,
        selected_customer=customer_id,
        start_date=start_date,
        end_date=end_date,
    )


@app.get("/admin/prices/digital")
@admin_required
def digital_prices():
    return render_template(
        "digital_prices.html",
        digital_prices=digital_price_map(get_database()),
        digital_sizes=DIGITAL_SIZES,
        print_types=PRINT_TYPES,
    )


@app.get("/orders/new")
@login_required
def new_order():
    if g.user["role"] != "customer":
        abort(403)
    return render_template(
        "order_new.html",
        digital_prices=digital_price_map(get_database()),
        customer_address=g.user.get("address", ""),
    )


@app.post("/orders")
@login_required
def create_order():
    if g.user["role"] != "customer":
        abort(403)
    uploaded = request.files.get("document")
    if not uploaded or not uploaded.filename:
        flash("Choose a document to print.", "error")
        return redirect(url_for("new_order"))
    original_name = secure_filename(uploaded.filename)
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if extension not in ALLOWED_EXTENSIONS:
        flash("Upload a PDF, Word document, JPG, or PNG file.", "error")
        return redirect(url_for("new_order"))
    try:
        copies = int(request.form.get("copies", "1"))
    except ValueError:
        copies = 0
    if not 1 <= copies <= 1000:
        flash("Copies must be a number between 1 and 1,000.", "error")
        return redirect(url_for("new_order"))

    category = request.form.get("product_category", "digital_printing")
    if category not in {"digital_printing", "cad"}:
        flash("Choose digital printing or CAD printing.", "error")
        return redirect(url_for("new_order"))
    database = get_database()
    delivery_type = request.form.get("delivery_type", "pickup")
    if delivery_type not in {"pickup", "delivery"}:
        flash("Choose pickup or delivery.", "error")
        return redirect(url_for("new_order"))
    notes = request.form.get("notes", "").strip()[:500]
    if delivery_type == "delivery":
        delivery_address = request.form.get("delivery_address", "").strip()[:500]
        if not delivery_address:
            flash("Enter the address for this delivery.", "error")
            return redirect(url_for("new_order"))
    else:
        delivery_address = ""
    delivery_fee_paise = (
        digital_price_map(database).get("delivery_fee_paise", 0)
        if delivery_type == "delivery"
        else 0
    )
    if category == "digital_printing":
        paper_size = request.form.get("paper_size", "")
        print_type = request.form.get("print_type", "")
        if paper_size not in DIGITAL_SIZES or print_type not in PRINT_TYPES:
            flash("Choose a valid digital print size and print mode.", "error")
            return redirect(url_for("new_order"))
        rate = database.digital_prices.find_one(
            {
                "service": "digital_printing",
                "size": paper_size,
                "print_type": print_type,
            }
        )
        if not rate or rate.get("price_paise", 0) <= 0:
            flash("Digital printing is not priced for that size and mode yet.", "error")
            return redirect(url_for("new_order"))
        price_each_paise = rate["price_paise"]
        quote_paise = price_each_paise * copies + delivery_fee_paise
        status = "awaiting_payment"
        print_label = "colour" if print_type == "color" else "black-and-white"
        initial_update = order_update(
            status,
            f"Digital printing estimate: ₹{quote_paise / 100:,.2f} ({copies} sheets at ₹{price_each_paise / 100:,.2f} each)."
            + (f" Includes ₹{delivery_fee_paise / 100:,.2f} delivery." if delivery_fee_paise else ""),
        )
    else:
        paper_size = request.form.get("cad_size", "")
        if paper_size not in CAD_SIZES:
            flash("Choose a valid CAD drawing size.", "error")
            return redirect(url_for("new_order"))
        if paper_size == "Custom" and not notes:
            flash("Add the required extra notes for a custom CAD size.", "error")
            return redirect(url_for("new_order"))
        print_type = "cad"
        price_each_paise = None
        quote_paise = None
        status = "pending_quote"
        print_label = "CAD"
        initial_update = order_update(
            status,
            "CAD order received. Waiting for a quotation, including any delivery charges."
            if delivery_type == "delivery"
            else "CAD order received. Waiting for a quotation.",
        )

    order_id = ObjectId()
    order_tracking_id = tracking_id_for(order_id)
    stored_name = f"{order_tracking_id}.{extension}"
    display_name = f"{order_tracking_id}_{original_name}"
    uploaded.save(UPLOAD_FOLDER / stored_name)
    order = {
        "_id": order_id,
        "tracking_id": order_tracking_id,
        "user_id": g.user["_id"],
        "customer_name": g.user["name"],
        "document_name": original_name,
        "display_name": display_name,
        "stored_name": stored_name,
        "copies": copies,
        "product_category": category,
        "print_type": print_type,
        "paper_size": paper_size,
        "price_each_paise": price_each_paise,
        "delivery_type": delivery_type,
        "delivery_address": delivery_address,
        "delivery_fee_paise": delivery_fee_paise,
        "notes": notes,
        "created_at": datetime.now(timezone.utc),
        "status": status,
        "updates": [initial_update],
        "quote_paise": quote_paise,
        "payment_method": "upi",
        "payment_reference": None,
    }
    try:
        get_database().orders.insert_one(order)
    except PyMongoError:
        (UPLOAD_FOLDER / stored_name).unlink(missing_ok=True)
        raise
    notify_admin(
        f"New {print_label} order {order_tracking_id} from {g.user['name']}: {copies} sheets of {original_name}, size {paper_size}, {delivery_type}."
    )
    flash("Raju Printer will review your document and send you a quotation.", "order-sent")
    return redirect(url_for("dashboard"))


@app.post("/admin/orders/<order_id>/quote")
@admin_required
def update_quote(order_id):
    try:
        quote = Decimal(request.form.get("amount", "")).quantize(Decimal("0.01"))
        quote_paise = int(quote * 100)
    except (InvalidOperation, ValueError):
        quote_paise = 0
    if quote_paise <= 0:
        flash("Enter a quotation greater than zero.", "error")
        return redirect(url_for("dashboard"))
    database = get_database()
    query = {
        "_id": ObjectId(order_id),
        "product_category": {"$ne": "digital_printing"},
        "status": {"$in": ["pending_quote", "awaiting_payment"]},
    }
    timestamp = datetime.now(timezone.utc)
    order = database.orders.find_one(query)
    if not order:
        abort(404)
    result = database.orders.update_one(
        query,
        {
            "$set": {
                "quote_paise": quote_paise,
                "status": "awaiting_payment",
                "quoted_at": timestamp,
            },
            "$push": {
                "updates": order_update(
                    "awaiting_payment", f"Quotation ready: ₹{quote_paise / 100:,.2f}."
                )
            },
        },
    )
    if not result.matched_count:
        abort(409)
    notify_customer(
        order["user_id"],
        f"Your print order {order.get('tracking_id', order['_id'])} has a quotation of ₹{quote_paise / 100:,.2f}. Sign in to pay by UPI.",
    )
    flash("Quotation updated. The customer can now pay by UPI.", "success")
    return redirect(url_for("dashboard"))


@app.post("/admin/prices/digital")
@admin_required
def update_digital_prices():
    updates = []
    raw_delivery_fee = request.form.get("delivery_fee", "").strip()
    delivery_fee = None
    if raw_delivery_fee:
        try:
            delivery_fee = int(Decimal(raw_delivery_fee).quantize(Decimal("0.01")) * 100)
        except (InvalidOperation, ValueError):
            delivery_fee = -1
        if delivery_fee < 0:
            flash("Enter a valid delivery fee of zero or more.", "error")
            return redirect(url_for("digital_prices"))
    for size in DIGITAL_SIZES:
        for print_type in PRINT_TYPES:
            field_name = f"rate_{size}_{print_type}"
            raw_rate = request.form.get(field_name, "").strip()
            price_paise = None
            if raw_rate:
                try:
                    amount = Decimal(raw_rate).quantize(Decimal("0.01"))
                    price_paise = int(amount * 100)
                except (InvalidOperation, ValueError):
                    price_paise = 0
                if price_paise <= 0:
                    flash("Enter a valid per-sheet price greater than zero, or leave it blank to remove a rate.", "error")
                    return redirect(url_for("digital_prices"))
            updates.append((size, print_type, price_paise))

    database = get_database()
    timestamp = datetime.now(timezone.utc)
    for size, print_type, price_paise in updates:
        query = {"service": "digital_printing", "size": size, "print_type": print_type}
        if price_paise is None:
            database.digital_prices.delete_one(query)
        else:
            database.digital_prices.update_one(
                query,
                {
                    "$set": {
                        **query,
                        "price_paise": price_paise,
                        "updated_at": timestamp,
                        "updated_by": g.user["_id"],
                    }
                },
                upsert=True,
            )
    delivery_query = {
        "service": "delivery_fee",
        "size": "flat",
        "print_type": "all",
    }
    if delivery_fee is None:
        database.digital_prices.delete_one(delivery_query)
    else:
        database.digital_prices.update_one(
            delivery_query,
            {"$set": {**delivery_query, "price_paise": delivery_fee, "updated_at": timestamp}},
            upsert=True,
        )
    flash("Digital printing prices saved.", "success")
    return redirect(url_for("digital_prices"))


@app.post("/admin/customers")
@admin_required
def create_customer():
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    address = request.form.get("address", "").strip()
    password = request.form.get("password", "")
    whatsapp_number = normalize_whatsapp_number(request.form.get("whatsapp_number", ""))
    whatsapp_opt_in = request.form.get("whatsapp_opt_in") == "yes"
    if not name or not username or len(password) < 8 or not address or not whatsapp_number or not whatsapp_opt_in:
        flash("Add the customer name, address, WhatsApp number, password, and notification consent.", "error")
        return redirect(url_for("new_customer"))
    try:
        get_database().users.insert_one(
            {
                "name": name[:100],
                "username": username[:60],
                "address": address[:500],
                "password_hash": generate_password_hash(password),
                "role": "customer",
                "whatsapp_number": whatsapp_number,
                "whatsapp_opt_in": True,
                "whatsapp_opted_in_at": datetime.now(timezone.utc),
                "created_at": datetime.now(timezone.utc),
            }
        )
    except PyMongoError as error:
        if error.code == 11000:
            flash("That username is already in use.", "error")
            return redirect(url_for("new_customer"))
        raise
    flash(f"Login created for {name}.", "success")
    return redirect(url_for("new_customer"))


@app.get("/admin/customers/new")
@admin_required
def new_customer():
    return render_template("customer_new.html")


@app.post("/admin/orders/<order_id>/updates")
@admin_required
def add_order_update(order_id):
    database = get_database()
    order = database.orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        abort(404)
    current_status = order["status"]
    next_status = request.form.get("status", current_status)
    note = request.form.get("note", "").strip()[:500]
    if current_status not in FULFILLMENT_RANK or next_status not in FULFILLMENT_RANK:
        flash("Fulfillment updates are available after payment.", "error")
        return redirect(url_for("dashboard"))
    if FULFILLMENT_RANK[next_status] < FULFILLMENT_RANK[current_status]:
        flash("Order status cannot move backwards.", "error")
        return redirect(url_for("dashboard"))
    if not note:
        note = f"Order status updated to {ORDER_STATUS_LABELS[next_status].lower()}."
    result = database.orders.update_one(
        {"_id": order["_id"], "status": current_status},
        {
            "$set": {"status": next_status},
            "$push": {"updates": order_update(next_status, note)},
        },
    )
    if not result.matched_count:
        abort(409)
    notify_customer(
        order["user_id"],
        f"Update for order {order.get('tracking_id', order['_id'])}: {ORDER_STATUS_LABELS[next_status]}. {note}",
    )
    flash("Order update posted and customer notified.", "success")
    return redirect(url_for("dashboard"))


@app.post("/orders/<order_id>/cancel")
@login_required
def cancel_order(order_id):
    if g.user["role"] != "customer":
        abort(403)
    database = get_database()
    query = {
        "_id": ObjectId(order_id),
        "user_id": g.user["_id"],
        "status": {"$in": ["pending_quote", "awaiting_payment"]},
    }
    order = database.orders.find_one(query)
    if not order:
        flash("This order can no longer be cancelled.", "error")
        return redirect(url_for("dashboard"))
    note = "Cancelled by customer before payment."
    result = database.orders.update_one(
        query,
        {
            "$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc)},
            "$push": {"updates": order_update("cancelled", note)},
        },
    )
    if not result.matched_count:
        flash("This order can no longer be cancelled.", "error")
        return redirect(url_for("dashboard"))
    notify_admin(
        f"Order {order.get('tracking_id', order['_id'])} from {g.user['name']} was cancelled before payment."
    )
    flash("Your order was cancelled.", "success")
    return redirect(url_for("dashboard"))


@app.get("/orders/<order_id>/document")
@login_required
def download_document(order_id):
    order = get_database().orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        abort(404)
    if g.user["role"] != "admin" and order["user_id"] != g.user["_id"]:
        abort(403)
    return send_from_directory(
        UPLOAD_FOLDER,
        order["stored_name"],
        as_attachment=True,
        download_name=order.get("display_name", order["document_name"]),
    )


@app.post("/orders/<order_id>/payment-submitted")
@login_required
def submit_upi_payment(order_id):
    if g.user["role"] != "customer":
        abort(403)
    database = get_database()
    order = database.orders.find_one({
        "_id": ObjectId(order_id),
        "user_id": g.user["_id"],
        "status": "awaiting_payment",
    })
    if not order:
        abort(404)
    payment_reference = request.form.get("payment_reference", "").strip()[:100]
    note = "Customer reports UPI payment sent; awaiting admin confirmation."
    if payment_reference:
        note += f" Reference: {payment_reference}."
    result = database.orders.update_one(
        {"_id": order["_id"], "status": "awaiting_payment"},
        {
            "$set": {
                "status": "payment_submitted",
                "payment_method": "upi",
                "payment_reference": payment_reference or None,
                "payment_submitted_at": datetime.now(timezone.utc),
            },
            "$push": {"updates": order_update("payment_submitted", note)},
        },
    )
    if not result.matched_count:
        abort(409)
    notify_admin(
        f"UPI payment reported for {order.get('tracking_id', order['_id'])} by {g.user['name']}: ₹{order['quote_paise'] / 100:,.2f}. Confirm receipt in the admin dashboard."
    )
    flash("Payment reported. Raju Printer will confirm it before processing your order.", "success")
    return redirect(url_for("dashboard"))


@app.post("/admin/orders/<order_id>/confirm-payment")
@admin_required
def confirm_upi_payment(order_id):
    database = get_database()
    order = database.orders.find_one({"_id": ObjectId(order_id), "status": "payment_submitted"})
    if not order:
        abort(404)
    result = database.orders.update_one(
        {"_id": order["_id"], "status": "payment_submitted"},
        {
            "$set": {
                "status": "paid",
                "paid_at": datetime.now(timezone.utc),
                "payment_confirmed_by": g.user["_id"],
            },
            "$push": {"updates": order_update("paid", "UPI payment received and confirmed by Raju Printer.")},
        },
    )
    if not result.matched_count:
        abort(409)
    notify_customer(
        order["user_id"],
        f"UPI payment for {order.get('tracking_id', order['_id'])} is confirmed. Your order is now being processed.",
    )
    flash("UPI payment confirmed. The order is now in processing.", "success")
    return redirect(url_for("dashboard"))


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=error.description), 400


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You do not have access to this page."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="We couldn't find that page or order."), 404


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "true").lower() == "true")