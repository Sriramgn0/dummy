import hmac
import hashlib
import io
import os
import re
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from xml.sax.saxutils import escape
import certifi
import requests
from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from pymongo import DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import PyMongoError
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A6, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

UPLOAD_FOLDER = Path(os.environ.get("UPLOAD_FOLDER", "uploads"))
if not UPLOAD_FOLDER.is_absolute():
    UPLOAD_FOLDER = ROOT / UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {
    extension.strip().lower()
    for extension in os.environ.get(
        "ALLOWED_EXTENSIONS", "pdf,doc,docx,jpg,jpeg,png"
    ).split(",")
    if extension.strip()
}
try:
    MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "20")) * 1024 * 1024
except ValueError as error:
    raise RuntimeError("MAX_UPLOAD_SIZE_MB must be a positive integer.") from error
if MAX_UPLOAD_SIZE < 1 or not ALLOWED_EXTENSIONS:
    raise RuntimeError(
        "MAX_UPLOAD_SIZE_MB must be positive and ALLOWED_EXTENSIONS cannot be empty."
    )
DIGITAL_SIZES = (
    "A4",
    "A3",
    "A5",
    "Letter",
    "4 x 6 inches (10.2 x 15.2 cm)",
    "5 x 7 inches (12.7 x 17.8 cm)",
    "8 x 10 inches (20.3 x 25.4 cm)",
    "8.5 x 11 inches (21.6 x 27.9 cm)",
    "11 x 14 inches (27.9 x 35.6 cm)",
    "12 x 18 inches (30.5 x 45.7 cm)",
    "18 x 24 inches (45.7 x 61.0 cm)",
    "24 x 36 inches (61.0 x 91.4 cm)",
)

DIGITAL_SIZE_DESCRIPTIONS = {
    "A4": "Standard A4 paper size.",
    "A3": "Standard A3 paper size.",
    "A5": "Standard A5 paper size.",
    "Letter": "Standard US Letter paper size.",
    "4 x 6 inches (10.2 x 15.2 cm)": (
        "3:2 ratio; best for postcards, small frames, and standard photos. "
        "Recommended: 1200 x 1800 px at 300 DPI."
    ),
    "5 x 7 inches (12.7 x 17.8 cm)": (
        "Great for portrait photography and smaller displays. "
        "Recommended: 1500 x 2100 px at 300 DPI."
    ),
    "8 x 10 inches (20.3 x 25.4 cm)": (
        "4:5 ratio; classic size for framed home artwork."
    ),
    "8.5 x 11 inches (21.6 x 27.9 cm)": (
        "Standard US Letter / small poster size."
    ),
    "11 x 14 inches (27.9 x 35.6 cm)": (
        "Popular standalone gallery and gift print size."
    ),
    "12 x 18 inches (30.5 x 45.7 cm)": "2:3 ratio; medium poster print.",
    "18 x 24 inches (45.7 x 61.0 cm)": "3:4 ratio; large statement wall art.",
    "24 x 36 inches (61.0 x 91.4 cm)": (
        "2:3 ratio; extra-large poster size. "
        "Recommended: 7200 x 10800 px at 300 DPI."
    ),
}
CAD_SIZES = ("A0", "A1", "A2", "A3", "A4", "Custom")
CAD_PAPER_TYPES = (
    "Plain Paper 100GSM",
    "Tracing Paper",
    "Blueprint Paper",
    "Glossy Paper",
)
PRINT_TYPES = ("black_white", "color")
PRINT_SIDES = ("front_only", "front_back")
ORDER_STATUS_LABELS = {
    "pending_quote": "Awaiting quote",
    "awaiting_payment": "Payment due",
    "paid": "Paid",
    "confirmed": "Confirmed",
    "payment_submitted": "Payment sent · awaiting confirmation",
    "printing": "Printing",
    "work_in_progress": "Work in progress",
    "ready_for_pickup": "Ready for pickup",
    "out_for_delivery": "Dispatched",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
    "rejected": "Rejected by admin",
}
FULFILLMENT_RANK = {
    "awaiting_payment": -2,
    "payment_submitted": -1,
    "paid": 0,
    "confirmed": 1,
    "printing": 2,
    "work_in_progress": 2,
    "ready_for_pickup": 3,
    "out_for_delivery": 4,
    "delivered": 5,
}
HTTPS_CERTIFICATE = os.environ.get("HTTPS_CERTIFICATE", "")
HTTPS_PRIVATE_KEY = os.environ.get("HTTPS_PRIVATE_KEY", "")
if bool(HTTPS_CERTIFICATE) != bool(HTTPS_PRIVATE_KEY):
    raise RuntimeError("Set both HTTPS_CERTIFICATE and HTTPS_PRIVATE_KEY to enable HTTPS.")
try:
    SESSION_IDLE_TIMEOUT_MINUTES = int(os.environ.get("SESSION_IDLE_TIMEOUT_MINUTES", "30"))
except ValueError as error:
    raise RuntimeError("SESSION_IDLE_TIMEOUT_MINUTES must be a positive integer.") from error
if SESSION_IDLE_TIMEOUT_MINUTES < 1:
    raise RuntimeError("SESSION_IDLE_TIMEOUT_MINUTES must be at least 1.")

RAJU_ENV = os.environ.get("RAJU_ENV", "development").lower()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", ""),
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=SESSION_IDLE_TIMEOUT_MINUTES),
    MONGO_URI=os.environ.get("MONGO_URI", "").strip(),
    MONGO_DATABASE=os.environ.get("MONGO_DATABASE", "raju_printer"),
    UPI_ID=os.environ.get("RAJU_UPI_ID", ""),
    UPI_PAYEE_NAME=os.environ.get("RAJU_UPI_NAME", "CAD Master"),
    BILLING_BUSINESS_NAME=os.environ.get("BILLING_BUSINESS_NAME", "CAD Master").strip(),
    BILLING_GSTIN=os.environ.get("BILLING_GSTIN", "").strip(),
    BILLING_PHONE=os.environ.get("BILLING_PHONE", "").strip(),
    BILLING_EMAIL=os.environ.get("BILLING_EMAIL", "").strip(),
    BILLING_ADDRESS=os.environ.get("BILLING_ADDRESS", "").strip(),
    BILLING_STATE=os.environ.get("BILLING_STATE", "").strip(),
    BILLING_INVOICE_PREFIX=os.environ.get("BILLING_INVOICE_PREFIX", "CM").strip() or "CM",
    RAJU_ENV=RAJU_ENV,
    FLASK_DEBUG=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
    RAJU_DEMO_MODE=os.environ.get("RAJU_DEMO_MODE", "false").lower() == "true",
    DEMO_ADMIN_USERNAME=os.environ.get("DEMO_ADMIN_USERNAME", "admin"),
    DEMO_ADMIN_PASSWORD=os.environ.get("DEMO_ADMIN_PASSWORD", ""),
    DEMO_CUSTOMER_USERNAME=os.environ.get("DEMO_CUSTOMER_USERNAME", "customer"),
    DEMO_CUSTOMER_PASSWORD=os.environ.get("DEMO_CUSTOMER_PASSWORD", ""),
    BOOTSTRAP_ADMIN_USERNAME=os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "admin"),
    BOOTSTRAP_ADMIN_PASSWORD=os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", ""),
    DEMO_CUSTOMER_WHATSAPP=os.environ.get("DEMO_CUSTOMER_WHATSAPP", ""),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_SIZE,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        RAJU_ENV == "production"
        or bool(HTTPS_CERTIFICATE and HTTPS_PRIVATE_KEY)
    ),
    WHATSAPP_ACCESS_TOKEN=os.environ.get("WHATSAPP_ACCESS_TOKEN", ""),
    WHATSAPP_PHONE_NUMBER_ID=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
    WHATSAPP_ADMIN_NUMBER=os.environ.get("WHATSAPP_ADMIN_NUMBER", ""),
    WHATSAPP_TEMPLATE_NAME=os.environ.get("WHATSAPP_TEMPLATE_NAME", "raju_printer_update"),
    WHATSAPP_TEMPLATE_LANGUAGE=os.environ.get("WHATSAPP_TEMPLATE_LANGUAGE", "en_US"),
    WHATSAPP_API_VERSION=os.environ.get("WHATSAPP_API_VERSION", "v23.0"),
    TWILIO_ACCOUNT_SID=os.environ.get("TWILIO_ACCOUNT_SID", "").strip(),
    TWILIO_AUTH_TOKEN=os.environ.get("TWILIO_AUTH_TOKEN", "").strip(),
    TWILIO_VERIFY_SERVICE_SID=os.environ.get("TWILIO_VERIFY_SERVICE_SID", "").strip(),
    SMS_AUTHENTICATION_ENABLED=os.environ.get(
        "SMS_AUTHENTICATION_ENABLED", "true"
    ).strip().lower() in {"1", "true", "yes", "on"},
)
if not app.config["SECRET_KEY"]:
    raise RuntimeError("FLASK_SECRET_KEY must be set in the environment or .env file.")
UPLOAD_FOLDER.mkdir(exist_ok=True)


def get_database():
    if "database" not in app.extensions:
        mongo_uri = app.config["MONGO_URI"]
        if not mongo_uri:
            raise RuntimeError(
                "MONGO_URI is not configured. Set it to the connection string "
                "copied from your MongoDB Atlas cluster."
            )
        client = None
        try:
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=10000, tlsCAFile=certifi.where())
            client.admin.command("ping")
            database = client[app.config["MONGO_DATABASE"]]
            database.users.create_index("username", unique=True)
            database.orders.create_index([("user_id", 1), ("created_at", DESCENDING)])
            database.orders.create_index("status")
            legacy_price_index_keys = [
                ("service", 1),
                ("size", 1),
                ("print_type", 1),
            ]
            for index_name, index in database.digital_prices.index_information().items():
                if (
                    index_name != "_id_"
                    and index.get("unique")
                    and index.get("key") == legacy_price_index_keys
                ):
                    database.digital_prices.drop_index(index_name)
            database.digital_prices.update_many(
                {
                    "service": "digital_printing",
                    "print_sides": {"$exists": False},
                },
                {"$set": {"print_sides": "front_only"}},
            )
            database.digital_prices.create_index(
                [
                    ("service", 1),
                    ("size", 1),
                    ("print_type", 1),
                    ("print_sides", 1),
                ],
                unique=True,
            )
            database.orders.create_index("tracking_id", unique=True, sparse=True)
            database.orders.create_index("invoice_number", unique=True, sparse=True)
            database.orders.create_index("invoice_generated_at")
            database.login_sessions.create_index([("user_id", 1), ("created_at", DESCENDING)])
            database.login_sessions.create_index("expires_at", expireAfterSeconds=0)
            database.auth_challenges.create_index("expires_at", expireAfterSeconds=0)
        except PyMongoError as error:
            if client is not None:
                client.close()
            app.logger.error(
                "MongoDB connection/setup failed (%s). Check the Atlas URI and "
                "database credentials, the Atlas IP access list, and DNS/network access.",
                type(error).__name__,
            )
            raise
        app.extensions["mongo_client"] = client
        app.extensions["database"] = database
    return app.extensions["database"]


def seed_initial_accounts(database):
    demo_mode = app.config["RAJU_DEMO_MODE"]
    admin_password = (
        app.config["DEMO_ADMIN_PASSWORD"]
        if demo_mode
        else app.config["BOOTSTRAP_ADMIN_PASSWORD"]
    )
    accounts = []
    if admin_password:
        accounts.append(
            {
                "username": (
                    app.config["DEMO_ADMIN_USERNAME"]
                    if demo_mode
                    else app.config["BOOTSTRAP_ADMIN_USERNAME"]
                ).lower(),
                "name": "CAD Master Admin",
                "password": admin_password,
                "role": "admin",
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
                    "whatsapp_number": app.config["DEMO_CUSTOMER_WHATSAPP"]
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


AUTH_CHALLENGE_TTL = timedelta(minutes=10)
AUTH_CODE_PATTERN = re.compile(r"\d{4,10}")


def twilio_verify_request(action, phone_number, code=None):
    account_sid = app.config["TWILIO_ACCOUNT_SID"]
    auth_token = app.config["TWILIO_AUTH_TOKEN"]
    service_sid = app.config["TWILIO_VERIFY_SERVICE_SID"]
    if not account_sid or not auth_token or not service_sid:
        raise RuntimeError("Twilio Verify is not configured.")

    endpoint = (
        "Verifications"
        if action == "send"
        else "VerificationCheck"
    )
    url = (
        f"https://verify.twilio.com/v2/Services/{service_sid}/{endpoint}"
    )
    payload = {"To": phone_number}
    if action == "send":
        payload["Channel"] = "sms"
    else:
        payload["Code"] = code

    try:
        response = requests.post(
            url,
            data=payload,
            auth=(account_sid, auth_token),
            timeout=10,
        )
    except requests.RequestException as error:
        app.logger.warning(
            "Twilio Verify request failed (%s).", type(error).__name__
        )
        raise RuntimeError("SMS verification is temporarily unavailable.") from error

    if action == "check" and response.status_code == 404:
        return False
    try:
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as error:
        app.logger.warning(
            "Twilio Verify returned an unusable response (%s).",
            type(error).__name__,
        )
        raise RuntimeError("SMS verification is temporarily unavailable.") from error
    return action == "send" or result.get("status") == "approved"


def create_auth_challenge(purpose, phone_number, send_sms=True, **fields):
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    challenge = {
        "_id": hashlib.sha256(token.encode()).hexdigest(),
        "purpose": purpose,
        "phone_number": phone_number,
        "created_at": now,
        "last_sent_at": now,
        "expires_at": now + AUTH_CHALLENGE_TTL,
        "attempt_count": 0,
        "resend_count": 0,
        **fields,
    }
    get_database().auth_challenges.insert_one(challenge)
    if send_sms:
        try:
            twilio_verify_request("send", phone_number)
        except RuntimeError:
            get_database().auth_challenges.delete_one({"_id": challenge["_id"]})
            raise
    session["auth_challenge"] = token
    return challenge


def current_auth_challenge(purpose=None):
    token = session.get("auth_challenge", "")
    if not token:
        return None
    query = {
        "_id": hashlib.sha256(token.encode()).hexdigest(),
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    }
    if purpose:
        query["purpose"] = purpose
    return get_database().auth_challenges.find_one(query)


def masked_phone_number(phone_number):
    return f"{phone_number[:3]}{'•' * max(0, len(phone_number) - 7)}{phone_number[-4:]}"


def send_whatsapp(recipient, name, message):
    recipient = normalize_whatsapp_number(recipient)
    access_token = app.config["WHATSAPP_ACCESS_TOKEN"]
    phone_number_id = app.config["WHATSAPP_PHONE_NUMBER_ID"]
    if not recipient:
        app.logger.warning(
            "WhatsApp notification skipped: recipient number is missing or invalid."
        )
        return False
    if not access_token or not phone_number_id:
        app.logger.warning(
            "WhatsApp notification skipped: configure WHATSAPP_ACCESS_TOKEN and "
            "WHATSAPP_PHONE_NUMBER_ID."
        )
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
        app.config["WHATSAPP_ADMIN_NUMBER"], "CAD Master", message
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
    return {
        "current_user": g.get("user"),
        "sms_authentication_enabled": app.config["SMS_AUTHENTICATION_ENABLED"],
    }


@app.before_request
def load_user():
    user_id = session.get("user_id")
    login_session_id = session.get("login_session_id")
    g.user = None
    if not user_id:
        return
    if not login_session_id:
        session.clear()
        return
    try:
        user_object_id = ObjectId(user_id)
    except (InvalidId, TypeError):
        session.clear()
        return

    now = datetime.now(timezone.utc)
    database = get_database()
    session_filter = {
        "user_id": user_object_id,
        "session_hash": hashlib.sha256(login_session_id.encode()).hexdigest(),
        "revoked_at": None,
        "expires_at": {"$gt": now},
    }
    login_session = database.login_sessions.find_one(session_filter)
    if not login_session:
        session.clear()
        return

    expires_at = now + app.config["PERMANENT_SESSION_LIFETIME"]
    refreshed = database.login_sessions.update_one(
        {**session_filter, "_id": login_session["_id"]},
        {"$set": {"last_seen_at": now, "expires_at": expires_at}},
    )
    if not refreshed.matched_count:
        session.clear()
        return

    session.permanent = True
    g.user = database.users.find_one({"_id": user_object_id})
    if not g.user:
        database.login_sessions.update_one(
            {"_id": login_session["_id"], "revoked_at": None},
            {"$set": {"revoked_at": now}},
        )
        session.clear()


def start_login_session(user_id):
    login_session_id = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + app.config["PERMANENT_SESSION_LIFETIME"]
    get_database().login_sessions.insert_one(
        {
            "user_id": user_id,
            "session_hash": hashlib.sha256(login_session_id.encode()).hexdigest(),
            "user_agent": request.user_agent.string[:300],
            "created_at": now,
            "last_seen_at": now,
            "expires_at": expires_at,
            "revoked_at": None,
        }
    )
    session.clear()
    session.permanent = True
    session["user_id"] = str(user_id)
    session["login_session_id"] = login_session_id
    session["csrf_token"] = secrets.token_urlsafe(32)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            return redirect(
                url_for("login", next=request.full_path.rstrip("?"))
            )
        return view(*args, **kwargs)

    return wrapped


def landing_endpoint(user):
    return "new_order" if user["role"] == "customer" else "dashboard"


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


def customer_addresses(user):
    addresses = list(user.get("addresses", []))
    legacy_address = user.get("address", "").strip()
    if legacy_address and legacy_address not in addresses:
        addresses.insert(0, legacy_address)
    return addresses


def digital_price_map(database):
    prices = {
        size: {
            print_type: {print_sides: None for print_sides in PRINT_SIDES}
            for print_type in PRINT_TYPES
        }
        for size in DIGITAL_SIZES
    }
    for rate in database.digital_prices.find({"service": "digital_printing"}):
        if rate.get("size") in prices and rate.get("print_type") in PRINT_TYPES:
            print_sides = rate.get("print_sides", "front_only")
            if print_sides in PRINT_SIDES:
                prices[rate["size"]][rate["print_type"]][print_sides] = rate[
                    "price_paise"
                ]
    delivery = database.digital_prices.find_one(
        {"service": "delivery_fee", "size": "flat", "print_type": "all"}
    )
    prices["delivery_fee_paise"] = delivery.get("price_paise", 0) if delivery else 0
    return prices


def tracking_id_for(order_id):
    return f"RP-{datetime.now(timezone.utc):%y%m%d}-{str(order_id)[-8:].upper()}"


def order_documents(order):
    if order.get("items"):
        return [
            document
            for item in order["items"]
            for document in item.get("documents", [])
        ]
    documents = order.get("documents")
    if documents:
        return documents
    return [{
        "document_name": order["document_name"],
        "display_name": order.get("display_name", order["document_name"]),
        "stored_name": order["stored_name"],
        "file_deleted": order.get("file_deleted", False),
    }]


def order_document_entries(order):
    if order.get("items"):
        for item_index, item in enumerate(order["items"]):
            for document_index, document in enumerate(item.get("documents", [])):
                yield document, f"items.{item_index}.documents.{document_index}"
        return
    if order.get("documents"):
        for document_index, document in enumerate(order["documents"]):
            yield document, f"documents.{document_index}"
        return
    if order.get("stored_name"):
        yield {
            "document_name": order.get("document_name", order["stored_name"]),
            "display_name": order.get("display_name", order["stored_name"]),
            "stored_name": order["stored_name"],
            "file_deleted": order.get("file_deleted", False),
        }, ""


def delete_rejected_order_files(database, order):
    upload_root = UPLOAD_FOLDER.resolve()
    for document, document_path in order_document_entries(order):
        stored_name = document.get("stored_name")
        if not stored_name:
            app.logger.warning(
                "Rejected-order cleanup skipped a document without a stored file for order %s.",
                order["_id"],
            )
            continue

        stored_path = (upload_root / stored_name).resolve()
        if stored_path.parent != upload_root:
            app.logger.error(
                "Rejected-order cleanup found an unsafe stored-file path for order %s.",
                order["_id"],
            )
            abort(
                409,
                description="A rejected order contains an unsafe stored-file path; cleanup was stopped.",
            )

        deleted_field = f"{document_path}.file_deleted" if document_path else "file_deleted"
        deleted_at_field = (
            f"{document_path}.file_deleted_at" if document_path else "file_deleted_at"
        )
        result = database.orders.update_one(
            {
                "_id": order["_id"],
                "status": "rejected",
                f"{document_path}.stored_name" if document_path else "stored_name": stored_name,
                deleted_field: {"$ne": True},
            },
            {
                "$set": {
                    deleted_field: True,
                    deleted_at_field: datetime.now(timezone.utc),
                }
            },
        )
        if not result.modified_count:
            continue

        try:
            stored_path.unlink(missing_ok=True)
        except OSError:
            database.orders.update_one(
                {"_id": order["_id"], "status": "rejected"},
                {"$unset": {deleted_field: "", deleted_at_field: ""}},
            )
            app.logger.exception(
                "Rejected-order cleanup could not delete an uploaded file for order %s.",
                order["_id"],
            )
            raise


def order_items(order):
    if order.get("items"):
        return order["items"]
    return [{
        "product_category": order.get("product_category", "cad"),
        "paper_size": order.get("paper_size", ""),
        "print_type": order.get("print_type"),
        "print_sides": order.get("print_sides"),
        "copies": order.get("copies", 1),
        "sheet_count": order.get("sheet_count"),
        "paper_type": order.get("paper_type"),
        "quote_paise": order.get("quote_paise"),
        "estimate_paise": order.get("digital_estimate_paise"),
        "documents": order_documents(order),
    }]


def item_copy_count(item):
    file_count = item.get("file_count", len(item.get("documents", []))) or 1
    copies = item.get("copies", 1) or 1
    return max(int(file_count), 1) * max(int(copies), 1)


def item_quote_per_copy_paise(item, order=None):
    existing_rate = item.get("quote_per_copy_paise")
    if existing_rate is not None:
        return existing_rate

    amount_paise = item.get("quote_paise")
    if item.get("product_category") == "digital_printing":
        amount_paise = item.get("estimate_paise", amount_paise)
    if order and not order.get("items") and item.get("estimate_paise") is None:
        amount_paise = max(
            order.get("quote_paise", 0)
            - order.get("additional_charges_paise", 0)
            - order.get(
                "quoted_delivery_charges_paise",
                order.get("delivery_fee_paise", 0),
            ),
            0,
        )
    if amount_paise is None:
        return None
    return int(
        (Decimal(amount_paise) / item_copy_count(item)).quantize(Decimal("1"))
    )


app.jinja_env.filters["money"] = money
app.jinja_env.globals["order_documents"] = order_documents
app.jinja_env.globals["order_items"] = order_items
app.jinja_env.globals["item_copy_count"] = item_copy_count
app.jinja_env.globals["item_quote_per_copy_paise"] = item_quote_per_copy_paise


def invoice_fields_for_order(database, order, generated_at=None):
    if order.get("status") == "rejected":
        raise ValueError("Cannot generate a bill for a rejected order.")

    generated_at = generated_at or datetime.now(timezone.utc)
    year = generated_at.year
    counter = database.bill_counters.find_one_and_update(
        {"_id": f"bill:{year}"},
        {"$inc": {"sequence": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    bill_number = (
        f"{app.config['BILLING_INVOICE_PREFIX']}/{year}/{counter['sequence']:06d}"
    )

    customer = order.get("billing_customer")
    if not customer:
        account = database.users.find_one({"_id": order["user_id"]}) or {}
        customer = {
            "name": order.get("customer_name") or account.get("name", "Customer"),
            "phone": account.get("whatsapp_number", ""),
            "address": order.get("delivery_address") or account.get("address", ""),
        }
    else:
        customer = {
            "name": customer.get("name") or order.get("customer_name", "Customer"),
            "phone": customer.get("phone", ""),
            "address": customer.get("address", ""),
        }

    additional_charges_paise = order.get("additional_charges_paise", 0)
    delivery_charges_paise = order.get(
        "quoted_delivery_charges_paise", order.get("delivery_fee_paise", 0)
    )
    total_paise = order.get("quote_paise", 0)
    items = order_items(order)
    invoice_items = []
    item_total_paise = 0
    for item in items:
        product_category = item.get("product_category", "cad")
        if product_category == "digital_printing":
            amount_paise = (
                item.get("quote_paise")
                if item.get("quote_per_copy_paise") is not None
                else item.get("estimate_paise")
            )
        else:
            amount_paise = item.get("quote_paise")
        if amount_paise is None:
            amount_paise = 0
        item_total_paise += amount_paise
        detail_parts = [
            "CAD drawing" if product_category == "cad" else "Digital printing",
            item.get("paper_size", ""),
        ]
        if product_category == "cad" and item.get("paper_type"):
            detail_parts.append(item["paper_type"])
        if product_category == "digital_printing":
            detail_parts.extend(
                [
                    "Front and back" if item.get("print_sides") == "front_back" else "Front only",
                ]
            )
        invoice_items.append({
            "description": " · ".join(part for part in detail_parts if part),
            "print_type": (
                "Color"
                if item.get("print_type") == "color"
                else "Black & white"
                if product_category == "digital_printing"
                else ""
            ),
            "quantity": (
                f"{item.get('file_count', len(item.get('documents', [])))} file(s) "
                f"× {item.get('copies', 1)} cop(y)"
            ),
            "amount_paise": amount_paise,
        })

    # Legacy one-item records may only have an order-level total and estimates.
    if not order.get("items") and invoice_items:
        legacy_item = invoice_items[0]
        legacy_estimate = order.get("digital_estimate_paise")
        if legacy_estimate is not None:
            legacy_item["amount_paise"] = legacy_estimate
            item_total_paise = legacy_estimate
        else:
            legacy_item["amount_paise"] = max(
                total_paise - additional_charges_paise - delivery_charges_paise,
                0,
            )
            item_total_paise = legacy_item["amount_paise"]

    calculated_total = (
        item_total_paise + additional_charges_paise + delivery_charges_paise
    )
    adjustment_paise = total_paise - calculated_total
    if adjustment_paise:
        invoice_items.append({
            "description": "Order total adjustment",
            "quantity": "",
            "amount_paise": adjustment_paise,
        })

    snapshot = {
        "bill_number": bill_number,
        "generated_at": generated_at,
        "seller": {
            "name": app.config["BILLING_BUSINESS_NAME"],
            "gstin": app.config["BILLING_GSTIN"],
            "phone": app.config["BILLING_PHONE"],
            "email": app.config["BILLING_EMAIL"],
            "address": app.config["BILLING_ADDRESS"],
            "state": app.config["BILLING_STATE"],
        },
        "customer": customer,
        "order_number": order.get("tracking_id", str(order["_id"])),
        "items": invoice_items,
        "additional_charges_paise": additional_charges_paise,
        "delivery_charges_paise": delivery_charges_paise,
        "total_paise": total_paise,
    }
    return {
        "invoice_number": bill_number,
        "invoice_generated_at": generated_at,
        "invoice_snapshot": snapshot,
    }


def invoice_pdf(snapshot):
    pdf_buffer = io.BytesIO()
    pdf = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Bill {snapshot['bill_number']}",
        author=snapshot["seller"]["name"],
    )
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "Helvetica-Bold"
    styles["Title"].fontSize = 19
    styles["Title"].textColor = colors.HexColor("#18263b")
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 13
    styles["Heading2"].fontSize = 11
    right_style = styles["BodyText"].clone("InvoiceRight")
    right_style.alignment = TA_RIGHT
    seller = snapshot["seller"]
    customer = snapshot["customer"]
    story = [
        Paragraph(escape(seller["name"] or "Business"), styles["Title"]),
    ]
    seller_lines = [
        seller.get("address", ""),
        f"GSTIN: {seller['gstin']}" if seller.get("gstin") else "",
        f"Phone: {seller['phone']}" if seller.get("phone") else "",
        f"Email: {seller['email']}" if seller.get("email") else "",
        f"State: {seller['state']}" if seller.get("state") else "",
    ]
    seller_text = "<br/>".join(escape(line) for line in seller_lines if line)
    header = Table(
        [[
            Paragraph(seller_text or " ", styles["BodyText"]),
            Paragraph(
                f"<b>BILL</b><br/>No: {escape(snapshot['bill_number'])}<br/>"
                f"Date: {snapshot['generated_at'].strftime('%d %b %Y')}<br/>"
                f"Order: {escape(snapshot['order_number'])}",
                right_style,
            ),
        ]],
        colWidths=[105 * mm, 65 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.extend([header, Spacer(1, 7 * mm), Paragraph("Billed to", styles["Heading2"])])
    customer_lines = [
        customer.get("name", ""),
        customer.get("address", ""),
        f"Phone: {customer['phone']}" if customer.get("phone") else "",
    ]
    story.extend([
        Paragraph("<br/>".join(escape(line) for line in customer_lines if line) or "Customer", styles["BodyText"]),
        Spacer(1, 8 * mm),
    ])

    table_data = [[
        Paragraph("<b>#</b>", styles["BodyText"]),
        Paragraph("<b>Item / description</b>", styles["BodyText"]),
        Paragraph("<b>Print type</b>", styles["BodyText"]),
        Paragraph("<b>Quantity</b>", styles["BodyText"]),
        Paragraph("<b>Amount (INR)</b>", right_style),
    ]]
    for index, item in enumerate(snapshot["items"], 1):
        description = Paragraph(escape(item["description"]), styles["BodyText"])
        table_data.append([
            str(index),
            description,
            Paragraph(escape(item.get("print_type") or "-"), styles["BodyText"]),
            Paragraph(escape(item.get("quantity", "")), styles["BodyText"]),
            Paragraph(f"{item['amount_paise'] / 100:,.2f}", right_style),
        ])
    item_table = Table(
        table_data,
        colWidths=[8 * mm, 67 * mm, 30 * mm, 30 * mm, 35 * mm],
        repeatRows=1,
    )
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#18263b")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d8d8d1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([item_table, Spacer(1, 5 * mm)])
    total_rows = [
        ["Items total", f"INR {sum(item['amount_paise'] for item in snapshot['items']) / 100:,.2f}"],
        ["Additional charges", f"INR {snapshot['additional_charges_paise'] / 100:,.2f}"],
        ["Delivery charges", f"INR {snapshot['delivery_charges_paise'] / 100:,.2f}"],
        ["Bill total", f"INR {snapshot['total_paise'] / 100:,.2f}"],
    ]
    totals = Table(total_rows, colWidths=[127 * mm, 43 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#18263b")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([
        totals,
        Spacer(1, 12 * mm),
        Paragraph("This is a computer-generated bill.", styles["BodyText"]),
    ])
    pdf.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer.read()


def invoice_month_range(month_value):
    if not re.fullmatch(r"\d{4}-\d{2}", month_value):
        raise ValueError("Month must use YYYY-MM format.")
    month = datetime.strptime(month_value, "%Y-%m").replace(
        day=1, tzinfo=timezone.utc
    )
    next_month = (
        month.replace(year=month.year + 1, month=1)
        if month.month == 12
        else month.replace(month=month.month + 1)
    )
    return month, next_month


def mongo_unavailable():
    return render_template("unavailable.html"), 503


@app.errorhandler(PyMongoError)
def handle_database_error(_error):
    return mongo_unavailable()


@app.errorhandler(413)
def upload_too_large(_error):
    flash("This order exceeds the 20 MB total upload limit.", "error")
    return redirect(url_for("new_order"))


@app.route("/", methods=["GET"])
def home():
    if g.user:
        return redirect(url_for(landing_endpoint(g.user)))
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for(landing_endpoint(g.user)))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = get_database().users.find_one({"username": username})
        if user and check_password_hash(user["password_hash"], password):
            start_login_session(user["_id"])
            destination = request.form.get("next", "").strip()
            parsed_destination = urlsplit(destination)
            if (
                user.get("role") == "admin"
                and destination.startswith("/")
                and not destination.startswith("//")
                and not parsed_destination.netloc
                and parsed_destination.path == url_for("admin_bills")
            ):
                return redirect(destination)
            return redirect(url_for(landing_endpoint(user)))
        flash("That username and password do not match.", "error")
    return render_template(
        "login.html",
        next=request.form.get("next", request.args.get("next", "")),
        demo_mode=app.config["RAJU_DEMO_MODE"],
        demo_admin_username=app.config["DEMO_ADMIN_USERNAME"],
        demo_admin_password=app.config["DEMO_ADMIN_PASSWORD"],
        demo_customer_username=app.config["DEMO_CUSTOMER_USERNAME"],
        demo_customer_password=app.config["DEMO_CUSTOMER_PASSWORD"],
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for(landing_endpoint(g.user)))
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
        mobile_number = re.sub(
            r"\D", "", request.form.get("whatsapp_number", "")
        )
        whatsapp_number = (
            f"+91{mobile_number}"
            if re.fullmatch(r"[6-9]\d{9}", mobile_number)
            else ""
        )
        whatsapp_opt_in = request.form.get("whatsapp_opt_in") == "yes"
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        form_data.update(
            name=name,
            username=username,
            address=address,
            whatsapp_number=mobile_number,
            whatsapp_opt_in=whatsapp_opt_in,
        )

        if not name or len(name) > 100:
            form_error = "Enter your name (up to 100 characters)."
        elif not address or len(address) > 500:
            form_error = "Enter your delivery address (up to 500 characters)."
        elif not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,59}", username):
            form_error = "Username must be 3–60 characters and use letters, numbers, dots, dashes, or underscores."
        elif not whatsapp_number:
            form_error = "Enter a valid 10-digit Indian mobile number."
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
            elif app.config["SMS_AUTHENTICATION_ENABLED"] and database.auth_challenges.find_one(
                {
                    "phone_number": whatsapp_number,
                    "created_at": {
                        "$gt": datetime.now(timezone.utc) - timedelta(minutes=1)
                    },
                }
            ):
                form_error = "Please wait one minute before requesting another verification text."
                response_status = 429
            else:
                user = {
                    "name": name,
                    "address": address,
                    "addresses": [address],
                    "username": username,
                    "password_hash": generate_password_hash(password),
                    "role": "customer",
                    "whatsapp_number": whatsapp_number,
                    "whatsapp_opt_in": True,
                    "whatsapp_opted_in_at": datetime.now(timezone.utc),
                    "created_at": datetime.now(timezone.utc),
                }
                if app.config["SMS_AUTHENTICATION_ENABLED"]:
                    try:
                        create_auth_challenge(
                            "signup",
                            whatsapp_number,
                            name=name,
                            address=address,
                            username=username,
                            password_hash=user["password_hash"],
                            whatsapp_opted_in_at=user["whatsapp_opted_in_at"],
                        )
                    except RuntimeError:
                        form_error = (
                            "We couldn’t send a verification text. Please try again "
                            "later or contact the shop."
                        )
                        response_status = 503
                    else:
                        return redirect(url_for("verify_signup"))
                else:
                    try:
                        result = database.users.insert_one(user)
                    except PyMongoError as error:
                        if getattr(error, "code", None) != 11000:
                            raise
                        form_error = "That username is already in use. Try signing in instead."
                        response_status = 409
                    else:
                        start_login_session(result.inserted_id)
                        return redirect(url_for("new_order"))
    return render_template("signup.html", form_data=form_data, form_error=form_error), response_status


@app.route("/signup/verify", methods=["GET", "POST"])
def verify_signup():
    if not app.config["SMS_AUTHENTICATION_ENABLED"]:
        return redirect(url_for("signup"))
    if g.user:
        return redirect(url_for(landing_endpoint(g.user)))
    challenge = current_auth_challenge("signup")
    if not challenge:
        session.pop("auth_challenge", None)
        flash("Your verification session expired. Please create your account again.", "error")
        return redirect(url_for("signup"))

    form_error = None
    response_status = 200
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if not AUTH_CODE_PATTERN.fullmatch(code):
            form_error = "Enter the verification code from the SMS."
            response_status = 400
        elif challenge.get("attempt_count", 0) >= 5:
            form_error = "Too many attempts. Restart account creation to try again."
            response_status = 429
        else:
            try:
                is_approved = twilio_verify_request(
                    "check", challenge["phone_number"], code
                )
            except RuntimeError:
                form_error = "SMS verification is temporarily unavailable. Please try again."
                response_status = 503
            else:
                get_database().auth_challenges.update_one(
                    {"_id": challenge["_id"]}, {"$inc": {"attempt_count": 1}}
                )
                if not is_approved:
                    form_error = "That code is invalid or expired. Check the SMS and try again."
                    response_status = 400
                else:
                    user = {
                        "name": challenge["name"],
                        "address": challenge["address"],
                        "addresses": [challenge["address"]],
                        "username": challenge["username"],
                        "password_hash": challenge["password_hash"],
                        "role": "customer",
                        "whatsapp_number": challenge["phone_number"],
                        "phone_verified": True,
                        "phone_verified_at": datetime.now(timezone.utc),
                        "whatsapp_opt_in": True,
                        "whatsapp_opted_in_at": challenge["whatsapp_opted_in_at"],
                        "created_at": datetime.now(timezone.utc),
                    }
                    try:
                        result = get_database().users.insert_one(user)
                    except PyMongoError as error:
                        if getattr(error, "code", None) != 11000:
                            raise
                        get_database().auth_challenges.delete_one(
                            {"_id": challenge["_id"]}
                        )
                        session.pop("auth_challenge", None)
                        flash(
                            "That username was just registered. Sign in or choose another username.",
                            "error",
                        )
                        return redirect(url_for("signup"))
                    get_database().auth_challenges.delete_one(
                        {"_id": challenge["_id"]}
                    )
                    start_login_session(result.inserted_id)
                    return redirect(url_for("new_order"))

    return render_template(
        "verify_phone.html",
        purpose="signup",
        masked_phone=masked_phone_number(challenge["phone_number"]),
        form_error=form_error,
    ), response_status


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if not app.config["SMS_AUTHENTICATION_ENABLED"]:
        return redirect(url_for("login"))
    if g.user:
        return redirect(url_for(landing_endpoint(g.user)))
    form_error = None
    response_status = 200
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        phone_number = normalize_whatsapp_number(
            request.form.get("whatsapp_number", "")
        )
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,59}", username) or not phone_number:
            form_error = "Enter your username and mobile number with country code."
            response_status = 400
        else:
            user = get_database().users.find_one(
                {
                    "username": username,
                    "role": "customer",
                    "whatsapp_number": phone_number,
                },
                {"_id": 1},
            )
            recent_challenge = get_database().auth_challenges.find_one(
                {
                    "phone_number": phone_number,
                    "created_at": {
                        "$gt": datetime.now(timezone.utc) - timedelta(minutes=1)
                    },
                }
            )
            try:
                create_auth_challenge(
                    "reset",
                    phone_number,
                    send_sms=user is not None and recent_challenge is None,
                    user_id=user["_id"] if user else None,
                    account_matches=user is not None,
                )
            except RuntimeError:
                form_error = (
                    "We couldn’t send a verification text. Please try again later."
                )
                response_status = 503
            else:
                return redirect(url_for("verify_password_reset"))
    return render_template(
        "forgot_password.html", form_error=form_error
    ), response_status


@app.route("/forgot-password/verify", methods=["GET", "POST"])
def verify_password_reset():
    if not app.config["SMS_AUTHENTICATION_ENABLED"]:
        return redirect(url_for("login"))
    if g.user:
        return redirect(url_for(landing_endpoint(g.user)))
    challenge = current_auth_challenge("reset")
    if not challenge:
        session.pop("auth_challenge", None)
        flash("Your recovery session expired. Please start again.", "error")
        return redirect(url_for("forgot_password"))
    if challenge.get("verified_at"):
        return redirect(url_for("reset_password"))

    form_error = None
    response_status = 200
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if not AUTH_CODE_PATTERN.fullmatch(code):
            form_error = "Enter the verification code from the SMS."
            response_status = 400
        elif challenge.get("attempt_count", 0) >= 5:
            form_error = "Too many attempts. Restart password recovery to try again."
            response_status = 429
        else:
            try:
                is_approved = (
                    challenge.get("account_matches")
                    and twilio_verify_request(
                        "check", challenge["phone_number"], code
                    )
                )
            except RuntimeError:
                form_error = "SMS verification is temporarily unavailable. Please try again."
                response_status = 503
            else:
                get_database().auth_challenges.update_one(
                    {"_id": challenge["_id"]}, {"$inc": {"attempt_count": 1}}
                )
                if not is_approved:
                    form_error = "That code is invalid or expired. Check the SMS and try again."
                    response_status = 400
                else:
                    get_database().auth_challenges.update_one(
                        {"_id": challenge["_id"]},
                        {"$set": {"verified_at": datetime.now(timezone.utc)}},
                    )
                    return redirect(url_for("reset_password"))
    return render_template(
        "verify_phone.html",
        purpose="reset",
        masked_phone=masked_phone_number(challenge["phone_number"]),
        form_error=form_error,
    ), response_status


@app.route("/forgot-password/reset", methods=["GET", "POST"])
def reset_password():
    if not app.config["SMS_AUTHENTICATION_ENABLED"]:
        return redirect(url_for("login"))
    if g.user:
        return redirect(url_for(landing_endpoint(g.user)))
    challenge = current_auth_challenge("reset")
    if not challenge or not challenge.get("verified_at"):
        session.pop("auth_challenge", None)
        flash("Verify your mobile number before resetting your password.", "error")
        return redirect(url_for("forgot_password"))
    form_error = None
    response_status = 200
    if request.method == "POST":
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        if len(password) < 8:
            form_error = "Choose a password with at least 8 characters."
            response_status = 400
        elif password != password_confirm:
            form_error = "Those passwords do not match."
            response_status = 400
        elif not challenge.get("account_matches") or not challenge.get("user_id"):
            form_error = "We couldn’t verify those account details. Please start again."
            response_status = 400
        else:
            database = get_database()
            result = database.users.update_one(
                {
                    "_id": challenge["user_id"],
                    "role": "customer",
                    "whatsapp_number": challenge["phone_number"],
                },
                {"$set": {"password_hash": generate_password_hash(password)}},
            )
            if not result.matched_count:
                form_error = "We couldn’t find that account. Please start again."
                response_status = 404
            else:
                database.login_sessions.update_many(
                    {"user_id": challenge["user_id"], "revoked_at": None},
                    {"$set": {"revoked_at": datetime.now(timezone.utc)}},
                )
                database.auth_challenges.delete_one({"_id": challenge["_id"]})
                session.pop("auth_challenge", None)
                flash("Your password has been reset. You can now sign in.", "success")
                return redirect(url_for("login"))
    return render_template(
        "reset_password.html", form_error=form_error
    ), response_status


@app.post("/auth/resend-code")
def resend_auth_code():
    if not app.config["SMS_AUTHENTICATION_ENABLED"]:
        return redirect(url_for("login"))
    challenge = current_auth_challenge()
    if not challenge:
        session.pop("auth_challenge", None)
        flash("Your verification session expired. Please start again.", "error")
        return redirect(url_for("signup"))
    now = datetime.now(timezone.utc)
    if challenge.get("resend_count", 0) >= 3:
        flash("You’ve reached the SMS resend limit. Please start again later.", "error")
    elif (now - challenge["last_sent_at"]).total_seconds() < 60:
        flash("Please wait a minute before requesting another code.", "error")
    elif challenge.get("purpose") == "reset" and not challenge.get("account_matches"):
        flash("If the account details match, a new code will be sent.", "success")
    else:
        try:
            twilio_verify_request("send", challenge["phone_number"])
        except RuntimeError:
            flash("SMS verification is temporarily unavailable. Please try again.", "error")
        else:
            get_database().auth_challenges.update_one(
                {"_id": challenge["_id"]},
                {
                    "$set": {"last_sent_at": now},
                    "$inc": {"resend_count": 1},
                },
            )
            flash("A new verification code has been sent.", "success")
    endpoint = (
        "verify_password_reset"
        if challenge.get("purpose") == "reset"
        else "verify_signup"
    )
    return redirect(url_for(endpoint))


@app.post("/logout")
@login_required
def logout():
    database = get_database()
    login_session_id = session.get("login_session_id")
    if login_session_id:
        database.login_sessions.update_one(
            {
                "user_id": g.user["_id"],
                "session_hash": hashlib.sha256(login_session_id.encode()).hexdigest(),
                "revoked_at": None,
            },
            {"$set": {"revoked_at": datetime.now(timezone.utc)}},
        )
    session.clear()
    return redirect(url_for("login"))


@app.post("/account/addresses")
@login_required
def add_account_address():
    if g.user["role"] != "customer":
        abort(403)
    address = request.form.get("address", "").strip()
    if not address or len(address) > 500:
        flash("Enter an address of up to 500 characters.", "error")
        return redirect(url_for("account_addresses"))
    database = get_database()
    update = {"$addToSet": {"addresses": address}}
    if not g.user.get("address"):
        update["$set"] = {"address": address}
    result = database.users.update_one(
        {"_id": g.user["_id"], "role": "customer"},
        update,
    )
    if not result.matched_count:
        abort(404)
    flash("Address saved to your account.", "success")
    return redirect(url_for("account_addresses"))


@app.get("/account/addresses")
@login_required
def account_addresses():
    if g.user["role"] != "customer":
        abort(403)
    return render_template(
        "customer_addresses.html",
        addresses=customer_addresses(g.user),
    )


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
            "work_in_progress",
            "ready_for_pickup",
            "out_for_delivery",
        ]
        order_filters = {
            "all": ("All active orders", active_statuses),
            "waiting_quote": ("Waiting for quotation", ["pending_quote"]),
            "pending_payment": (
                "Pending payment",
                ["awaiting_payment", "payment_submitted"],
            ),
            "paid_not_production": ("Paid, not in production", ["paid", "confirmed"]),
            "production": ("In production", ["printing", "work_in_progress"]),
            "dispatch": ("Ready for pickup / dispatch", ["ready_for_pickup", "out_for_delivery"]),
            "cancelled": ("Cancelled / rejected", ["cancelled", "rejected"]),
        }
        selected_filter = request.args.get("order_filter", "all")
        if selected_filter not in order_filters:
            selected_filter = "all"
        selected_label, selected_statuses = order_filters[selected_filter]
        orders = list(
            database.orders.find({"status": {"$in": selected_statuses}})
            .sort("created_at", DESCENDING)
            .limit(100)
        )
        counts = {
            "open": database.orders.count_documents({"status": "pending_quote"}),
            "payment": database.orders.count_documents(
                {"status": {"$in": ["awaiting_payment", "payment_submitted"]}}
            ),
            "paid": database.orders.count_documents(
                {"status": {"$in": ["paid", "confirmed", "printing", "work_in_progress", "ready_for_pickup", "out_for_delivery"]}}
            ),
        }
        return render_template(
            "admin.html",
            orders=orders,
            counts=counts,
            order_filters={key: value[0] for key, value in order_filters.items()},
            selected_filter=selected_filter,
            selected_filter_label=selected_label,
            digital_prices=digital_price_map(database),
            digital_sizes=DIGITAL_SIZES,
            print_types=PRINT_TYPES,
            print_side_options=PRINT_SIDES,
        )
    orders = list(
        database.orders.find(
            {
                "user_id": g.user["_id"],
                "status": {
                    "$in": [
                        "pending_quote",
                        "awaiting_payment",
                        "payment_submitted",
                        "paid",
                        "confirmed",
                        "printing",
                        "work_in_progress",
                        "ready_for_pickup",
                        "out_for_delivery",
                    ]
                },
            }
        ).sort("created_at", DESCENDING)
    )
    return render_template(
        "customer.html",
        orders=orders,
        upi_id=app.config["UPI_ID"],
        upi_payee_name=app.config["UPI_PAYEE_NAME"],
    )


@app.get("/orders/history")
@login_required
def order_history():
    if g.user["role"] != "customer":
        abort(403)
    orders = list(
        get_database()
        .orders.find(
            {
                "user_id": g.user["_id"],
                "status": {"$in": ["delivered", "cancelled", "rejected"]},
            }
        )
        .sort("created_at", DESCENDING)
    )
    return render_template("order_history.html", orders=orders)


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


@app.get("/admin/bills")
@admin_required
def admin_bills():
    month_value = request.args.get("month", datetime.now(timezone.utc).strftime("%Y-%m"))
    try:
        start, end = invoice_month_range(month_value)
    except ValueError:
        abort(400, description="Choose a valid billing month.")
    orders = list(
        get_database()
        .orders.find({
            "invoice_generated_at": {"$gte": start, "$lt": end},
            "invoice_snapshot": {"$exists": True},
            "status": {"$ne": "rejected"},
        })
        .sort("invoice_generated_at", DESCENDING)
        .limit(1000)
    )
    return render_template(
        "admin_bills.html",
        orders=orders,
        selected_month=month_value,
        total_paise=sum(
            order["invoice_snapshot"].get("total_paise", 0) for order in orders
        ),
    )


@app.get("/admin/bills/download")
@admin_required
def download_monthly_bills():
    month_value = request.args.get("month", datetime.now(timezone.utc).strftime("%Y-%m"))
    try:
        start, end = invoice_month_range(month_value)
    except ValueError:
        abort(400, description="Choose a valid billing month.")
    orders = list(
        get_database()
        .orders.find({
            "invoice_generated_at": {"$gte": start, "$lt": end},
            "invoice_snapshot": {"$exists": True},
            "status": {"$ne": "rejected"},
        })
        .sort("invoice_generated_at", DESCENDING)
    )
    if not orders:
        flash("There are no generated bills for that month.", "error")
        return redirect(url_for("admin_bills", month=month_value))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for order in orders:
            snapshot = order.get("invoice_snapshot")
            if not snapshot:
                app.logger.error(
                    "Invoice archive encountered a bill without its snapshot: %s",
                    order.get("invoice_number", order["_id"]),
                )
                abort(500, description="A generated bill is missing its saved invoice details.")
            bill_name = secure_filename(snapshot.get("bill_number", "bill")) or "bill"
            zip_file.writestr(
                f"{bill_name}.pdf",
                invoice_pdf(snapshot),
            )
    archive.seek(0)
    return send_file(
        archive,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"bills_{month_value}.zip",
    )


@app.get("/orders/<order_id>/bill")
@login_required
def download_order_bill(order_id):
    try:
        order_object_id = ObjectId(order_id)
    except (InvalidId, TypeError):
        abort(404)
    order = get_database().orders.find_one({"_id": order_object_id})
    if not order:
        abort(404)
    if g.user["role"] != "admin" and order.get("user_id") != g.user["_id"]:
        abort(403)
    snapshot = order.get("invoice_snapshot")
    if (
        order.get("status") == "rejected"
        or not snapshot
        or not order.get("invoice_number")
    ):
        abort(404, description="A bill is not available until payment is confirmed.")
    bill_name = secure_filename(snapshot["bill_number"]) or "bill"
    return send_file(
        io.BytesIO(invoice_pdf(snapshot)),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{bill_name}.pdf",
    )


def completed_file_cleanup_filters(source):
    customer_id = source.get("customer_id", "").strip()
    start_date = source.get("start_date", "").strip()
    end_date = source.get("end_date", "").strip()
    min_size_raw = source.get("min_size_mb", "").strip()
    max_size_raw = source.get("max_size_mb", "").strip()
    try:
        min_size_mb = Decimal(min_size_raw) if min_size_raw else None
        max_size_mb = Decimal(max_size_raw) if max_size_raw else None
        if customer_id:
            ObjectId(customer_id)
        if start_date:
            start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            start = None
        if end_date:
            end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            end = None
    except (InvalidId, InvalidOperation, ValueError, TypeError):
        abort(400, description="Choose a valid customer, file size, and date range.")
    if (
        (min_size_mb is not None and (not min_size_mb.is_finite() or min_size_mb < 0))
        or (max_size_mb is not None and (not max_size_mb.is_finite() or max_size_mb < 0))
        or (min_size_mb is not None and max_size_mb is not None and min_size_mb > max_size_mb)
        or (start is not None and end is not None and start > end)
    ):
        abort(400, description="Enter a valid file-size range and order date range.")
    return {
        "customer_id": customer_id,
        "start_date": start_date,
        "end_date": end_date,
        "min_size_mb": min_size_raw,
        "max_size_mb": max_size_raw,
        "min_size_value": min_size_mb,
        "max_size_value": max_size_mb,
    }


def completed_file_cleanup_candidates(database, filters):
    query = {"status": {"$in": ["delivered", "cancelled", "rejected"]}}
    if filters["customer_id"]:
        query["user_id"] = ObjectId(filters["customer_id"])
    if filters["start_date"]:
        query.setdefault("created_at", {})["$gte"] = datetime.strptime(
            filters["start_date"], "%Y-%m-%d"
        ).replace(tzinfo=timezone.utc)
    if filters["end_date"]:
        query.setdefault("created_at", {})["$lt"] = datetime.strptime(
            filters["end_date"], "%Y-%m-%d"
        ).replace(tzinfo=timezone.utc) + timedelta(days=1)

    upload_root = UPLOAD_FOLDER.resolve()
    for order in database.orders.find(query).sort("created_at", DESCENDING):
        for document, document_path in order_document_entries(order):
            if document.get("file_deleted"):
                continue
            if not document.get("stored_name"):
                app.logger.warning(
                    "Completed-order file cleanup skipped a document without a stored file for order %s.",
                    order["_id"],
                )
                continue
            stored_path = (upload_root / document["stored_name"]).resolve()
            if stored_path.parent != upload_root:
                abort(
                    409,
                    description="A completed order contains an unsafe stored-file path; cleanup was stopped.",
                )
            if not stored_path.is_file():
                app.logger.warning(
                    "Completed-order file cleanup skipped a missing file for order %s.",
                    order["_id"],
                )
                continue
            size_bytes = stored_path.stat().st_size
            size_mb = Decimal(size_bytes) / Decimal(1024 * 1024)
            if (
                filters["min_size_value"] is not None
                and size_mb < filters["min_size_value"]
            ) or (
                filters["max_size_value"] is not None
                and size_mb > filters["max_size_value"]
            ):
                continue
            yield {
                "order": order,
                "document": document,
                "document_path": document_path,
                "stored_path": stored_path,
                "size_bytes": size_bytes,
            }


@app.route("/admin/orders/completed/files/cleanup", methods=["GET", "POST"])
@admin_required
def cleanup_completed_order_files():
    database = get_database()
    customers = list(
        database.users.find({"role": "customer"}, {"password_hash": 0}).sort("name", 1)
    )

    def render_cleanup(filters=None, preview=None, matched_files=None):
        return render_template(
            "admin_file_cleanup.html",
            customers=customers,
            filters=filters or {
                "customer_id": "",
                "start_date": "",
                "end_date": "",
                "min_size_mb": "",
                "max_size_mb": "",
            },
            preview=preview,
            matched_files=matched_files or [],
        )

    if request.method == "GET" and not request.args.get("preview"):
        return render_cleanup()

    filters = completed_file_cleanup_filters(
        request.form if request.method == "POST" else request.args
    )
    if request.method == "GET" or request.form.get("confirm_delete") != "yes":
        matched_files = []
        count = 0
        size_bytes = 0
        for candidate in completed_file_cleanup_candidates(database, filters):
            count += 1
            size_bytes += candidate["size_bytes"]
            if len(matched_files) < 100:
                matched_files.append({
                    "tracking_id": candidate["order"].get(
                        "tracking_id", f"RP-{candidate['order']['_id']}"
                    ),
                    "customer_name": candidate["order"].get("customer_name", "Customer"),
                    "file_name": candidate["document"].get(
                        "document_name", candidate["document"]["stored_name"]
                    ),
                    "size_bytes": candidate["size_bytes"],
                })
        if request.method == "POST":
            flash("Confirm the deletion checkbox before removing files.", "error")
        return render_cleanup(
            filters,
            {"count": count, "size_bytes": size_bytes},
            matched_files,
        )

    deleted_count = 0
    deleted_size_bytes = 0
    for candidate in completed_file_cleanup_candidates(database, filters):
        document_path = candidate["document_path"]
        deleted_field = f"{document_path}.file_deleted" if document_path else "file_deleted"
        deleted_at_field = (
            f"{document_path}.file_deleted_at" if document_path else "file_deleted_at"
        )
        result = database.orders.update_one(
            {
                "_id": candidate["order"]["_id"],
                "status": {"$in": ["delivered", "cancelled", "rejected"]},
                deleted_field: {"$ne": True},
            },
            {"$set": {deleted_field: True, deleted_at_field: datetime.now(timezone.utc)}},
        )
        if not result.modified_count:
            app.logger.warning(
                "Completed-order file cleanup skipped a file changed during cleanup for order %s.",
                candidate["order"]["_id"],
            )
            continue
        try:
            candidate["stored_path"].unlink()
        except OSError:
            database.orders.update_one(
                {"_id": candidate["order"]["_id"]},
                {"$unset": {deleted_field: "", deleted_at_field: ""}},
            )
            raise
        deleted_count += 1
        deleted_size_bytes += candidate["size_bytes"]

    flash(
        f"Deleted {deleted_count} completed-order file(s), freeing "
        f"{deleted_size_bytes / (1024 * 1024):.2f} MB. Order records were kept.",
        "success",
    )
    return redirect(url_for("cleanup_completed_order_files"))


@app.get("/admin/prices/digital")
@admin_required
def digital_prices():
    return render_template(
        "digital_prices.html",
        digital_prices=digital_price_map(get_database()),
        digital_sizes=DIGITAL_SIZES,
        print_types=PRINT_TYPES,
        print_side_options=PRINT_SIDES,
    )


@app.get("/orders/new")
@login_required
def new_order():
    if g.user["role"] != "customer":
        abort(403)
    return render_template(
        "order_new.html",
        digital_prices=digital_price_map(get_database()),
        digital_sizes=DIGITAL_SIZES,
        digital_size_descriptions=DIGITAL_SIZE_DESCRIPTIONS,
        print_side_options=PRINT_SIDES,
        customer_addresses=customer_addresses(g.user),
    )


@app.post("/orders")
@login_required
def create_order():
    if g.user["role"] != "customer":
        abort(403)
    cart_count = request.form.get("cart_items_count")
    if cart_count is not None:
        try:
            item_count = int(cart_count)
        except ValueError:
            item_count = 0
        if not 1 <= item_count <= 50:
            flash("Add between 1 and 50 items to your cart.", "error")
            return redirect(url_for("new_order"))
        requested_items = []
        for index in range(item_count):
            prefix = f"cart_items[{index}]"
            requested_items.append({
                "product_category": request.form.get(f"{prefix}[product_category]", ""),
                "copies": request.form.get(f"{prefix}[copies]", ""),
                "paper_size": request.form.get(f"{prefix}[paper_size]", ""),
                "print_type": request.form.get(f"{prefix}[print_type]", ""),
                "print_sides": request.form.get(f"{prefix}[print_sides]", ""),
                "cad_size": request.form.get(f"{prefix}[cad_size]", ""),
                "paper_type": request.form.get(f"{prefix}[paper_type]", ""),
                "notes": request.form.get(f"{prefix}[notes]", ""),
                "uploads": [
                    file for file in request.files.getlist(f"{prefix}[documents]")
                    if file.filename
                ],
            })
    else:
        uploaded_files = request.files.getlist("documents")
        if not uploaded_files:
            uploaded_files = request.files.getlist("document")
        requested_items = [{
            "product_category": request.form.get("product_category", "digital_printing"),
            "copies": request.form.get("copies", "1"),
            "paper_size": request.form.get("paper_size", ""),
            "print_type": request.form.get("print_type", ""),
            "print_sides": request.form.get("print_sides", "front_only"),
            "cad_size": request.form.get("cad_size", ""),
            "paper_type": request.form.get("paper_type", ""),
            "notes": request.form.get("notes", ""),
            "uploads": [file for file in uploaded_files if file.filename],
        }]
    if any(not item["uploads"] for item in requested_items):
        flash("Each cart item must include at least one document.", "error")
        return redirect(url_for("new_order"))

    database = get_database()
    delivery_type = request.form.get("delivery_type", "pickup")
    if delivery_type not in {"pickup", "delivery"}:
        flash("Choose pickup or delivery.", "error")
        return redirect(url_for("new_order"))
    if delivery_type == "delivery":
        address_choice = request.form.get("delivery_address_choice", "")
        saved_addresses = customer_addresses(g.user)
        if address_choice == "__new__":
            delivery_address = request.form.get("delivery_address", "").strip()
        elif address_choice in saved_addresses:
            delivery_address = address_choice
        else:
            delivery_address = ""
        if not delivery_address:
            flash("Choose a saved address or enter a new delivery address.", "error")
            return redirect(url_for("new_order"))
        if len(delivery_address) > 500:
            flash("Delivery addresses must be 500 characters or fewer.", "error")
            return redirect(url_for("new_order"))
    else:
        delivery_address = ""
    delivery_fee_paise = digital_price_map(database).get("delivery_fee_paise", 0) if delivery_type == "delivery" else 0

    order_id = ObjectId()
    order_tracking_id = tracking_id_for(order_id)
    items = []
    saved_paths = []
    for item_index, requested in enumerate(requested_items):
        category = requested["product_category"]
        if category not in {"digital_printing", "cad"}:
            flash("Choose digital printing or CAD printing for every cart item.", "error")
            return redirect(url_for("new_order"))
        try:
            copies = int(requested["copies"])
        except ValueError:
            copies = 0
        if not 1 <= copies <= 1000:
            flash("Prints per file must be a number between 1 and 1,000.", "error")
            return redirect(url_for("new_order"))
        notes = requested["notes"].strip()[:500]
        if category == "digital_printing":
            paper_size = requested["paper_size"]
            print_type = requested["print_type"]
            print_sides = requested["print_sides"]
            if paper_size not in DIGITAL_SIZES or print_type not in PRINT_TYPES or print_sides not in PRINT_SIDES:
                flash("Choose a valid digital print size, mode, and side option for every item.", "error")
                return redirect(url_for("new_order"))
            rate = database.digital_prices.find_one({
                "service": "digital_printing",
                "size": paper_size,
                "print_type": print_type,
                "print_sides": print_sides,
            })
            if not rate or rate.get("price_paise", 0) <= 0:
                flash(f"Digital printing is not priced for {paper_size} in the selected mode.", "error")
                return redirect(url_for("new_order"))
            price_each_paise = rate["price_paise"]
            file_count = len(requested["uploads"])
            sheet_count = (file_count + 1) // 2 if print_sides == "front_back" else file_count
            estimate_paise = price_each_paise * copies * sheet_count
        else:
            paper_size = requested["cad_size"]
            if paper_size not in CAD_SIZES:
                flash("Choose a valid CAD drawing size for every item.", "error")
                return redirect(url_for("new_order"))
            paper_type = requested["paper_type"]
            if paper_type not in CAD_PAPER_TYPES:
                flash("Choose a valid paper type for every CAD item.", "error")
                return redirect(url_for("new_order"))
            if paper_size == "Custom" and not notes:
                flash("Add the required extra notes for a custom CAD size.", "error")
                return redirect(url_for("new_order"))
            print_type = "cad"
            print_sides = None
            price_each_paise = None
            sheet_count = None
            estimate_paise = None
        if category == "digital_printing":
            paper_type = None
        documents = []
        for uploaded in requested["uploads"]:
            original_name = secure_filename(uploaded.filename)
            extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
            if not original_name or extension not in ALLOWED_EXTENSIONS:
                flash("Upload PDF, Word, JPG, or PNG documents only.", "error")
                return redirect(url_for("new_order"))
            stored_name = (
                f"{order_tracking_id}_{item_index + 1}_"
                f"{secure_filename(paper_size)}_{copies}_"
                f"{len(documents) + 1}.{extension}"
            )
            display_name = f"{order_tracking_id}_{item_index + 1}_{original_name}"
            documents.append({
                "document_name": original_name,
                "display_name": display_name,
                "stored_name": stored_name,
                "item_index": item_index,
            })
            saved_paths.append((uploaded, UPLOAD_FOLDER / stored_name))
        items.append({
            "product_category": category,
            "documents": documents,
            "file_count": len(documents),
            "copies": copies,
            "print_type": print_type,
            "print_sides": print_sides,
            "sheet_count": sheet_count,
            "paper_size": paper_size,
            "paper_type": paper_type,
            "price_each_paise": price_each_paise,
            "estimate_paise": estimate_paise,
            "notes": notes,
        })

    categories = {item["product_category"] for item in items}
    contains_cad = "cad" in categories
    category = next(iter(categories)) if len(categories) == 1 else "mixed"
    documents = [document for item in items for document in item["documents"]]
    file_count = len(documents)
    digital_estimate_paise = sum(item["estimate_paise"] or 0 for item in items)
    quote_paise = None if contains_cad else digital_estimate_paise + delivery_fee_paise
    status = "pending_quote" if contains_cad else "awaiting_payment"
    distinct_sizes = {item["paper_size"] for item in items}
    paper_size = next(iter(distinct_sizes)) if len(distinct_sizes) == 1 else "Multiple"
    copies = items[0]["copies"] if len({item["copies"] for item in items}) == 1 else 1
    sheet_count = sum(item["sheet_count"] or 0 for item in items)
    notes = "\n".join(item["notes"] for item in items if item["notes"])
    if contains_cad:
        cad_count = sum(item["product_category"] == "cad" for item in items)
        initial_note = (
            f"Order received with {len(items)} item(s), including {cad_count} CAD item(s). "
            "Waiting for a quotation for the full cart."
        )
        print_label = "mixed CAD and digital" if "digital_printing" in categories else "CAD"
    else:
        initial_note = f"Digital printing estimate: ₹{quote_paise / 100:,.2f} across {len(items)} item(s)."
        if delivery_fee_paise:
            initial_note += f" Includes ₹{delivery_fee_paise / 100:,.2f} delivery."
        print_label = "digital printing"

    order = {
        "_id": order_id,
        "tracking_id": order_tracking_id,
        "user_id": g.user["_id"],
        "customer_name": g.user["name"],
        "billing_customer": {
            "name": g.user["name"],
            "phone": g.user.get("whatsapp_number", ""),
            "address": (
                delivery_address
                if delivery_type == "delivery"
                else g.user.get("address", "")
            ),
        },
        "items": items,
        "documents": documents,
        "file_count": file_count,
        "document_name": documents[0]["document_name"],
        "display_name": (
            documents[0]["display_name"]
            if len(documents) == 1
            else f"{len(documents)} documents"
        ),
        "stored_name": documents[0]["stored_name"],
        "copies": copies,
        "product_category": category,
        "contains_cad": contains_cad,
        "print_type": items[0]["print_type"] if len(items) == 1 else None,
        "print_sides": items[0]["print_sides"] if len(items) == 1 else None,
        "sheet_count": sheet_count,
        "paper_size": paper_size,
        "price_each_paise": items[0]["price_each_paise"] if len(items) == 1 else None,
        "delivery_type": delivery_type,
        "delivery_address": delivery_address,
        "delivery_fee_paise": delivery_fee_paise,
        "digital_estimate_paise": digital_estimate_paise,
        "notes": notes,
        "created_at": datetime.now(timezone.utc),
        "status": status,
        "updates": [order_update(status, initial_note)],
        "quote_paise": quote_paise,
        "payment_method": "upi",
        "payment_reference": None,
    }
    try:
        for uploaded, path in saved_paths:
            uploaded.save(path)
        get_database().orders.insert_one(order)
    except (OSError, PyMongoError):
        for _, path in saved_paths:
            path.unlink(missing_ok=True)
        raise
    if (
        delivery_type == "delivery"
        and request.form.get("save_address") == "yes"
        and request.form.get("delivery_address_choice") == "__new__"
    ):
        address_update = {"$addToSet": {"addresses": delivery_address}}
        if not g.user.get("address"):
            address_update["$set"] = {"address": delivery_address}
        database.users.update_one(
            {"_id": g.user["_id"], "role": "customer"},
            address_update,
        )
    notify_admin(
        f"New {print_label} order {order_tracking_id} from {g.user['name']}: "
        f"{len(items)} cart item(s), {file_count} document(s), "
        f"{delivery_type}."
    )
    flash(
        "CAD Master will review the CAD items and send you a quotation."
        if contains_cad
        else "Your order is ready for payment.",
        "order-sent",
    )
    return redirect(url_for("dashboard"))


@app.post("/admin/orders/<order_id>/quote")
@admin_required
def update_quote(order_id):
    database = get_database()
    query = {
        "_id": ObjectId(order_id),
        "$or": [
            {"contains_cad": True},
            {"product_category": {"$ne": "digital_printing"}},
        ],
        "status": {"$in": ["pending_quote", "awaiting_payment"]},
    }
    timestamp = datetime.now(timezone.utc)
    order = database.orders.find_one(query)
    if not order:
        abort(404)
    items = order_items(order)
    item_quote_per_copy_values = []
    try:
        for index, item in enumerate(items):
            raw_quote = request.form.get(f"item_quote_{index}", "").strip()
            if not raw_quote and len(items) == 1:
                raw_quote = request.form.get("amount", "").strip()
            amount = Decimal(raw_quote)
            if not amount.is_finite() or amount <= 0:
                raise InvalidOperation
            amount = amount.quantize(Decimal("0.01"))
            rate_paise = int(amount * 100)
            item_quote_per_copy_values.append(rate_paise)
    except (InvalidOperation, ValueError):
        flash("Enter a valid quotation greater than zero for every cart item.", "error")
        return redirect(url_for("dashboard"))

    try:
        additional_charges = Decimal(
            request.form.get("additional_charges", "0").strip() or "0"
        ).quantize(Decimal("0.01"))
        delivery_charges = Decimal(
            request.form.get("delivery_charges", "0").strip() or "0"
        ).quantize(Decimal("0.01"))
        if (
            not additional_charges.is_finite()
            or not delivery_charges.is_finite()
            or additional_charges < 0
            or delivery_charges < 0
        ):
            raise InvalidOperation
        additional_charges_paise = int(additional_charges * 100)
        delivery_charges_paise = int(delivery_charges * 100)
    except (InvalidOperation, ValueError):
        flash("Additional and delivery charges must be zero or more.", "error")
        return redirect(url_for("dashboard"))

    item_quote_paise = [
        rate_paise * item_copy_count(item)
        for item, rate_paise in zip(items, item_quote_per_copy_values)
    ]
    for item, rate_paise, amount_paise in zip(
        items, item_quote_per_copy_values, item_quote_paise
    ):
        item["quote_per_copy_paise"] = rate_paise
        item["quote_paise"] = amount_paise
    quote_paise = (
        sum(item_quote_paise)
        + additional_charges_paise
        + delivery_charges_paise
    )
    update_values = {
        "items": items,
        "quote_paise": quote_paise,
        "additional_charges_paise": additional_charges_paise,
        "quoted_delivery_charges_paise": delivery_charges_paise,
        "status": "awaiting_payment",
        "quoted_at": timestamp,
    }
    result = database.orders.update_one(
        query,
        {
            "$set": update_values,
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
    flash("The customer can now pay by UPI.", "quote-sent")
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
            for print_sides in PRINT_SIDES:
                field_name = f"rate_{size}_{print_type}_{print_sides}"
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
                updates.append((size, print_type, print_sides, price_paise))

    database = get_database()
    timestamp = datetime.now(timezone.utc)
    for size, print_type, print_sides, price_paise in updates:
        query = {
            "service": "digital_printing",
            "size": size,
            "print_type": print_type,
            "print_sides": print_sides,
        }
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
                "addresses": [address[:500]],
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


@app.get("/admin/customers")
@admin_required
def customers():
    customer_list = list(
        get_database()
        .users.find({"role": "customer"}, {"password_hash": 0})
        .sort("name", 1)
        .limit(500)
    )
    return render_template("customers.html", customers=customer_list)


@app.post("/admin/customers/<customer_id>/password")
@admin_required
def update_customer_password(customer_id):
    try:
        user_id = ObjectId(customer_id)
    except (InvalidId, TypeError):
        abort(404)
    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")
    if len(password) < 8:
        flash("Customer passwords must be at least 8 characters.", "error")
        return redirect(url_for("customers"))
    if password != password_confirm:
        flash("The passwords do not match.", "error")
        return redirect(url_for("customers"))
    database = get_database()
    result = database.users.update_one(
        {"_id": user_id, "role": "customer"},
        {"$set": {"password_hash": generate_password_hash(password)}},
    )
    if not result.matched_count:
        abort(404)
    database.login_sessions.update_many(
        {"user_id": user_id, "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc)}},
    )
    flash("Customer password updated. Their active sessions have been signed out.", "success")
    return redirect(url_for("customers"))


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
    if current_status == "pending_quote" or current_status not in FULFILLMENT_RANK:
        flash("Fulfillment updates are available after payment.", "error")
        return redirect(url_for("dashboard"))
    if next_status not in FULFILLMENT_RANK:
        flash("Choose a valid order status.", "error")
        return redirect(url_for("dashboard"))
    if current_status in {"awaiting_payment", "payment_submitted"} and next_status not in {
        current_status,
        "paid",
    }:
        flash("Confirm payment before moving the order into production.", "error")
        return redirect(url_for("dashboard"))
    if FULFILLMENT_RANK[next_status] < FULFILLMENT_RANK[current_status]:
        flash("Order status cannot move backwards.", "error")
        return redirect(url_for("dashboard"))
    dispatch_details = request.form.get("dispatch_details", "").strip()[:500]
    if next_status == "out_for_delivery" and not dispatch_details:
        flash("Enter dispatch details before marking the order as dispatched.", "error")
        return redirect(url_for("dashboard"))
    dispatch_details_changed = dispatch_details != order.get("dispatch_details", "")
    raw_expected_date = request.form.get("expected_delivery_date", "").strip()
    expected_delivery_date = None
    if raw_expected_date:
        try:
            expected_delivery_date = datetime.strptime(
                raw_expected_date, "%Y-%m-%d"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            flash("Enter a valid expected delivery date.", "error")
            return redirect(url_for("dashboard"))
    current_expected_date = order.get("expected_delivery_date")
    expected_date_changed = (
        expected_delivery_date.date() if expected_delivery_date else None
    ) != (current_expected_date.date() if current_expected_date else None)
    if (
        next_status == current_status
        and not expected_date_changed
        and not dispatch_details_changed
        and not note
    ):
        flash("Choose a status, dispatch details, expected delivery date, or customer update to change.", "error")
        return redirect(url_for("dashboard"))
    update_fields = {}
    if next_status != current_status:
        update_fields["status"] = next_status
    if (
        FULFILLMENT_RANK[current_status] < FULFILLMENT_RANK["paid"]
        and FULFILLMENT_RANK[next_status] >= FULFILLMENT_RANK["paid"]
    ):
        confirmed_at = datetime.now(timezone.utc)
        update_fields["paid_at"] = confirmed_at
        update_fields["payment_confirmed_by"] = g.user["_id"]
        if not order.get("invoice_number"):
            update_fields.update(
                invoice_fields_for_order(database, order, confirmed_at)
            )
    elif next_status == "confirmed" and not order.get("invoice_number"):
        update_fields.update(
            invoice_fields_for_order(database, order, datetime.now(timezone.utc))
        )
    if next_status == "delivered" and current_status != "delivered":
        update_fields["delivered_at"] = datetime.now(timezone.utc)
    if expected_date_changed:
        if expected_delivery_date:
            update_fields["expected_delivery_date"] = expected_delivery_date
    if dispatch_details_changed:
        if dispatch_details:
            update_fields["dispatch_details"] = dispatch_details
        else:
            update_fields.pop("dispatch_details", None)
    if next_status != current_status and not note:
        note = f"Order status updated to {ORDER_STATUS_LABELS[next_status].lower()}."
    if expected_date_changed:
        date_note = (
            f"Expected delivery: {expected_delivery_date.strftime('%d %b %Y')}."
            if expected_delivery_date
            else "Expected delivery date removed."
        )
        note = f"{note} {date_note}".strip()
    if dispatch_details_changed and dispatch_details:
        note = f"{note} Dispatch details: {dispatch_details}.".strip()
    if not note:
        note = "Order update posted."
    update_query = {"$push": {"updates": order_update(next_status, note)}}
    if update_fields:
        update_query["$set"] = update_fields
    if expected_date_changed and not expected_delivery_date:
        update_query["$unset"] = {"expected_delivery_date": ""}
    if dispatch_details_changed and not dispatch_details:
        update_query.setdefault("$unset", {})["dispatch_details"] = ""
    result = database.orders.update_one(
        {"_id": order["_id"], "status": current_status},
        update_query,
    )
    if not result.matched_count:
        abort(409)
    notify_customer(
        order["user_id"],
        f"Update for order {order.get('tracking_id', order['_id'])}: {ORDER_STATUS_LABELS[next_status]}. {note}",
    )
    flash("Order update posted.", "success")
    return redirect(url_for("dashboard"))


@app.post("/admin/orders/<order_id>/reject")
@admin_required
def reject_order(order_id):
    try:
        order_object_id = ObjectId(order_id)
    except (InvalidId, TypeError):
        abort(404)
    database = get_database()
    order = database.orders.find_one({"_id": order_object_id})
    if not order:
        abort(404)
    if order.get("status") == "rejected":
        delete_rejected_order_files(database, order)
        flash("This order was already rejected; its uploaded files have been deleted.", "success")
        return redirect(url_for("dashboard", order_filter="cancelled"))

    rejected_at = datetime.now(timezone.utc)
    reason = request.form.get("reason", "").strip()[:500]
    note = "Order rejected by CAD Master."
    if reason:
        note += f" Reason: {reason}"
    result = database.orders.update_one(
        {"_id": order_object_id, "status": {"$ne": "rejected"}},
        {
            "$set": {
                "status": "rejected",
                "rejected_at": rejected_at,
                "rejected_by": g.user["_id"],
            },
            "$unset": {
                "invoice_number": "",
                "invoice_generated_at": "",
                "invoice_snapshot": "",
            },
            "$push": {"updates": order_update("rejected", note)},
        },
    )
    if not result.matched_count:
        abort(409)
    delete_rejected_order_files(database, order)
    notify_customer(
        order["user_id"],
        f"Your order {order.get('tracking_id', order['_id'])} was rejected by CAD Master."
        + (f" Reason: {reason}" if reason else ""),
    )
    flash("Order rejected. Any issued bill has been voided and removed.", "success")
    return redirect(url_for("dashboard", order_filter="cancelled"))


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
@app.get("/orders/<order_id>/documents/<int:document_index>")
@login_required
def download_document(order_id, document_index=None):
    order = get_database().orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        abort(404)
    if g.user["role"] != "admin" and order["user_id"] != g.user["_id"]:
        abort(403)
    preview = request.args.get("preview") == "1"
    documents = order_documents(order)
    if document_index is None:
        document_index = 0
    if document_index >= len(documents):
        abort(404)
    document = documents[document_index]
    if document.get("file_deleted"):
        abort(410, description="This file was deleted by an administrator.")
    return send_from_directory(
        UPLOAD_FOLDER,
        document["stored_name"],
        as_attachment=not preview,
        download_name=document["display_name"],
    )


def delivery_address_pdf(order):
    pdf_buffer = io.BytesIO()
    document = SimpleDocTemplate(
        pdf_buffer,
        pagesize=A6,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=f"Delivery address {order.get('tracking_id', order['_id'])}",
    )
    styles = getSampleStyleSheet()
    order_number = escape(str(order.get("tracking_id", order["_id"])))
    customer_name = escape(str(order.get("customer_name", "Customer")))
    address = escape(str(order.get("delivery_address", ""))).replace("\n", "<br/>")
    story = [
        Paragraph("DELIVERY ADDRESS", styles["Title"]),
        Spacer(1, 8 * mm),
        Paragraph(f"<b>Order:</b> {order_number}", styles["BodyText"]),
        Spacer(1, 3 * mm),
        Paragraph(f"<b>Customer:</b> {customer_name}", styles["BodyText"]),
        Spacer(1, 6 * mm),
        Paragraph("<b>Deliver to:</b>", styles["Heading2"]),
        Spacer(1, 2 * mm),
        Paragraph(address, styles["BodyText"]),
    ]
    document.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer.read()


@app.get("/admin/orders/<order_id>/download")
@admin_required
def download_order_files(order_id):
    try:
        order_object_id = ObjectId(order_id)
    except (InvalidId, TypeError):
        abort(404)
    order = get_database().orders.find_one({"_id": order_object_id})
    if not order:
        abort(404)
    documents = order_documents(order)
    if not documents:
        abort(404, description="This order has no files to download.")

    customer_folder = secure_filename(order.get("customer_name", "")) or "customer"
    order_number = secure_filename(
        order.get("tracking_id", str(order["_id"]))
    ) or str(order["_id"])
    folder_name = f"{customer_folder}_{order_number}"
    archive = io.BytesIO()
    upload_root = UPLOAD_FOLDER.resolve()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for document in documents:
            if document.get("file_deleted"):
                continue
            stored_path = (upload_root / document["stored_name"]).resolve()
            if stored_path.parent != upload_root or not stored_path.is_file():
                abort(404, description="One or more files for this order are unavailable.")
            archive_name = secure_filename(Path(document["stored_name"]).name)
            zip_file.write(stored_path, f"{folder_name}/{archive_name}")
        if order.get("delivery_type") == "delivery" and order.get("delivery_address"):
            zip_file.writestr(
                f"{folder_name}/delivery_address_A6.pdf",
                delivery_address_pdf(order),
            )
        if not zip_file.namelist():
            abort(404, description="This order has no available files to download.")
    archive.seek(0)
    return send_file(
        archive,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{folder_name}.zip",
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
    payment_channel = request.form.get("payment_channel", "upi_app")
    if payment_channel not in {"upi_app", "upi_qr"}:
        abort(400)
    payment_reference = request.form.get("payment_reference", "").strip()[:100]
    if payment_channel == "upi_qr" and not payment_reference:
        flash("Enter the transaction ID from your QR payment before submitting.", "error")
        return redirect(url_for("dashboard"))
    note = (
        "Customer reports UPI QR payment sent; awaiting admin confirmation."
        if payment_channel == "upi_qr"
        else "Customer reports UPI payment sent; awaiting admin confirmation."
    )
    if payment_reference:
        note += f" Reference: {payment_reference}."
    result = database.orders.update_one(
        {"_id": order["_id"], "status": "awaiting_payment"},
        {
            "$set": {
                "status": "payment_submitted",
                "payment_method": "upi",
                "payment_channel": payment_channel,
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
    flash("Payment reported. CAD Master will confirm it before processing your order.", "success")
    return redirect(url_for("dashboard"))


@app.post("/admin/orders/<order_id>/confirm-payment")
@admin_required
def confirm_upi_payment(order_id):
    database = get_database()
    order = database.orders.find_one({"_id": ObjectId(order_id), "status": "payment_submitted"})
    if not order:
        abort(404)
    confirmed_at = datetime.now(timezone.utc)
    paid_fields = {
        "status": "paid",
        "paid_at": confirmed_at,
        "payment_confirmed_by": g.user["_id"],
    }
    if not order.get("invoice_number"):
        paid_fields.update(invoice_fields_for_order(database, order, confirmed_at))
    result = database.orders.update_one(
        {"_id": order["_id"], "status": "payment_submitted"},
        {
            "$set": paid_fields,
            "$push": {"updates": order_update("paid", "UPI payment received and confirmed by CAD Master.")},
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
    ssl_context = (HTTPS_CERTIFICATE, HTTPS_PRIVATE_KEY) if HTTPS_CERTIFICATE else None
    app.run(
        debug=app.config["FLASK_DEBUG"],
        ssl_context=ssl_context,
    )