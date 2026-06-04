import os
import json
import urllib.error
import urllib.request
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
import sqlite3
from pathlib import Path


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vanta-local-secret")
DB_PATH = Path(__file__).with_name("vanta.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "vanta123").strip()
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN", "").strip()
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                customer_email TEXT,
                total INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                size TEXT NOT NULL,
                price INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            )
        """)
        ensure_column(connection, "orders", "payment_status", "TEXT DEFAULT 'manual'")
        ensure_column(connection, "orders", "payment_id", "TEXT")
        ensure_column(connection, "orders", "merchant_order_id", "TEXT")
        ensure_column(connection, "orders", "preference_id", "TEXT")


def ensure_column(connection, table_name, column_name, definition):
    columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    if not any(column["name"] == column_name for column in columns):
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def get_public_base_url():
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL

    return request.url_root.rstrip("/")


def save_order(customer, items, payment_status="manual"):
    total = sum(int(item["price"]) * int(item["quantity"]) for item in items)

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO orders (customer_name, customer_phone, customer_email, total, payment_status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                customer["name"],
                customer["phone"],
                customer.get("email", ""),
                total,
                payment_status,
            ),
        )
        order_id = cursor.lastrowid

        for item in items:
            connection.execute(
                """
                INSERT INTO order_items (order_id, product_name, size, price, quantity)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    item["name"],
                    item["size"],
                    int(item["price"]),
                    int(item["quantity"]),
                ),
            )

    return order_id, total


def update_order_payment(order_id, **payment_fields):
    allowed_fields = {"payment_status", "payment_id", "merchant_order_id", "preference_id"}
    fields = {key: value for key, value in payment_fields.items() if key in allowed_fields and value}

    if not fields:
        return

    assignments = ", ".join(f"{field} = ?" for field in fields)
    values = list(fields.values()) + [order_id]

    with get_connection() as connection:
        connection.execute(f"UPDATE orders SET {assignments} WHERE id = ?", values)


def mercadopago_request(path, payload=None, method="GET"):
    if not MERCADO_PAGO_ACCESS_TOKEN:
        raise RuntimeError("Falta configurar MERCADO_PAGO_ACCESS_TOKEN")

    data = None
    headers = {
        "Authorization": f"Bearer {MERCADO_PAGO_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    api_request = urllib.request.Request(
        f"https://api.mercadopago.com{path}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(api_request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Mercado Pago respondio {error.code}: {details}") from error


def update_payment_from_mercadopago(payment_id):
    if not payment_id:
        return

    payment = mercadopago_request(f"/v1/payments/{payment_id}")
    order_id = payment.get("external_reference")

    if not order_id:
        return

    update_order_payment(
        order_id,
        payment_status=payment.get("status"),
        payment_id=str(payment.get("id", "")),
        merchant_order_id=str(payment.get("order", {}).get("id", "")),
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/orders", methods=["POST"])
def create_order():
    data = request.get_json()

    customer = data.get("customer", {})
    items = data.get("items", [])

    if not customer.get("name") or not customer.get("phone"):
        return jsonify({"error": "Faltan nombre o telefono"}), 400

    if not items:
        return jsonify({"error": "El carrito esta vacio"}), 400

    order_id, total = save_order(customer, items)

    return jsonify({
        "message": "Pedido guardado correctamente",
        "order_id": order_id,
        "total": total,
    }), 201


@app.route("/api/checkout", methods=["POST"])
def create_checkout():
    data = request.get_json()

    customer = data.get("customer", {})
    items = data.get("items", [])

    if not customer.get("name") or not customer.get("phone"):
        return jsonify({"error": "Faltan nombre o telefono"}), 400

    if not items:
        return jsonify({"error": "El carrito esta vacio"}), 400

    try:
        order_id, total = save_order(customer, items, payment_status="pending")
        base_url = get_public_base_url()
        preference_payload = {
            "items": [
                {
                    "title": f"{item['name']} - Talle {item['size']}",
                    "quantity": int(item["quantity"]),
                    "unit_price": int(item["price"]),
                    "currency_id": "ARS",
                }
                for item in items
            ],
            "payer": {
                "name": customer["name"],
                "email": customer.get("email", ""),
                "phone": {"number": customer["phone"]},
            },
            "external_reference": str(order_id),
            "back_urls": {
                "success": f"{base_url}/payment/success",
                "failure": f"{base_url}/payment/failure",
                "pending": f"{base_url}/payment/pending",
            },
            "auto_return": "approved",
            "notification_url": f"{base_url}/api/mercadopago/webhook",
            "statement_descriptor": "VANTA",
        }
        preference = mercadopago_request("/checkout/preferences", preference_payload, method="POST")
        update_order_payment(order_id, preference_id=preference.get("id"))

        return jsonify({
            "order_id": order_id,
            "total": total,
            "preference_id": preference.get("id"),
            "init_point": preference.get("init_point"),
            "sandbox_init_point": preference.get("sandbox_init_point"),
        }), 201
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 500


@app.route("/api/mercadopago/webhook", methods=["GET", "POST"])
def mercadopago_webhook():
    payload = request.get_json(silent=True) or {}
    payment_id = (
        request.args.get("data.id")
        or request.args.get("id")
        or payload.get("data", {}).get("id")
        or payload.get("id")
    )
    notification_type = request.args.get("type") or request.args.get("topic") or payload.get("type")

    if payment_id and notification_type in {"payment", "merchant_order", None}:
        try:
            update_payment_from_mercadopago(payment_id)
        except RuntimeError:
            pass

    return jsonify({"ok": True})


@app.route("/payment/<status>")
def payment_result(status):
    payment_id = request.args.get("payment_id")

    if payment_id:
        try:
            update_payment_from_mercadopago(payment_id)
        except RuntimeError:
            pass

    return render_template("payment_result.html", status=status)


@app.route("/api/orders", methods=["GET"])
def list_orders():
    with get_connection() as connection:
        orders = connection.execute(
            "SELECT * FROM orders ORDER BY created_at DESC"
        ).fetchall()

        result = []
        for order in orders:
            items = connection.execute(
                "SELECT product_name, size, price, quantity FROM order_items WHERE order_id = ?",
                (order["id"],),
            ).fetchall()

            result.append({
                "id": order["id"],
                "customer_name": order["customer_name"],
                "customer_phone": order["customer_phone"],
                "customer_email": order["customer_email"],
                "total": order["total"],
                "created_at": order["created_at"],
                "payment_status": order["payment_status"],
                "payment_id": order["payment_id"],
                "preference_id": order["preference_id"],
                "items": [dict(item) for item in items],
            })

    return jsonify(result)


@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    return render_template("admin.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = ""

    if request.method == "POST":
        password = request.form.get("password", "").strip()

        if password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))

        error = "Contrasena incorrecta"

    return render_template("login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("home"))


init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
