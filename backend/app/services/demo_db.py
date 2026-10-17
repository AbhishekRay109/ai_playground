"""Deterministic demonstration database for the SQL Assistant (``demo.db``).

Tables: customers, products, orders, order_items, monthly_sales. Data is generated from a
fixed random seed so evaluation questions have stable answers.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import (
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    insert,
    select,
)

metadata = MetaData()

customers = Table(
    "customers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("email", String(200), nullable=False),
    Column("city", String(100), nullable=False),
    Column("country", String(100), nullable=False),
    Column("segment", String(20), nullable=False),  # Consumer | SMB | Enterprise
    Column("signup_date", Date, nullable=False),
)

products = Table(
    "products",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("category", String(50), nullable=False),
    Column("unit_price", Float, nullable=False),
    Column("unit_cost", Float, nullable=False),
)

orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
    Column("order_date", Date, nullable=False),
    Column("status", String(20), nullable=False),  # completed | shipped | cancelled | returned
)

order_items = Table(
    "order_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("order_id", Integer, ForeignKey("orders.id"), nullable=False),
    Column("product_id", Integer, ForeignKey("products.id"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Float, nullable=False),
)

monthly_sales = Table(
    "monthly_sales",
    metadata,
    Column("month", String(7), primary_key=True),  # YYYY-MM
    Column("product_id", Integer, ForeignKey("products.id"), primary_key=True),
    Column("units_sold", Integer, nullable=False),
    Column("revenue", Float, nullable=False),
)

PRODUCTS = [
    ("Aurora Laptop 14", "Computers", 1299.0, 910.0),
    ("Aurora Laptop 16", "Computers", 1699.0, 1180.0),
    ("Nimbus Tablet", "Tablets", 549.0, 360.0),
    ("Pulse Smartwatch", "Wearables", 249.0, 140.0),
    ("Echo Wireless Earbuds", "Audio", 129.0, 58.0),
    ("Echo Studio Headphones", "Audio", 299.0, 150.0),
    ('Vertex 27" Monitor', "Displays", 379.0, 240.0),
    ('Vertex 32" 4K Monitor', "Displays", 649.0, 430.0),
    ("Glide Mechanical Keyboard", "Accessories", 119.0, 55.0),
    ("Glide Ergonomic Mouse", "Accessories", 69.0, 28.0),
    ("Dock Pro USB-C Hub", "Accessories", 89.0, 37.0),
    ("Lumen Webcam 4K", "Accessories", 159.0, 80.0),
]
# Relative popularity: earbuds and mice sell most units; laptops earn the most revenue.
POPULARITY = [7, 3, 6, 8, 18, 6, 5, 3, 9, 13, 10, 5]
CITIES = [
    ("Berlin", "Germany"),
    ("Munich", "Germany"),
    ("Paris", "France"),
    ("Lyon", "France"),
    ("London", "United Kingdom"),
    ("Manchester", "United Kingdom"),
    ("Madrid", "Spain"),
    ("Amsterdam", "Netherlands"),
    ("New York", "United States"),
    ("Austin", "United States"),
    ("Toronto", "Canada"),
    ("Bengaluru", "India"),
    ("Singapore", "Singapore"),
    ("Sydney", "Australia"),
]
FIRST = [
    "Ava",
    "Liam",
    "Mia",
    "Noah",
    "Zoe",
    "Omar",
    "Lena",
    "Ravi",
    "Sofia",
    "Kenji",
    "Ines",
    "Tariq",
    "Hana",
    "Lucas",
    "Amara",
    "Jonas",
    "Priya",
    "Mateo",
    "Elif",
    "Chen",
]
LAST = [
    "Schmidt",
    "Martin",
    "Garcia",
    "Patel",
    "Kim",
    "Rossi",
    "Nowak",
    "Silva",
    "Okafor",
    "Larsen",
    "Dubois",
    "Tanaka",
    "Haddad",
    "Novak",
    "Jensen",
    "Moreau",
    "Singh",
    "Costa",
    "Yilmaz",
    "Wang",
]
COMPANIES = [
    "Northwind",
    "Contoso",
    "Fabrikam",
    "Initech",
    "Globex",
    "Umbrella",
    "Hooli",
    "Vandelay",
    "Tyrell",
    "Wayne",
]

START = date(2024, 1, 1)
END = date(2025, 12, 31)


def create_demo_db(path: Path, seed: int = 42, n_customers: int = 120, n_orders: int = 900) -> None:
    """Create and populate the demo database if it does not already contain data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    metadata.create_all(engine)
    with engine.begin() as conn:
        if conn.execute(select(func.count()).select_from(products)).scalar():
            engine.dispose()
            return
        rng = random.Random(seed)
        conn.execute(
            insert(products),
            [
                {"id": i + 1, "name": n, "category": c, "unit_price": p, "unit_cost": k}
                for i, (n, c, p, k) in enumerate(PRODUCTS)
            ],
        )
        cust_rows = []
        for i in range(n_customers):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            segment = rng.choices(["Consumer", "SMB", "Enterprise"], weights=[6, 3, 1])[0]
            name = f"{first} {last}" if segment == "Consumer" else f"{rng.choice(COMPANIES)} {last} {segment}"
            city, country = rng.choice(CITIES)
            cust_rows.append(
                {
                    "id": i + 1,
                    "name": name,
                    "email": f"{first.lower()}.{last.lower()}{i + 1}@example.com",
                    "city": city,
                    "country": country,
                    "segment": segment,
                    "signup_date": START - timedelta(days=rng.randint(0, 700)),
                }
            )
        conn.execute(insert(customers), cust_rows)

        order_rows, item_rows = [], []
        span = (END - START).days
        item_id = 1
        for oid in range(1, n_orders + 1):
            # Mild growth trend and a Q4 seasonal bump.
            day = int(span * (rng.random() ** 0.85))
            odate = START + timedelta(days=day)
            if odate.month in (11, 12) and rng.random() < 0.3:
                odate = odate.replace(day=min(odate.day, 28))
            status = rng.choices(["completed", "shipped", "cancelled", "returned"], weights=[78, 12, 6, 4])[0]
            order_rows.append(
                {"id": oid, "customer_id": rng.randint(1, n_customers), "order_date": odate, "status": status}
            )
            for pid in sorted(
                set(
                    rng.sample(
                        range(1, len(PRODUCTS) + 1), k=rng.choices([1, 2, 3], weights=[6, 3, 1])[0], counts=POPULARITY
                    )
                )
            ):
                qty = rng.choices([1, 2, 3, 5], weights=[70, 18, 8, 4])[0]
                price = PRODUCTS[pid - 1][2]
                if rng.random() < 0.15:  # occasional discount
                    price = round(price * 0.9, 2)
                item_rows.append(
                    {"id": item_id, "order_id": oid, "product_id": pid, "quantity": qty, "unit_price": price}
                )
                item_id += 1
        conn.execute(insert(orders), order_rows)
        conn.execute(insert(order_items), item_rows)

        # monthly_sales is a pre-aggregated table (completed + shipped orders only).
        status_by_order = {o["id"]: o for o in order_rows}
        agg: dict[tuple[str, int], list[float]] = {}
        for it in item_rows:
            o = status_by_order[it["order_id"]]
            if o["status"] not in ("completed", "shipped"):
                continue
            key = (o["order_date"].strftime("%Y-%m"), it["product_id"])
            acc = agg.setdefault(key, [0, 0.0])
            acc[0] += it["quantity"]
            acc[1] += it["quantity"] * it["unit_price"]
        conn.execute(
            insert(monthly_sales),
            [
                {"month": m, "product_id": p, "units_sold": int(v[0]), "revenue": round(v[1], 2)}
                for (m, p), v in sorted(agg.items())
            ],
        )
    engine.dispose()


TABLE_DESCRIPTIONS = {
    "customers": "One row per customer. segment is Consumer, SMB or Enterprise.",
    "products": "Product catalogue with list price (unit_price) and cost (unit_cost) in USD.",
    "orders": "One row per order. status is completed, shipped, cancelled or returned. order_date is YYYY-MM-DD.",
    "order_items": "Line items of orders. unit_price is the price actually charged (may include a discount).",
    "monthly_sales": "Pre-aggregated sales per month (YYYY-MM) and product, counting completed and shipped "
    "orders only. revenue = sum(quantity * unit_price).",
}
