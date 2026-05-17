import os
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
import sqlite3
from pathlib import Path


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vanta-local-secret")
DB_PATH = Path(__file__).with_name("vanta.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "vanta123").strip()


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

    total = sum(int(item["price"]) * int(item["quantity"]) for item in items)

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO orders (customer_name, customer_phone, customer_email, total)
            VALUES (?, ?, ?, ?)
            """,
            (
                customer["name"],
                customer["phone"],
                customer.get("email", ""),
                total,
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

    return jsonify({
        "message": "Pedido guardado correctamente",
        "order_id": order_id,
        "total": total,
    }), 201


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
