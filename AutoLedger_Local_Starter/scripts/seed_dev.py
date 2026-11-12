"""Seed repeatable development fixtures in the explicitly permitted local clone."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
load_dotenv(WORKSPACE_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")

EXPECTED_DATABASE = "autoledger_dev_clone"
DEV_PASSWORD = "AutoLedger-Dev-Only-2026!"
ROLE_NAMES = (
    "Super Admin",
    "Admin",
    "Business Owner",
    "Manager",
    "Accountant",
    "Staff",
    "Viewer",
)
BUSINESSES = ("AutoLedger Dev Business A", "AutoLedger Dev Business B")
USER_EMAILS = {
    role: f"autoledger.seed.{role.lower().replace(' ', '-')}@example.test"
    for role in ROLE_NAMES
}


def _validate_target() -> None:
    database = os.getenv("DB_NAME", "").strip()
    host = os.getenv("DB_HOST", "").strip()
    port = os.getenv("DB_PORT", "").strip()
    if database.casefold() == "autoledger_db":
        raise SystemExit("Refusing to seed the forbidden autoledger_db database.")
    if database != EXPECTED_DATABASE:
        raise SystemExit(
            "Refusing to seed: DB_NAME must be exactly autoledger_dev_clone."
        )
    if host.casefold() not in {"localhost", "127.0.0.1"} or port != "2005":
        raise SystemExit(
            "Refusing to seed: DB_HOST must be localhost and DB_PORT must be 2005."
        )
    if not os.getenv("DB_USER") or not os.getenv("DB_PASSWORD"):
        raise SystemExit("Refusing to seed: DB_USER and DB_PASSWORD must be set.")


def _role_ids(cursor) -> dict[str, int]:
    cursor.execute(
        "SELECT role_name, role_id FROM roles WHERE role_name = ANY(%s)",
        (list(ROLE_NAMES),),
    )
    roles = {row[0]: row[1] for row in cursor.fetchall()}
    missing = set(ROLE_NAMES) - roles.keys()
    if missing:
        raise RuntimeError(f"Required roles are missing from the clone: {sorted(missing)}")
    return roles


def _business_id(cursor, business_name: str) -> int:
    cursor.execute(
        "SELECT business_id FROM businesses WHERE business_name = %s ORDER BY business_id LIMIT 1 FOR UPDATE",
        (business_name,),
    )
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute(
        "INSERT INTO businesses (business_name) VALUES (%s) RETURNING business_id",
        (business_name,),
    )
    return cursor.fetchone()[0]


def _party_id(cursor, table: str, id_column: str, name_column: str, business_id: int, name: str, email: str) -> int:
    cursor.execute(
        f"SELECT {id_column} FROM {table} WHERE business_id = %s AND {name_column} = %s ORDER BY {id_column} LIMIT 1 FOR UPDATE",
        (business_id, name),
    )
    row = cursor.fetchone()
    if row:
        cursor.execute(
            f"UPDATE {table} SET email = %s, is_active = TRUE WHERE {id_column} = %s",
            (email, row[0]),
        )
        return row[0]
    cursor.execute(
        f"""
        INSERT INTO {table} (business_id, {name_column}, email)
        VALUES (%s, %s, %s)
        RETURNING {id_column}
        """,
        (business_id, name, email),
    )
    return cursor.fetchone()[0]


def _vehicle_id(cursor, business_key: str, sequence: int) -> int:
    vin = f"ALDEV{business_key}{sequence:010d}"
    registration = f"AL-DEV-{business_key}-{sequence:02d}"
    cursor.execute(
        """
        INSERT INTO vehicles
            (vin, registration_no, brand, model, model_year, color, fuel_type, transmission, engine_no)
        VALUES (%s, %s, 'AutoLedger', %s, 2025, 'Silver', 'Hybrid', 'Automatic', %s)
        ON CONFLICT (vin) DO UPDATE SET
            registration_no = EXCLUDED.registration_no,
            brand = EXCLUDED.brand,
            model = EXCLUDED.model,
            model_year = EXCLUDED.model_year,
            color = EXCLUDED.color,
            fuel_type = EXCLUDED.fuel_type,
            transmission = EXCLUDED.transmission,
            engine_no = EXCLUDED.engine_no
        RETURNING vehicle_id
        """,
        (
            vin,
            registration,
            f"Demo {sequence}",
            f"ALDEV-ENGINE-{business_key}-{sequence:02d}",
        ),
    )
    return cursor.fetchone()[0]


def _ensure_purchase(
    cursor,
    actor_id: int,
    business_id: int,
    supplier_id: int,
    vehicle_id: int,
    business_key: str,
    sequence: int,
) -> int:
    reference = f"AL-DEV-{business_key}-PUR-{sequence:02d}"
    cursor.execute(
        "SELECT purchase_id FROM purchases WHERE purchase_reference = %s",
        (reference,),
    )
    row = cursor.fetchone()
    if row:
        if row[0] is None:
            raise RuntimeError("Seed purchase lookup returned an invalid row.")
        return row[0]

    cursor.execute("SELECT set_config('app.user_id', %s, true)", (str(actor_id),))
    cursor.execute("SELECT set_config('app.business_id', %s, true)", (str(business_id),))
    price = 1_000_000 + sequence * 100_000
    cursor.execute(
        """
        INSERT INTO purchases
            (business_id, supplier_id, purchase_date, total_amount, purchase_reference, purchase_status)
        VALUES (%s, %s, %s, 0, %s, 'DRAFT')
        RETURNING purchase_id
        """,
        (business_id, supplier_id, date.today(), reference),
    )
    purchase_id = cursor.fetchone()[0]
    cursor.execute(
        """
        INSERT INTO purchase_items
            (business_id, purchase_id, vehicle_id, purchase_price, condition_at_purchase)
        VALUES (%s, %s, %s, %s, 'GOOD')
        """,
        (business_id, purchase_id, vehicle_id, price),
    )
    cursor.execute(
        "UPDATE purchases SET total_amount = %s WHERE purchase_id = %s AND business_id = %s",
        (price, purchase_id, business_id),
    )
    cursor.execute(
        "UPDATE purchases SET purchase_status = 'ORDERED' WHERE purchase_id = %s AND business_id = %s",
        (purchase_id, business_id),
    )
    cursor.execute(
        "UPDATE purchases SET purchase_status = 'RECEIVED' WHERE purchase_id = %s AND business_id = %s",
        (purchase_id, business_id),
    )
    cursor.execute(
        """
        UPDATE vehicle_inventory SET business_id = %s
        WHERE vehicle_id = %s AND business_id IS NULL
        """,
        (business_id, vehicle_id),
    )
    cursor.execute(
        """
        SELECT business_id FROM vehicle_inventory WHERE vehicle_id = %s FOR UPDATE
        """,
        (vehicle_id,),
    )
    inventory = cursor.fetchone()
    if inventory is None or inventory[0] != business_id:
        raise RuntimeError("Seed vehicle inventory is assigned to an unexpected business.")
    return purchase_id


def _ensure_payment(
    cursor,
    actor_id: int,
    business_id: int,
    business_key: str,
    parent_column: str,
    parent_id: int,
    amount: int,
    reference_suffix: str,
) -> int:
    idempotency_key = f"autoledger-dev-{business_key.lower()}-{reference_suffix.lower()}"
    cursor.execute(
        "SELECT payment_id FROM payments WHERE idempotency_key = %s",
        (idempotency_key,),
    )
    row = cursor.fetchone()
    if row:
        return row[0]
    reference = f"AL-DEV-{business_key}-{reference_suffix}"
    cursor.execute("SELECT set_config('app.user_id', %s, true)", (str(actor_id),))
    cursor.execute("SELECT set_config('app.business_id', %s, true)", (str(business_id),))
    cursor.execute(
        f"""
        INSERT INTO payments
            (payment_reference, business_id, {parent_column}, amount, currency,
             payment_kind, payment_status, payment_method, idempotency_key)
        VALUES (%s, %s, %s, %s, 'PKR', 'PAYMENT', 'COMPLETED', 'BANK_TRANSFER', %s)
        RETURNING payment_id
        """,
        (reference, business_id, parent_id, amount, idempotency_key),
    )
    return cursor.fetchone()[0]


def _ensure_sale(
    cursor,
    actor_id: int,
    business_id: int,
    customer_id: int,
    vehicle_id: int,
    business_key: str,
) -> int:
    reference = f"AL-DEV-{business_key}-SAL-01"
    cursor.execute("SELECT sale_id FROM sales WHERE sale_reference = %s", (reference,))
    row = cursor.fetchone()
    if row:
        if row[0] is None:
            raise RuntimeError("Seed sale lookup returned an invalid row.")
        return row[0]

    cursor.execute("SELECT business_id FROM vehicle_inventory WHERE vehicle_id = %s FOR UPDATE", (vehicle_id,))
    inventory = cursor.fetchone()
    if inventory is None or inventory[0] != business_id:
        raise RuntimeError("Seed vehicle is not onboarded to its expected business.")

    cursor.execute("SELECT set_config('app.user_id', %s, true)", (str(actor_id),))
    cursor.execute("SELECT set_config('app.business_id', %s, true)", (str(business_id),))
    sale_total = 1_400_000
    cursor.execute(
        """
        INSERT INTO sales
            (business_id, customer_id, sale_date, total_amount, sale_reference, sale_status)
        VALUES (%s, %s, %s, 0, %s, 'DRAFT')
        RETURNING sale_id
        """,
        (business_id, customer_id, date.today(), reference),
    )
    sale_id = cursor.fetchone()[0]
    cursor.execute(
        """
        INSERT INTO sale_items
            (business_id, sale_id, vehicle_id, selling_price, discount_amount, tax_amount)
        VALUES (%s, %s, %s, %s, 0, 0)
        """,
        (business_id, sale_id, vehicle_id, sale_total),
    )
    cursor.execute(
        "UPDATE sales SET total_amount = %s WHERE sale_id = %s AND business_id = %s",
        (sale_total, sale_id, business_id),
    )
    cursor.execute(
        "UPDATE sales SET sale_status = 'CONFIRMED' WHERE sale_id = %s AND business_id = %s",
        (sale_id, business_id),
    )
    cursor.execute(
        "UPDATE sales SET sale_status = 'COMPLETED' WHERE sale_id = %s AND business_id = %s",
        (sale_id, business_id),
    )
    return sale_id


def seed() -> dict[str, int]:
    _validate_target()

    import psycopg2

    sys.path.insert(0, str(PROJECT_ROOT))
    from backend.auth import hash_password

    connection = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=5,
    )
    counts: dict[str, int] = {}
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), inet_server_port()")
                database, server_port = cursor.fetchone()
                if database != EXPECTED_DATABASE or server_port != 2005:
                    raise RuntimeError("Connected database does not match the permitted local clone.")

                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("autoledger.dev.seed.v1",))
                role_ids = _role_ids(cursor)
                business_ids = {
                    name: _business_id(cursor, name) for name in BUSINESSES
                }
                user_ids: dict[str, int] = {}
                password_hash = hash_password(DEV_PASSWORD)
                for role in ROLE_NAMES:
                    email = USER_EMAILS[role]
                    cursor.execute(
                        """
                        INSERT INTO users (role_id, full_name, email, password_hash, is_active)
                        VALUES (%s, %s, %s, %s, TRUE)
                        ON CONFLICT (email) DO UPDATE SET
                            role_id = EXCLUDED.role_id,
                            full_name = EXCLUDED.full_name,
                            password_hash = EXCLUDED.password_hash,
                            is_active = TRUE
                        RETURNING user_id
                        """,
                        (role_ids[role], f"AutoLedger Dev {role}", email, password_hash),
                    )
                    user_ids[role] = cursor.fetchone()[0]
                    for business_name in BUSINESSES:
                        if business_name == BUSINESSES[1] and role not in {
                            "Super Admin",
                            "Manager",
                        }:
                            continue
                        cursor.execute(
                            """
                            INSERT INTO business_memberships
                                (user_id, business_id, role_id, is_active)
                            VALUES (%s, %s, %s, TRUE)
                            ON CONFLICT (user_id, business_id) DO UPDATE SET
                                role_id = EXCLUDED.role_id,
                                is_active = TRUE
                            """,
                            (
                                user_ids[role],
                                business_ids[business_name],
                                role_ids[role],
                            ),
                        )

                manager_id = user_ids["Manager"]
                for business_key, business_name in zip(("A", "B"), BUSINESSES):
                    business_id = business_ids[business_name]
                    cursor.execute("SELECT set_config('app.user_id', %s, true)", (str(manager_id),))
                    cursor.execute("SELECT set_config('app.business_id', %s, true)", (str(business_id),))
                    supplier_id = _party_id(
                        cursor,
                        "suppliers",
                        "supplier_id",
                        "supplier_name",
                        business_id,
                        f"AutoLedger Dev {business_key} Supplier",
                        f"supplier-{business_key.lower()}@example.test",
                    )
                    customer_id = _party_id(
                        cursor,
                        "customers",
                        "customer_id",
                        "customer_name",
                        business_id,
                        f"AutoLedger Dev {business_key} Customer",
                        f"customer-{business_key.lower()}@example.test",
                    )
                    vehicle_ids = [
                        _vehicle_id(cursor, business_key, sequence)
                        for sequence in (1, 2)
                    ]
                    purchase_ids = [
                        _ensure_purchase(
                            cursor,
                            manager_id,
                            business_id,
                            supplier_id,
                            vehicle_id,
                            business_key,
                            sequence,
                        )
                        for sequence, vehicle_id in enumerate(vehicle_ids, start=1)
                    ]
                    for sequence, purchase_id in enumerate(purchase_ids, start=1):
                        _ensure_payment(
                            cursor,
                            manager_id,
                            business_id,
                            business_key,
                            "purchase_id",
                            purchase_id,
                            500_000,
                            f"PUR-{sequence:02d}-PAY",
                        )
                    sale_id = _ensure_sale(
                        cursor,
                        manager_id,
                        business_id,
                        customer_id,
                        vehicle_ids[0],
                        business_key,
                    )
                    _ensure_payment(
                        cursor,
                        manager_id,
                        business_id,
                        business_key,
                        "sale_id",
                        sale_id,
                        700_000,
                        "SAL-01-PAY",
                    )

                for table, selector, parameter in (
                    ("businesses", "business_name = ANY(%s)", list(BUSINESSES)),
                    ("business_memberships", "user_id = ANY(%s)", list(user_ids.values())),
                    ("suppliers", "supplier_name LIKE %s", "AutoLedger Dev % Supplier"),
                    ("customers", "customer_name LIKE %s", "AutoLedger Dev % Customer"),
                    ("purchases", "purchase_reference LIKE %s", "AL-DEV-%-PUR-%"),
                    ("sales", "sale_reference LIKE %s", "AL-DEV-%-SAL-%"),
                    ("payments", "payment_reference LIKE %s", "AL-DEV-%"),
                ):
                    cursor.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE {selector}",
                        (parameter,),
                    )
                    counts[table] = cursor.fetchone()[0]
                counts["users"] = len(user_ids)
                counts["vehicles"] = 4
        return counts
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        seeded_counts = seed()
    except Exception as error:
        print(f"SEED_FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"SEED_PASS database={EXPECTED_DATABASE} counts={seeded_counts}")
