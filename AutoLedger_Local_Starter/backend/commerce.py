import json
import secrets
from decimal import Decimal
from html import escape
from io import BytesIO

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.commerce_schemas import (
    CustomerCreate,
    CustomerListResponse,
    CustomerPatch,
    CustomerResponse,
    InventoryListResponse,
    InventoryOnboard,
    InventoryResponse,
    InventoryStatusUpdate,
    PaymentCreate,
    PaymentListResponse,
    PaymentResponse,
    PaymentStatusUpdate,
    PartnerStatusUpdate,
    PurchaseCreate,
    PurchaseListResponse,
    PurchaseResponse,
    SaleCreate,
    SaleListResponse,
    SaleResponse,
    SupplierCreate,
    SupplierListResponse,
    SupplierPatch,
    SupplierResponse,
)
from backend.database import get_connection
from backend.security import require_business_permissions as require_permissions

router = APIRouter(prefix="/api", tags=["Commerce and inventory"])

COMMERCE_COLUMNS = {
    "purchases": {
        "purchase_reference",
        "purchase_status",
        "received_at",
    },
    "sales": {"sale_reference", "sale_status"},
    "purchase_items": {
        "purchase_item_id",
        "purchase_id",
        "vehicle_id",
        "purchase_price",
        "condition_at_purchase",
    },
    "sale_items": {
        "sale_item_id",
        "sale_id",
        "vehicle_id",
        "selling_price",
        "discount_amount",
        "tax_amount",
        "line_total",
    },
    "vehicle_inventory": {
        "vehicle_id",
        "stock_status",
        "vehicle_condition",
        "asking_price",
        "reserved_for_sale_id",
        "sold_sale_id",
        "source_note",
        "source_reference",
        "status_changed_at",
        "updated_at",
    },
    "payments": {
        "payment_id",
        "payment_reference",
        "purchase_id",
        "sale_id",
        "amount",
        "currency",
        "payment_kind",
        "payment_status",
        "payment_method",
        "payment_date",
        "external_reference",
        "idempotency_key",
    },
}
COMMERCE_TRIGGERS = {
    "trg_p4_purchase_item_guard",
    "trg_p4_purchase_status_guard",
    "trg_p4_receive_purchase_inventory",
    "trg_p4_sale_item_guard",
    "trg_p4_sale_status_guard",
    "trg_p4_apply_sale_inventory",
    "trg_p4_audit_purchases",
    "trg_p4_audit_purchase_items",
    "trg_p4_audit_sales",
    "trg_p4_audit_sale_items",
    "trg_p4_audit_vehicle_inventory",
    "trg_p4_audit_payments",
}


def _require_commerce_schema(cursor) -> None:
    cursor.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
        """,
        (list(COMMERCE_COLUMNS),),
    )
    existing_columns: dict[str, set[str]] = {}
    for row in cursor.fetchall():
        existing_columns.setdefault(row["table_name"], set()).add(row["column_name"])

    missing_columns = [
        f"{table}.{column}"
        for table, columns in COMMERCE_COLUMNS.items()
        for column in columns - existing_columns.get(table, set())
    ]
    if missing_columns:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Commerce schema is not installed. Database migrations are "
                "proposed only and require separate approval."
            ),
        )

    cursor.execute(
        """
        SELECT tgname
        FROM pg_trigger
        WHERE tgrelid IN (
            'public.purchases'::regclass,
            'public.purchase_items'::regclass,
            'public.sales'::regclass,
            'public.sale_items'::regclass,
            'public.vehicle_inventory'::regclass,
            'public.payments'::regclass
        )
          AND NOT tgisinternal
        """
    )
    existing_triggers = {row["tgname"] for row in cursor.fetchall()}
    if COMMERCE_TRIGGERS - existing_triggers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Commerce workflow and audit triggers are not installed. "
                "Database migrations are proposed only and require separate approval."
            ),
        )


def _require_partner_lifecycle(cursor, table_name: str) -> None:
    if table_name not in {"customers", "suppliers"}:
        raise ValueError("Unsupported partner table.")
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
              AND column_name = 'is_active'
        ) AS installed
        """,
        (table_name,),
    )
    if not cursor.fetchone()["installed"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Partner deactivation requires the separately approved Phase 7 migration.",
        )


def _set_actor(cursor, user_id: int) -> None:
    cursor.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))


def _set_business(cursor, business_id: int) -> None:
    cursor.execute("SELECT set_config('app.business_id', %s, true)", (str(business_id),))


def _include_unassigned(user) -> bool:
    return user["role_name"] == "Super Admin"


def _audit(
    cursor,
    user_id: int,
    business_id: int,
    action: str,
    entity_name: str,
    entity_id: int,
    fields: list[str],
) -> None:
    _set_actor(cursor, user_id)
    _set_business(cursor, business_id)
    cursor.execute(
        """
        INSERT INTO audit_logs (user_id, business_id, action, entity_name, entity_id, details)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (user_id, business_id, action, entity_name, entity_id, json.dumps({"fields": fields})),
    )


def _translate_integrity_error(exc: psycopg2.IntegrityError) -> None:
    if isinstance(exc, psycopg2.errors.UniqueViolation):
        raise HTTPException(status_code=409, detail="A record with the supplied reference or vehicle already exists.") from exc
    if isinstance(exc, psycopg2.errors.ForeignKeyViolation):
        raise HTTPException(status_code=422, detail="A referenced supplier, customer, vehicle, or transaction does not exist.") from exc
    if isinstance(exc, psycopg2.errors.CheckViolation):
        raise HTTPException(status_code=409, detail=str(exc.diag.message_primary)) from exc
    if isinstance(exc, psycopg2.errors.NotNullViolation):
        raise HTTPException(status_code=422, detail=f"Required field missing: {exc.diag.column_name}.") from exc
    raise exc


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _reference(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(12).upper()}"


def _payment_totals(
    cursor,
    parent_kind: str,
    parent_id: int,
    business_id: int,
    include_unassigned: bool = False,
) -> tuple[Decimal, Decimal]:
    parent_column = "purchase_id" if parent_kind == "purchase" else "sale_id"
    cursor.execute(
        sql.SQL(
            """
            SELECT
                COALESCE(SUM(amount) FILTER (
                    WHERE payment_status = 'COMPLETED' AND payment_kind = 'PAYMENT'
                ), 0) -
                COALESCE(SUM(amount) FILTER (
                    WHERE payment_status = 'COMPLETED' AND payment_kind = 'REFUND'
                ), 0) AS settled,
                COALESCE(SUM(amount) FILTER (
                    WHERE payment_status = 'PENDING' AND payment_kind = 'PAYMENT'
                ), 0) AS pending
            FROM payments
            WHERE {} = %s
              AND (business_id = %s OR (business_id IS NULL AND %s))
            """
        ).format(sql.Identifier(parent_column)),
        (parent_id, business_id, include_unassigned),
    )
    row = cursor.fetchone()
    return Decimal(row["settled"]), Decimal(row["pending"])


def _parent_total(
    cursor,
    parent_kind: str,
    parent_id: int,
    business_id: int,
    lock: bool = False,
    include_unassigned: bool = False,
) -> Decimal:
    table = "purchases" if parent_kind == "purchase" else "sales"
    id_column = "purchase_id" if parent_kind == "purchase" else "sale_id"
    cursor.execute(
        sql.SQL(
            "SELECT total_amount FROM {} WHERE {} = %s "
            "AND (business_id = %s OR (business_id IS NULL AND %s)){}"
        ).format(
            sql.Identifier(table),
            sql.Identifier(id_column),
            sql.SQL(" FOR UPDATE") if lock else sql.SQL(""),
        ),
        (parent_id, business_id, include_unassigned),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{parent_kind.title()} not found.")
    if row["total_amount"] is None:
        raise HTTPException(status_code=409, detail="The transaction total is not available.")
    return Decimal(row["total_amount"])


def _assert_payment_fits(
    cursor,
    parent_kind: str,
    parent_id: int,
    business_id: int,
    amount: Decimal,
    payment_status: str,
    exclude_payment_id: int | None = None,
) -> None:
    total = _parent_total(cursor, parent_kind, parent_id, business_id, lock=True)
    settled, pending = _payment_totals(cursor, parent_kind, parent_id, business_id)
    if exclude_payment_id is not None:
        cursor.execute(
            "SELECT amount, payment_status FROM payments WHERE payment_id = %s AND business_id = %s",
            (exclude_payment_id, business_id),
        )
        current = cursor.fetchone()
        if current and current["payment_status"] == "PENDING":
            pending -= Decimal(current["amount"])

    if payment_status in ("COMPLETED", "PENDING") and amount > total - settled - pending:
        raise HTTPException(
            status_code=409,
            detail="Payment exceeds the remaining amount after completed and pending payments.",
        )


def _insert_payment(
    cursor,
    parent_kind: str,
    parent_id: int,
    amount: Decimal,
    payment_method: str,
    payment_status: str,
    user_id: int,
    business_id: int,
    external_reference: str | None = None,
    idempotency_key: str | None = None,
) -> int:
    _assert_payment_fits(cursor, parent_kind, parent_id, business_id, amount, payment_status)
    parent_column = "purchase_id" if parent_kind == "purchase" else "sale_id"
    _set_actor(cursor, user_id)
    _set_business(cursor, business_id)
    cursor.execute(
        sql.SQL(
            """
            INSERT INTO payments
                (payment_reference, business_id, {}, amount, currency, payment_kind,
                 payment_status, payment_method, external_reference, idempotency_key)
            VALUES (%s, %s, %s, %s, 'PKR', 'PAYMENT', %s, %s, %s, %s)
            RETURNING payment_id
            """
        ).format(sql.Identifier(parent_column)),
        (
            _reference("PAY"),
            business_id,
            parent_id,
            amount,
            payment_status,
            payment_method,
            external_reference,
            idempotency_key,
        ),
    )
    payment_id = cursor.fetchone()["payment_id"]
    _set_actor(cursor, user_id)
    _set_business(cursor, business_id)
    return payment_id


def _purchase_response(
    cursor,
    purchase_id: int,
    business_id: int,
    include_items: bool,
    include_unassigned: bool = False,
) -> dict:
    cursor.execute(
        """
        SELECT p.purchase_id, p.supplier_id, s.supplier_name, p.purchase_date,
               p.purchase_reference, p.purchase_status, p.received_at,
               p.total_amount,
               COALESCE((
                   SELECT SUM(CASE WHEN pm.payment_kind = 'PAYMENT' THEN pm.amount ELSE -pm.amount END)
                   FROM payments pm
                   WHERE pm.purchase_id = p.purchase_id
                     AND pm.business_id IS NOT DISTINCT FROM p.business_id
                     AND pm.payment_status = 'COMPLETED'
               ), 0) AS paid_amount
        FROM purchases p
        LEFT JOIN suppliers s
          ON s.supplier_id = p.supplier_id
         AND s.business_id IS NOT DISTINCT FROM p.business_id
        WHERE p.purchase_id = %s
          AND (p.business_id = %s OR (p.business_id IS NULL AND %s))
        """,
        (purchase_id, business_id, include_unassigned),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Purchase not found.")
    result = dict(row)
    total = Decimal(result["total_amount"] or 0)
    paid = Decimal(result["paid_amount"] or 0)
    result["paid_amount"] = paid
    result["balance_due"] = max(total - paid, Decimal("0.00"))
    result["items"] = []
    if include_items:
        cursor.execute(
            """
            SELECT pi.purchase_item_id, pi.vehicle_id, v.vin, v.registration_no,
                   pi.purchase_price, pi.condition_at_purchase
            FROM purchase_items pi
            JOIN vehicles v USING (vehicle_id)
            WHERE pi.purchase_id = %s
              AND pi.business_id IS NOT DISTINCT FROM
                  (SELECT p.business_id FROM purchases p WHERE p.purchase_id = %s)
            ORDER BY pi.purchase_item_id
            """,
            (purchase_id, purchase_id),
        )
        result["items"] = [dict(item) for item in cursor.fetchall()]
    return result


def _sale_response(
    cursor,
    sale_id: int,
    business_id: int,
    include_items: bool,
    include_unassigned: bool = False,
) -> dict:
    cursor.execute(
        """
        SELECT s.sale_id, s.customer_id, c.customer_name, s.sale_date,
               s.sale_reference, s.sale_status, s.total_amount,
               COALESCE((
                   SELECT SUM(CASE WHEN pm.payment_kind = 'PAYMENT' THEN pm.amount ELSE -pm.amount END)
                   FROM payments pm
                   WHERE pm.sale_id = s.sale_id
                     AND pm.business_id IS NOT DISTINCT FROM s.business_id
                     AND pm.payment_status = 'COMPLETED'
               ), 0) AS paid_amount
        FROM sales s
        LEFT JOIN customers c
          ON c.customer_id = s.customer_id
         AND c.business_id IS NOT DISTINCT FROM s.business_id
        WHERE s.sale_id = %s
          AND (s.business_id = %s OR (s.business_id IS NULL AND %s))
        """,
        (sale_id, business_id, include_unassigned),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Sale not found.")
    result = dict(row)
    total = Decimal(result["total_amount"] or 0)
    paid = Decimal(result["paid_amount"] or 0)
    result["paid_amount"] = paid
    result["balance_due"] = max(total - paid, Decimal("0.00"))
    result["items"] = []
    if include_items:
        cursor.execute(
            """
            SELECT si.sale_item_id, si.vehicle_id, v.vin, v.registration_no,
               v.brand, v.model, si.selling_price, si.discount_amount,
               si.tax_amount, si.line_total
            FROM sale_items si
            JOIN vehicles v USING (vehicle_id)
            WHERE si.sale_id = %s
              AND si.business_id IS NOT DISTINCT FROM
                  (SELECT s.business_id FROM sales s WHERE s.sale_id = %s)
            ORDER BY si.sale_item_id
            """,
            (sale_id, sale_id),
        )
        result["items"] = [dict(item) for item in cursor.fetchall()]
    return result


def _supplier_update(cursor, supplier_id: int, business_id: int, values: dict) -> dict:
    if "supplier_name" in values:
        values["supplier_name"] = values["supplier_name"].strip()
        if not values["supplier_name"]:
            raise HTTPException(status_code=422, detail="supplier_name cannot be blank.")
    for name in ("email", "phone"):
        if name in values:
            values[name] = _normalize_optional(values[name])
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(column)) for column in values
    )
    cursor.execute(
        sql.SQL(
            "UPDATE suppliers SET {} WHERE supplier_id = %s AND business_id = %s "
            "RETURNING supplier_id, supplier_name, phone, email"
        ).format(assignments),
        [*values.values(), supplier_id, business_id],
    )
    result = cursor.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    result = dict(result)
    cursor.execute(
        "SELECT COALESCE((to_jsonb(s)->>'is_active')::boolean, TRUE) AS is_active FROM suppliers s WHERE supplier_id = %s AND business_id = %s",
        (supplier_id, business_id),
    )
    result["is_active"] = cursor.fetchone()["is_active"]
    return result


def _customer_update(cursor, customer_id: int, business_id: int, values: dict) -> dict:
    if "customer_name" in values:
        values["customer_name"] = values["customer_name"].strip()
        if not values["customer_name"]:
            raise HTTPException(status_code=422, detail="customer_name cannot be blank.")
    for name in ("email", "phone"):
        if name in values:
            values[name] = _normalize_optional(values[name])
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(column)) for column in values
    )
    cursor.execute(
        sql.SQL(
            "UPDATE customers SET {} WHERE customer_id = %s AND business_id = %s "
            "RETURNING customer_id, customer_name, phone, email"
        ).format(assignments),
        [*values.values(), customer_id, business_id],
    )
    result = cursor.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    result = dict(result)
    cursor.execute(
        "SELECT COALESCE((to_jsonb(c)->>'is_active')::boolean, TRUE) AS is_active FROM customers c WHERE customer_id = %s AND business_id = %s",
        (customer_id, business_id),
    )
    result["is_active"] = cursor.fetchone()["is_active"]
    return result


def _update_partner_active(
    cursor,
    table_name: str,
    id_column: str,
    record_id: int,
    business_id: int,
    is_active: bool,
) -> dict:
    if table_name not in {"customers", "suppliers"}:
        raise ValueError("Unsupported partner table.")
    cursor.execute(
        sql.SQL(
            """
            UPDATE {} SET is_active = %s
            WHERE {} = %s AND business_id = %s
            RETURNING {}, {}, phone, email, is_active
            """
        ).format(
            sql.Identifier(table_name),
            sql.Identifier(id_column),
            sql.Identifier(id_column),
            sql.Identifier(f"{table_name[:-1]}_name"),
        ),
        (is_active, record_id, business_id),
    )
    row = cursor.fetchone()
    if row is None:
        label = "Supplier" if table_name == "suppliers" else "Customer"
        raise HTTPException(status_code=404, detail=f"{label} not found.")
    return dict(row)


@router.get("/suppliers", response_model=SupplierListResponse)
def list_suppliers(
    q: str = Query(default="", max_length=100),
    include_inactive: bool = False,
    user=Depends(require_permissions("suppliers.read")),
):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            term = f"%{q.strip()}%"
            cur.execute(
                """
                SELECT supplier_id, supplier_name, phone, email,
                       COALESCE((to_jsonb(s)->>'is_active')::boolean, TRUE) AS is_active
                FROM suppliers s
                WHERE (s.business_id = %s OR (s.business_id IS NULL AND %s))
                  AND (%s OR COALESCE((to_jsonb(s)->>'is_active')::boolean, TRUE))
                  AND (%s = '' OR supplier_name ILIKE %s OR phone ILIKE %s OR email ILIKE %s)
                ORDER BY supplier_name, supplier_id
                """,
                (
                    user["business_id"],
                    _include_unassigned(user),
                    include_inactive,
                    q.strip(),
                    term,
                    term,
                    term,
                ),
            )
            return {"suppliers": cur.fetchall()}
    finally:
        conn.close()


@router.post("/suppliers", status_code=201, response_model=SupplierResponse)
def create_supplier(payload: SupplierCreate, user=Depends(require_permissions("suppliers.manage"))):
    name = payload.supplier_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="supplier_name cannot be blank.")
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                cur.execute(
                    """
                    INSERT INTO suppliers (business_id, supplier_name, phone, email)
                    VALUES (%s, %s, %s, %s)
                    RETURNING supplier_id, supplier_name, phone, email
                    """,
                    (user["business_id"], name, _normalize_optional(payload.phone), _normalize_optional(payload.email)),
                )
                supplier = dict(cur.fetchone())
                _audit(cur, user["user_id"], user["business_id"], "INSERT", "suppliers", supplier["supplier_id"], ["supplier_name", "phone", "email"])
        return supplier
    except psycopg2.IntegrityError as exc:
        _translate_integrity_error(exc)
    finally:
        conn.close()


@router.get("/suppliers/{supplier_id}", response_model=SupplierResponse)
def get_supplier(supplier_id: int, user=Depends(require_permissions("suppliers.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT supplier_id, supplier_name, phone, email,
                       COALESCE((to_jsonb(s)->>'is_active')::boolean, TRUE) AS is_active
                FROM suppliers s
                WHERE supplier_id = %s
                  AND (business_id = %s OR (business_id IS NULL AND %s))
                """,
                (supplier_id, user["business_id"], _include_unassigned(user)),
            )
            supplier = cur.fetchone()
        if supplier is None:
            raise HTTPException(status_code=404, detail="Supplier not found.")
        return dict(supplier)
    finally:
        conn.close()


@router.get("/suppliers/{supplier_id}/purchases")
def supplier_purchase_history(supplier_id: int, user=Depends(require_permissions("suppliers.read", "purchases.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            cur.execute(
                """
                SELECT supplier_id FROM suppliers
                WHERE supplier_id = %s
                  AND (business_id = %s OR (business_id IS NULL AND %s))
                """,
                (supplier_id, user["business_id"], _include_unassigned(user)),
            )
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Supplier not found.")
            cur.execute(
                """
                SELECT purchase_id FROM purchases
                WHERE supplier_id = %s
                  AND (business_id = %s OR (business_id IS NULL AND %s))
                ORDER BY purchase_date DESC, purchase_id DESC
                """,
                (supplier_id, user["business_id"], _include_unassigned(user)),
            )
            purchases = [
                _purchase_response(
                    cur,
                    row["purchase_id"],
                    user["business_id"],
                    True,
                    _include_unassigned(user),
                )
                for row in cur.fetchall()
            ]
        return {"supplier_id": supplier_id, "purchases": purchases}
    finally:
        conn.close()


@router.patch("/suppliers/{supplier_id}", response_model=SupplierResponse)
def update_supplier(supplier_id: int, payload: SupplierPatch, user=Depends(require_permissions("suppliers.manage"))):
    values = payload.model_dump(exclude_unset=True)
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                supplier = _supplier_update(cur, supplier_id, user["business_id"], values)
                _audit(cur, user["user_id"], user["business_id"], "UPDATE", "suppliers", supplier_id, list(values))
        return supplier
    except psycopg2.IntegrityError as exc:
        _translate_integrity_error(exc)
    finally:
        conn.close()


@router.patch("/suppliers/{supplier_id}/active", response_model=SupplierResponse)
def set_supplier_active(
    supplier_id: int,
    payload: PartnerStatusUpdate,
    user=Depends(require_permissions("suppliers.manage")),
):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _require_partner_lifecycle(cur, "suppliers")
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                supplier = _update_partner_active(cur, "suppliers", "supplier_id", supplier_id, user["business_id"], payload.is_active)
                _audit(cur, user["user_id"], user["business_id"], "UPDATE", "suppliers", supplier_id, ["is_active"])
        return supplier
    finally:
        conn.close()


@router.get("/customers", response_model=CustomerListResponse)
def list_customers(
    q: str = Query(default="", max_length=100),
    include_inactive: bool = False,
    user=Depends(require_permissions("customers.read")),
):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            term = f"%{q.strip()}%"
            cur.execute(
                """
                SELECT customer_id, customer_name, phone, email,
                       COALESCE((to_jsonb(c)->>'is_active')::boolean, TRUE) AS is_active
                FROM customers c
                WHERE (c.business_id = %s OR (c.business_id IS NULL AND %s))
                  AND (%s OR COALESCE((to_jsonb(c)->>'is_active')::boolean, TRUE))
                  AND (%s = '' OR customer_name ILIKE %s OR phone ILIKE %s OR email ILIKE %s)
                ORDER BY customer_name, customer_id
                """,
                (
                    user["business_id"],
                    _include_unassigned(user),
                    include_inactive,
                    q.strip(),
                    term,
                    term,
                    term,
                ),
            )
            return {"customers": cur.fetchall()}
    finally:
        conn.close()


@router.post("/customers", status_code=201, response_model=CustomerResponse)
def create_customer(payload: CustomerCreate, user=Depends(require_permissions("customers.manage"))):
    name = payload.customer_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="customer_name cannot be blank.")
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                cur.execute(
                    """
                    INSERT INTO customers (business_id, customer_name, phone, email)
                    VALUES (%s, %s, %s, %s)
                    RETURNING customer_id, customer_name, phone, email
                    """,
                    (user["business_id"], name, _normalize_optional(payload.phone), _normalize_optional(payload.email)),
                )
                customer = dict(cur.fetchone())
                _audit(cur, user["user_id"], user["business_id"], "INSERT", "customers", customer["customer_id"], ["customer_name", "phone", "email"])
        return customer
    except psycopg2.IntegrityError as exc:
        _translate_integrity_error(exc)
    finally:
        conn.close()


@router.get("/customers/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: int, user=Depends(require_permissions("customers.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT customer_id, customer_name, phone, email,
                       COALESCE((to_jsonb(c)->>'is_active')::boolean, TRUE) AS is_active
                FROM customers c
                WHERE customer_id = %s
                  AND (business_id = %s OR (business_id IS NULL AND %s))
                """,
                (customer_id, user["business_id"], _include_unassigned(user)),
            )
            customer = cur.fetchone()
        if customer is None:
            raise HTTPException(status_code=404, detail="Customer not found.")
        return dict(customer)
    finally:
        conn.close()


@router.get("/customers/{customer_id}/sales")
def customer_sales_history(customer_id: int, user=Depends(require_permissions("customers.read", "sales.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            cur.execute(
                """
                SELECT customer_id FROM customers
                WHERE customer_id = %s
                  AND (business_id = %s OR (business_id IS NULL AND %s))
                """,
                (customer_id, user["business_id"], _include_unassigned(user)),
            )
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Customer not found.")
            cur.execute(
                """
                SELECT sale_id FROM sales
                WHERE customer_id = %s
                  AND (business_id = %s OR (business_id IS NULL AND %s))
                ORDER BY sale_date DESC, sale_id DESC
                """,
                (customer_id, user["business_id"], _include_unassigned(user)),
            )
            sales = [
                _sale_response(
                    cur,
                    row["sale_id"],
                    user["business_id"],
                    True,
                    _include_unassigned(user),
                )
                for row in cur.fetchall()
            ]
        return {"customer_id": customer_id, "sales": sales}
    finally:
        conn.close()


@router.patch("/customers/{customer_id}", response_model=CustomerResponse)
def update_customer(customer_id: int, payload: CustomerPatch, user=Depends(require_permissions("customers.manage"))):
    values = payload.model_dump(exclude_unset=True)
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                customer = _customer_update(cur, customer_id, user["business_id"], values)
                _audit(cur, user["user_id"], user["business_id"], "UPDATE", "customers", customer_id, list(values))
        return customer
    except psycopg2.IntegrityError as exc:
        _translate_integrity_error(exc)
    finally:
        conn.close()


@router.patch("/customers/{customer_id}/active", response_model=CustomerResponse)
def set_customer_active(
    customer_id: int,
    payload: PartnerStatusUpdate,
    user=Depends(require_permissions("customers.manage")),
):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _require_partner_lifecycle(cur, "customers")
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                customer = _update_partner_active(cur, "customers", "customer_id", customer_id, user["business_id"], payload.is_active)
                _audit(cur, user["user_id"], user["business_id"], "UPDATE", "customers", customer_id, ["is_active"])
        return customer
    finally:
        conn.close()


@router.get("/purchases", response_model=PurchaseListResponse)
def list_purchases(user=Depends(require_permissions("purchases.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            cur.execute(
                """
                SELECT purchase_id FROM purchases
                WHERE (business_id = %s OR (business_id IS NULL AND %s))
                ORDER BY purchase_date DESC, purchase_id DESC
                """,
                (user["business_id"], _include_unassigned(user)),
            )
            ids = [row["purchase_id"] for row in cur.fetchall()]
            purchases = [
                _purchase_response(
                    cur,
                    purchase_id,
                    user["business_id"],
                    False,
                    _include_unassigned(user),
                )
                for purchase_id in ids
            ]
        return {"purchases": purchases}
    finally:
        conn.close()


@router.post("/purchases", status_code=201, response_model=PurchaseResponse)
def create_purchase(payload: PurchaseCreate, user=Depends(require_permissions("purchases.manage"))):
    total = sum((item.purchase_price for item in payload.items), Decimal("0.00"))
    if total > Decimal("9999999999.99"):
        raise HTTPException(status_code=422, detail="Purchase total exceeds the supported amount.")
    reference = payload.purchase_reference.strip() if payload.purchase_reference else _reference("PUR")
    if not reference:
        raise HTTPException(status_code=422, detail="purchase_reference cannot be blank.")

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _require_commerce_schema(cur)
                cur.execute(
                    """
                    SELECT COALESCE((to_jsonb(s)->>'is_active')::boolean, TRUE) AS is_active
                    FROM suppliers s WHERE supplier_id = %s AND business_id = %s
                    """,
                    (payload.supplier_id, user["business_id"]),
                )
                supplier = cur.fetchone()
                if supplier is None:
                    raise HTTPException(status_code=404, detail="Supplier not found.")
                if not supplier["is_active"]:
                    raise HTTPException(status_code=409, detail="Inactive suppliers cannot be used for new purchases.")
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                cur.execute(
                    """
                    INSERT INTO purchases
                        (business_id, supplier_id, purchase_date, total_amount, purchase_reference, purchase_status)
                    VALUES (%s, %s, %s, 0, %s, 'DRAFT')
                    RETURNING purchase_id
                    """,
                    (user["business_id"], payload.supplier_id, payload.purchase_date, reference),
                )
                purchase_id = cur.fetchone()["purchase_id"]
                for item in payload.items:
                    cur.execute(
                        """
                        INSERT INTO purchase_items
                            (business_id, purchase_id, vehicle_id, purchase_price, condition_at_purchase)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (user["business_id"], purchase_id, item.vehicle_id, item.purchase_price, item.condition_at_purchase),
                    )
                cur.execute(
                    "UPDATE purchases SET total_amount = %s WHERE purchase_id = %s AND business_id = %s",
                    (total, purchase_id, user["business_id"]),
                )
                _set_business(cur, user["business_id"])
                cur.execute(
                    "UPDATE purchases SET purchase_status = 'ORDERED' WHERE purchase_id = %s AND business_id = %s",
                    (purchase_id, user["business_id"]),
                )
                cur.execute(
                    "UPDATE purchases SET purchase_status = 'RECEIVED' WHERE purchase_id = %s AND business_id = %s",
                    (purchase_id, user["business_id"]),
                )
                cur.execute(
                    """
                    UPDATE vehicle_inventory vi
                    SET business_id = %s
                    FROM purchase_items pi
                    WHERE pi.purchase_id = %s
                      AND pi.business_id = %s
                      AND vi.vehicle_id = pi.vehicle_id
                      AND vi.business_id IS NULL
                    """,
                    (user["business_id"], purchase_id, user["business_id"]),
                )
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM purchase_items pi
                    JOIN vehicle_inventory vi ON vi.vehicle_id = pi.vehicle_id
                    WHERE pi.purchase_id = %s
                      AND pi.business_id = %s
                      AND vi.business_id = %s
                    """,
                    (purchase_id, user["business_id"], user["business_id"]),
                )
                if cur.fetchone()["count"] != len(payload.items):
                    raise HTTPException(
                        status_code=409,
                        detail="A purchased vehicle is already assigned to another business inventory.",
                    )
                if payload.initial_payment:
                    _insert_payment(
                        cur,
                        "purchase",
                        purchase_id,
                        payload.initial_payment.amount,
                        payload.initial_payment.payment_method,
                        payload.initial_payment.payment_status,
                        user["user_id"],
                        user["business_id"],
                        idempotency_key=f"purchase-{purchase_id}-initial-payment",
                    )
                result = _purchase_response(cur, purchase_id, user["business_id"], True)
        return result
    except psycopg2.errors.RaiseException as exc:
        raise HTTPException(status_code=409, detail=str(exc.diag.message_primary)) from exc
    except psycopg2.IntegrityError as exc:
        _translate_integrity_error(exc)
    finally:
        conn.close()


@router.get("/purchases/{purchase_id}", response_model=PurchaseResponse)
def get_purchase(purchase_id: int, user=Depends(require_permissions("purchases.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            return _purchase_response(
                cur,
                purchase_id,
                user["business_id"],
                True,
                _include_unassigned(user),
            )
    finally:
        conn.close()


@router.get("/sales", response_model=SaleListResponse)
def list_sales(user=Depends(require_permissions("sales.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            cur.execute(
                """
                SELECT sale_id FROM sales
                WHERE business_id = %s OR (business_id IS NULL AND %s)
                ORDER BY sale_date DESC, sale_id DESC
                """,
                (user["business_id"], _include_unassigned(user)),
            )
            ids = [row["sale_id"] for row in cur.fetchall()]
            sales = [
                _sale_response(
                    cur,
                    sale_id,
                    user["business_id"],
                    False,
                    _include_unassigned(user),
                )
                for sale_id in ids
            ]
        return {"sales": sales}
    finally:
        conn.close()


@router.post("/sales", status_code=201, response_model=SaleResponse)
def create_sale(payload: SaleCreate, user=Depends(require_permissions("sales.manage"))):
    total = sum(
        (item.selling_price - item.discount_amount + item.tax_amount for item in payload.items),
        Decimal("0.00"),
    )
    if total > Decimal("9999999999.99"):
        raise HTTPException(status_code=422, detail="Sale total exceeds the supported amount.")
    reference = payload.sale_reference.strip() if payload.sale_reference else _reference("SAL")
    if not reference:
        raise HTTPException(status_code=422, detail="sale_reference cannot be blank.")
    vehicle_ids = sorted(item.vehicle_id for item in payload.items)

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _require_commerce_schema(cur)
                cur.execute(
                    """
                    SELECT COALESCE((to_jsonb(c)->>'is_active')::boolean, TRUE) AS is_active
                    FROM customers c WHERE customer_id = %s AND business_id = %s
                    """,
                    (payload.customer_id, user["business_id"]),
                )
                customer = cur.fetchone()
                if customer is None:
                    raise HTTPException(status_code=404, detail="Customer not found.")
                if not customer["is_active"]:
                    raise HTTPException(status_code=409, detail="Inactive customers cannot be used for new sales.")
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                cur.execute(
                    """
                    SELECT vi.vehicle_id, vi.stock_status
                    FROM vehicle_inventory vi
                    JOIN vehicles v USING (vehicle_id)
                    WHERE vi.vehicle_id = ANY(%s) AND vi.business_id = %s
                    ORDER BY vi.vehicle_id
                    FOR UPDATE OF v, vi
                    """,
                    (vehicle_ids, user["business_id"]),
                )
                inventory = cur.fetchall()
                if len(inventory) != len(vehicle_ids):
                    raise HTTPException(
                        status_code=409,
                        detail="Every vehicle must be explicitly onboarded into inventory before sale.",
                    )
                unavailable = [row["vehicle_id"] for row in inventory if row["stock_status"] != "AVAILABLE"]
                if unavailable:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Vehicle inventory is not available for sale: {unavailable}.",
                    )

                cur.execute(
                    """
                    INSERT INTO sales
                        (business_id, customer_id, sale_date, total_amount, sale_reference, sale_status)
                    VALUES (%s, %s, %s, 0, %s, 'DRAFT')
                    RETURNING sale_id
                    """,
                    (user["business_id"], payload.customer_id, payload.sale_date, reference),
                )
                sale_id = cur.fetchone()["sale_id"]
                for item in payload.items:
                    cur.execute(
                        """
                        INSERT INTO sale_items
                            (business_id, sale_id, vehicle_id, selling_price, discount_amount, tax_amount)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            user["business_id"],
                            sale_id,
                            item.vehicle_id,
                            item.selling_price,
                            item.discount_amount,
                            item.tax_amount,
                        ),
                    )
                cur.execute("UPDATE sales SET total_amount = %s WHERE sale_id = %s AND business_id = %s", (total, sale_id, user["business_id"]))
                cur.execute("UPDATE sales SET sale_status = 'CONFIRMED' WHERE sale_id = %s AND business_id = %s", (sale_id, user["business_id"]))
                cur.execute("UPDATE sales SET sale_status = 'COMPLETED' WHERE sale_id = %s AND business_id = %s", (sale_id, user["business_id"]))
                if payload.initial_payment:
                    _insert_payment(
                        cur,
                        "sale",
                        sale_id,
                        payload.initial_payment.amount,
                        payload.initial_payment.payment_method,
                        payload.initial_payment.payment_status,
                        user["user_id"],
                        user["business_id"],
                        idempotency_key=f"sale-{sale_id}-initial-payment",
                    )
                result = _sale_response(cur, sale_id, user["business_id"], True)
        return result
    except psycopg2.errors.RaiseException as exc:
        raise HTTPException(status_code=409, detail=str(exc.diag.message_primary)) from exc
    except psycopg2.IntegrityError as exc:
        _translate_integrity_error(exc)
    finally:
        conn.close()


@router.get("/sales/{sale_id}", response_model=SaleResponse)
def get_sale(sale_id: int, user=Depends(require_permissions("sales.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            return _sale_response(
                cur,
                sale_id,
                user["business_id"],
                True,
                _include_unassigned(user),
            )
    finally:
        conn.close()


@router.get("/inventory", response_model=InventoryListResponse)
def list_inventory(
    q: str = Query(default="", max_length=100),
    stock_status: str | None = Query(
        default=None,
        pattern="^(AVAILABLE|RESERVED|SOLD|UNDER_MAINTENANCE|UNTRACKED)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    user=Depends(require_permissions("inventory.read")),
):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            filters = []
            filter_params: list[object] = []
            if q.strip():
                term = f"%{q.strip()}%"
                filters.append("(v.vin ILIKE %s OR v.registration_no ILIKE %s OR v.brand ILIKE %s OR v.model ILIKE %s)")
                filter_params.extend([term, term, term, term])
            if stock_status == "UNTRACKED":
                filters.append("vi.vehicle_id IS NULL")
            elif stock_status:
                filters.append("vi.stock_status = %s")
                filter_params.append(stock_status)
            where = " WHERE " + " AND ".join(filters) if filters else ""
            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM vehicles v
                LEFT JOIN vehicle_inventory vi
                  ON vi.vehicle_id = v.vehicle_id
                 AND (
                     vi.business_id = %s
                     OR (vi.business_id IS NULL AND %s)
                 )
                {where}
                """,
                [user["business_id"], _include_unassigned(user), *filter_params],
            )
            total = cur.fetchone()["total"]
            cur.execute(
                f"""
                SELECT v.vehicle_id, v.vin, v.registration_no, v.brand, v.model,
                       v.model_year, COALESCE(vi.stock_status, 'UNTRACKED') AS stock_status,
                       COALESCE(vi.vehicle_condition, 'UNKNOWN') AS vehicle_condition,
                       vi.asking_price,
                       (
                           SELECT pi.purchase_price
                           FROM purchase_items pi
                           JOIN purchases p USING (purchase_id)
                           WHERE pi.vehicle_id = v.vehicle_id
                             AND pi.business_id IS NOT DISTINCT FROM p.business_id
                             AND (
                                 p.business_id = %s
                                 OR (p.business_id IS NULL AND %s)
                             )
                             AND p.purchase_status = 'RECEIVED'
                           ORDER BY p.received_at DESC NULLS LAST, p.purchase_id DESC, pi.purchase_item_id DESC
                           LIMIT 1
                       ) AS acquisition_cost,
                       vi.reserved_for_sale_id, vi.sold_sale_id,
                       vi.source_note, vi.source_reference
                FROM vehicles v
                LEFT JOIN vehicle_inventory vi
                  ON vi.vehicle_id = v.vehicle_id
                 AND (
                     vi.business_id = %s
                     OR (vi.business_id IS NULL AND %s)
                 )
                {where}
                ORDER BY v.registration_no, v.vehicle_id
                LIMIT %s OFFSET %s
                """,
                [
                    user["business_id"],
                    _include_unassigned(user),
                    user["business_id"],
                    _include_unassigned(user),
                    *filter_params,
                    page_size,
                    (page - 1) * page_size,
                ],
            )
            vehicles = [dict(row) for row in cur.fetchall()]
            cur.execute(
                f"""
                SELECT COALESCE(SUM((
                           SELECT pi.purchase_price
                           FROM purchase_items pi
                           JOIN purchases p USING (purchase_id)
                           WHERE pi.vehicle_id = v.vehicle_id
                             AND pi.business_id IS NOT DISTINCT FROM p.business_id
                             AND (
                                 p.business_id = %s
                                 OR (p.business_id IS NULL AND %s)
                             )
                             AND p.purchase_status = 'RECEIVED'
                           ORDER BY p.received_at DESC NULLS LAST, p.purchase_id DESC, pi.purchase_item_id DESC
                           LIMIT 1
                       )), 0) AS acquisition_total,
                       COALESCE(SUM(vi.asking_price), 0) AS asking_total
                FROM vehicles v
                LEFT JOIN vehicle_inventory vi
                  ON vi.vehicle_id = v.vehicle_id
                 AND (
                     vi.business_id = %s
                     OR (vi.business_id IS NULL AND %s)
                 )
                {where}
                """,
                [
                    user["business_id"],
                    _include_unassigned(user),
                    user["business_id"],
                    _include_unassigned(user),
                    *filter_params,
                ],
            )
            valuation = cur.fetchone()
        return {
            "vehicles": vehicles,
            "total": total,
            "acquisition_valuation": valuation["acquisition_total"],
            "asking_valuation": valuation["asking_total"],
        }
    finally:
        conn.close()


@router.post("/inventory/{vehicle_id}", status_code=201, response_model=InventoryResponse)
def onboard_inventory(vehicle_id: int, payload: InventoryOnboard, user=Depends(require_permissions("inventory.manage"))):
    note = payload.source_note.strip()
    if not note:
        raise HTTPException(status_code=422, detail="source_note cannot be blank.")
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _require_commerce_schema(cur)
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                cur.execute(
                    """
                    INSERT INTO vehicle_inventory
                        (business_id, vehicle_id, stock_status, vehicle_condition, asking_price,
                         source_note, source_reference, status_changed_at, updated_at)
                    VALUES (%s, %s, 'AVAILABLE', %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING vehicle_id
                    """,
                    (
                        user["business_id"],
                        vehicle_id,
                        payload.vehicle_condition,
                        payload.asking_price,
                        note,
                        _normalize_optional(payload.source_reference),
                    ),
                )
                result = _inventory_item(cur, cur.fetchone()["vehicle_id"], user["business_id"])
        return result
    except psycopg2.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="This vehicle already has an inventory status.") from exc
    except psycopg2.errors.ForeignKeyViolation as exc:
        raise HTTPException(status_code=404, detail="Vehicle not found.") from exc
    except psycopg2.IntegrityError as exc:
        _translate_integrity_error(exc)
    finally:
        conn.close()


def _inventory_item(
    cursor,
    vehicle_id: int,
    business_id: int,
    include_unassigned: bool = False,
) -> dict:
    cursor.execute(
        """
        SELECT v.vehicle_id, v.vin, v.registration_no, v.brand, v.model, v.model_year,
               COALESCE(vi.stock_status, 'UNTRACKED') AS stock_status,
               COALESCE(vi.vehicle_condition, 'UNKNOWN') AS vehicle_condition,
               vi.asking_price, vi.reserved_for_sale_id, vi.sold_sale_id,
               vi.source_note, vi.source_reference,
               (
                   SELECT pi.purchase_price
                   FROM purchase_items pi
                   JOIN purchases p USING (purchase_id)
                   WHERE pi.vehicle_id = v.vehicle_id
                     AND pi.business_id IS NOT DISTINCT FROM p.business_id
                     AND (
                         p.business_id = %s
                         OR (p.business_id IS NULL AND %s)
                     )
                     AND p.purchase_status = 'RECEIVED'
                   ORDER BY p.received_at DESC NULLS LAST, p.purchase_id DESC, pi.purchase_item_id DESC
                   LIMIT 1
               ) AS acquisition_cost
        FROM vehicles v
        JOIN vehicle_inventory vi
          ON vi.vehicle_id = v.vehicle_id
         AND (
             vi.business_id = %s
             OR (vi.business_id IS NULL AND %s)
         )
        WHERE v.vehicle_id = %s
        """,
        (business_id, include_unassigned, business_id, include_unassigned, vehicle_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return dict(row)


@router.get("/inventory/{vehicle_id}", response_model=InventoryResponse)
def get_inventory_item(vehicle_id: int, user=Depends(require_permissions("inventory.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            return _inventory_item(
                cur,
                vehicle_id,
                user["business_id"],
                _include_unassigned(user),
            )
    finally:
        conn.close()


@router.patch("/inventory/{vehicle_id}", response_model=InventoryResponse)
def update_inventory_status(vehicle_id: int, payload: InventoryStatusUpdate, user=Depends(require_permissions("inventory.manage"))):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _require_commerce_schema(cur)
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                cur.execute(
                    "SELECT stock_status FROM vehicle_inventory WHERE vehicle_id = %s AND business_id = %s FOR UPDATE",
                    (vehicle_id, user["business_id"]),
                )
                current = cur.fetchone()
                if current is None:
                    raise HTTPException(status_code=404, detail="Vehicle is not onboarded into inventory.")
                allowed = {
                    ("AVAILABLE", "UNDER_MAINTENANCE"),
                    ("UNDER_MAINTENANCE", "AVAILABLE"),
                }
                transition = (current["stock_status"], payload.stock_status)
                if transition not in allowed and transition[0] != transition[1]:
                    raise HTTPException(
                        status_code=409,
                        detail="Only AVAILABLE and UNDER_MAINTENANCE transitions are managed through this endpoint.",
                    )
                if transition[0] != transition[1]:
                    cur.execute(
                        """
                        UPDATE vehicle_inventory
                        SET stock_status = %s, status_changed_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE vehicle_id = %s AND business_id = %s
                        """,
                        (payload.stock_status, vehicle_id, user["business_id"]),
                    )
                return _inventory_item(cur, vehicle_id, user["business_id"])
    finally:
        conn.close()


def _payment_item(
    cursor,
    payment_id: int,
    business_id: int,
    include_unassigned: bool = False,
) -> dict:
    cursor.execute(
        """
        SELECT payment_id, payment_reference, purchase_id, sale_id, amount,
               currency, payment_kind, payment_status, payment_method,
               payment_date, external_reference
        FROM payments
        WHERE payment_id = %s
          AND (business_id = %s OR (business_id IS NULL AND %s))
        """,
        (payment_id, business_id, include_unassigned),
    )
    payment = cursor.fetchone()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return dict(payment)


@router.get("/payments", response_model=PaymentListResponse)
def list_payments(
    purchase_id: int | None = Query(default=None, gt=0),
    sale_id: int | None = Query(default=None, gt=0),
    user=Depends(require_permissions("payments.read")),
):
    if purchase_id is not None and sale_id is not None:
        raise HTTPException(status_code=422, detail="Filter by purchase_id or sale_id, not both.")
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            cur.execute(
                """
                SELECT payment_id, payment_reference, purchase_id, sale_id, amount,
                       currency, payment_kind, payment_status, payment_method,
                       payment_date, external_reference
                FROM payments
                WHERE business_id = %s OR (business_id IS NULL AND %s)
                  AND (%s IS NULL OR purchase_id = %s)
                  AND (%s IS NULL OR sale_id = %s)
                ORDER BY payment_date DESC, payment_id DESC
                """,
                (
                    user["business_id"],
                    _include_unassigned(user),
                    purchase_id,
                    purchase_id,
                    sale_id,
                    sale_id,
                ),
            )
            return {"payments": cur.fetchall()}
    finally:
        conn.close()


@router.post("/payments", status_code=201, response_model=PaymentResponse)
def create_payment(payload: PaymentCreate, user=Depends(require_permissions("payments.manage"))):
    parent_kind = "purchase" if payload.purchase_id is not None else "sale"
    parent_id = payload.purchase_id if payload.purchase_id is not None else payload.sale_id
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _require_commerce_schema(cur)
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                _parent_total(cur, parent_kind, parent_id, user["business_id"], lock=True)
                idempotency_key = _normalize_optional(payload.idempotency_key)
                if idempotency_key:
                    cur.execute("SELECT pg_advisory_xact_lock(0, hashtext(%s))", (idempotency_key,))
                    cur.execute(
                        """
                        SELECT payment_id, purchase_id, sale_id, amount,
                               payment_method, payment_status, external_reference
                        FROM payments WHERE idempotency_key = %s AND business_id = %s FOR UPDATE
                        """,
                        (idempotency_key, user["business_id"]),
                    )
                    existing = cur.fetchone()
                    if existing:
                        same_request = (
                            existing["purchase_id"] == payload.purchase_id
                            and existing["sale_id"] == payload.sale_id
                            and Decimal(existing["amount"]) == payload.amount
                            and existing["payment_method"] == payload.payment_method
                            and existing["external_reference"]
                            == _normalize_optional(payload.external_reference)
                        )
                        if not same_request:
                            raise HTTPException(
                                status_code=409,
                                detail="This idempotency_key was already used for a different payment.",
                            )
                        payment_id = existing["payment_id"]
                    else:
                        payment_id = _insert_payment(
                            cur,
                            parent_kind,
                            parent_id,
                            payload.amount,
                            payload.payment_method,
                            payload.payment_status,
                            user["user_id"],
                            user["business_id"],
                            _normalize_optional(payload.external_reference),
                            idempotency_key,
                        )
                else:
                    payment_id = _insert_payment(
                        cur,
                        parent_kind,
                        parent_id,
                        payload.amount,
                        payload.payment_method,
                        payload.payment_status,
                        user["user_id"],
                        user["business_id"],
                        _normalize_optional(payload.external_reference),
                    )
                result = _payment_item(cur, payment_id, user["business_id"])
        return result
    except psycopg2.IntegrityError as exc:
        _translate_integrity_error(exc)
    finally:
        conn.close()


@router.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: int, user=Depends(require_permissions("payments.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            return _payment_item(
                cur,
                payment_id,
                user["business_id"],
                _include_unassigned(user),
            )
    finally:
        conn.close()


@router.patch("/payments/{payment_id}", response_model=PaymentResponse)
def update_payment_status(payment_id: int, payload: PaymentStatusUpdate, user=Depends(require_permissions("payments.manage"))):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _require_commerce_schema(cur)
                cur.execute(
                    "SELECT purchase_id, sale_id FROM payments WHERE payment_id = %s AND business_id = %s",
                    (payment_id, user["business_id"]),
                )
                parent = cur.fetchone()
                if parent is None:
                    raise HTTPException(status_code=404, detail="Payment not found.")
                parent_kind = "purchase" if parent["purchase_id"] is not None else "sale"
                parent_id = parent["purchase_id"] if parent["purchase_id"] is not None else parent["sale_id"]
                _parent_total(cur, parent_kind, parent_id, user["business_id"], lock=True)
                cur.execute(
                    "SELECT payment_status, amount FROM payments WHERE payment_id = %s AND business_id = %s FOR UPDATE",
                    (payment_id, user["business_id"]),
                )
                payment = cur.fetchone()
                if payment["payment_status"] != "PENDING":
                    raise HTTPException(status_code=409, detail="Only pending payments may change status.")
                if payload.payment_status == "COMPLETED":
                    _assert_payment_fits(
                        cur,
                        parent_kind,
                        parent_id,
                        user["business_id"],
                        Decimal(payment["amount"]),
                        "COMPLETED",
                        exclude_payment_id=payment_id,
                    )
                _set_actor(cur, user["user_id"])
                _set_business(cur, user["business_id"])
                cur.execute(
                    "UPDATE payments SET payment_status = %s WHERE payment_id = %s AND business_id = %s",
                    (payload.payment_status, payment_id, user["business_id"]),
                )
                return _payment_item(cur, payment_id, user["business_id"])
    except psycopg2.IntegrityError as exc:
        _translate_integrity_error(exc)
    finally:
        conn.close()


def _transaction_pdf(title: str, details: list[tuple[str, object]], items: list[list[object]], summary: list[tuple[str, object]]) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 8 * mm)]
    for label, value in details:
        story.append(Paragraph(f"<b>{escape(label)}:</b> {escape(str(value))}", styles["BodyText"]))
    story.append(Spacer(1, 6 * mm))
    table = Table(items, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#18324b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    for label, value in summary:
        story.append(Paragraph(f"<b>{escape(label)}:</b> PKR {escape(str(value))}", styles["BodyText"]))
    document.build(story)
    return buffer.getvalue()


@router.get("/sales/{sale_id}/invoice.pdf", tags=["Financial reports"])
def sale_invoice(sale_id: int, user=Depends(require_permissions("invoices.read", "sales.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            sale = _sale_response(
                cur,
                sale_id,
                user["business_id"],
                True,
                _include_unassigned(user),
            )
            if not sale["items"]:
                raise HTTPException(status_code=409, detail="This sale has no vehicle lines to invoice.")
            if sale["sale_status"] != "COMPLETED":
                raise HTTPException(status_code=409, detail="An invoice is available only for a completed sale.")
            cur.execute(
                """
                SELECT customer_name, phone, email
                FROM customers
                WHERE customer_id = %s
                  AND (business_id = %s OR (business_id IS NULL AND %s))
                """,
                (
                    sale["customer_id"],
                    user["business_id"],
                    _include_unassigned(user),
                ),
            )
            customer = cur.fetchone()
            cur.execute(
                """
                SELECT payment_reference, amount, payment_date, payment_method
                FROM payments
                WHERE sale_id = %s
                  AND (business_id = %s OR (business_id IS NULL AND %s))
                  AND payment_status = 'COMPLETED'
                  AND payment_kind = 'PAYMENT'
                ORDER BY payment_date, payment_id
                """,
                (sale_id, user["business_id"], _include_unassigned(user)),
            )
            payments = cur.fetchall()
        item_rows = [["Vehicle", "VIN", "Selling price", "Discount", "Tax", "Line total"]]
        for item in sale["items"]:
            vehicle = f"{item['registration_no']} · {item['brand']} {item.get('model', '')}".strip()
            item_rows.append([
                vehicle,
                item["vin"],
                f"PKR {item['selling_price']}",
                f"PKR {item['discount_amount']}",
                f"PKR {item['tax_amount']}",
                f"PKR {item['line_total']}",
            ])
        details = [
            ("Invoice reference", sale["sale_reference"] or f"SALE-{sale_id}"),
            ("Sale date", sale["sale_date"]),
            ("Customer", customer["customer_name"] if customer else "Customer record unavailable"),
            ("Customer phone", customer["phone"] or "—" if customer else "—"),
            ("Customer email", customer["email"] or "—" if customer else "—"),
            ("Payment events", ", ".join(
                f"{item['payment_reference']} ({item['payment_date']:%Y-%m-%d})"
                for item in payments
            ) or "No completed payments"),
        ]
        pdf = _transaction_pdf(
            "AutoLedger Sales Invoice",
            details,
            item_rows,
            [
                ("Total", sale["total_amount"] or Decimal("0.00")),
                ("Paid", sale["paid_amount"]),
                ("Balance due", sale["balance_due"]),
            ],
        )
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="autledger-invoice-{sale_id}.pdf"'},
        )
    finally:
        conn.close()


@router.get("/payments/{payment_id}/receipt.pdf", tags=["Financial reports"])
def payment_receipt(payment_id: int, user=Depends(require_permissions("invoices.read", "payments.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            payment = _payment_item(
                cur,
                payment_id,
                user["business_id"],
                _include_unassigned(user),
            )
            if payment["payment_status"] != "COMPLETED":
                raise HTTPException(status_code=409, detail="A receipt is available only for a completed payment.")
            parent_kind = "purchase" if payment["purchase_id"] is not None else "sale"
            parent_id = payment["purchase_id"] if payment["purchase_id"] is not None else payment["sale_id"]
            total = _parent_total(
                cur,
                parent_kind,
                parent_id,
                user["business_id"],
                include_unassigned=_include_unassigned(user),
            )
            settled, _pending = _payment_totals(
                cur,
                parent_kind,
                parent_id,
                user["business_id"],
                _include_unassigned(user),
            )
            remaining = max(total - settled, Decimal("0.00"))
            parent_reference = (
                "SELECT purchase_reference AS reference FROM purchases WHERE purchase_id = %s AND (business_id = %s OR (business_id IS NULL AND %s))"
                if parent_kind == "purchase"
                else "SELECT sale_reference AS reference FROM sales WHERE sale_id = %s AND (business_id = %s OR (business_id IS NULL AND %s))"
            )
            cur.execute(
                parent_reference,
                (parent_id, user["business_id"], _include_unassigned(user)),
            )
            reference = cur.fetchone()["reference"]
        rows = [["Payment", "Amount", "Method", "Status"]]
        rows.append([
            payment["payment_reference"],
            f"PKR {payment['amount']}",
            payment["payment_method"],
            payment["payment_status"],
        ])
        pdf = _transaction_pdf(
            "AutoLedger Payment Receipt",
            [
                ("Transaction", f"{parent_kind.title()} {reference or parent_id}"),
                ("Payment date", payment["payment_date"]),
                ("External reference", payment["external_reference"] or "—"),
            ],
            rows,
            [("Transaction total", total), ("Balance remaining", remaining)],
        )
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="autoledger-receipt-{payment_id}.pdf"'},
        )
    finally:
        conn.close()


@router.get("/reports/financial", tags=["Financial reports"])
def financial_report(user=Depends(require_permissions("reports.financial", "financial.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _require_commerce_schema(cur)
            cur.execute(
                """
                WITH purchase_balance AS (
                    SELECT p.purchase_id, p.supplier_id, p.purchase_date,
                           p.purchase_status, COALESCE(p.total_amount, 0) AS total_amount,
                           COALESCE(SUM(CASE
                               WHEN pm.payment_status = 'COMPLETED' AND pm.payment_kind = 'PAYMENT' THEN pm.amount
                               WHEN pm.payment_status = 'COMPLETED' AND pm.payment_kind = 'REFUND' THEN -pm.amount
                               ELSE 0 END), 0) AS paid_amount
                    FROM purchases p
                    LEFT JOIN payments pm ON pm.purchase_id = p.purchase_id
                                         AND pm.business_id = p.business_id
                    WHERE p.business_id = %s
                    GROUP BY p.purchase_id
                ),
                sale_balance AS (
                    SELECT s.sale_id, s.customer_id, s.sale_date,
                           s.sale_status, COALESCE(s.total_amount, 0) AS total_amount,
                           COALESCE(SUM(CASE
                               WHEN pm.payment_status = 'COMPLETED' AND pm.payment_kind = 'PAYMENT' THEN pm.amount
                               WHEN pm.payment_status = 'COMPLETED' AND pm.payment_kind = 'REFUND' THEN -pm.amount
                               ELSE 0 END), 0) AS paid_amount
                    FROM sales s
                    LEFT JOIN payments pm ON pm.sale_id = s.sale_id
                                         AND pm.business_id = s.business_id
                    WHERE s.business_id = %s
                    GROUP BY s.sale_id
                )
                SELECT
                    COALESCE((SELECT SUM(total_amount) FROM purchase_balance WHERE purchase_status = 'RECEIVED'), 0) AS total_purchases,
                    COALESCE((SELECT SUM(LEAST(paid_amount, total_amount)) FROM purchase_balance WHERE purchase_status = 'RECEIVED'), 0) AS paid_to_suppliers,
                    COALESCE((SELECT SUM(GREATEST(total_amount - paid_amount, 0)) FROM purchase_balance WHERE purchase_status = 'RECEIVED'), 0) AS supplier_balance_due,
                    COALESCE((SELECT SUM(total_amount) FROM sale_balance WHERE sale_status = 'COMPLETED'), 0) AS total_sales,
                    COALESCE((SELECT SUM(LEAST(paid_amount, total_amount)) FROM sale_balance WHERE sale_status = 'COMPLETED'), 0) AS collected_from_customers,
                    COALESCE((SELECT SUM(GREATEST(total_amount - paid_amount, 0)) FROM sale_balance WHERE sale_status = 'COMPLETED'), 0) AS customer_balance_due
                """,
                (user["business_id"], user["business_id"]),
            )
            totals = dict(cur.fetchone())
            cur.execute(
                """
                WITH monthly AS (
                    SELECT date_trunc('month', purchase_date)::DATE AS month,
                           SUM(total_amount) AS purchases, 0::NUMERIC AS sales
                    FROM purchases
                    WHERE business_id = %s AND purchase_status = 'RECEIVED'
                      AND purchase_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '11 months'
                    GROUP BY 1
                    UNION ALL
                    SELECT date_trunc('month', sale_date)::DATE AS month,
                           0::NUMERIC AS purchases, SUM(total_amount) AS sales
                    FROM sales
                    WHERE business_id = %s AND sale_status = 'COMPLETED'
                      AND sale_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '11 months'
                    GROUP BY 1
                )
                SELECT month, SUM(purchases) AS purchases, SUM(sales) AS sales
                FROM monthly GROUP BY month ORDER BY month
                """,
                (user["business_id"], user["business_id"]),
            )
            monthly = cur.fetchall()
            cur.execute(
                """
                SELECT COALESCE(SUM(si.line_total - ac.purchase_price)
                           FILTER (WHERE ac.purchase_price IS NOT NULL), 0) AS realized_gross_profit,
                       COUNT(*) FILTER (WHERE ac.purchase_price IS NULL) AS sales_without_recorded_acquisition_cost
                FROM sale_items si
                JOIN sales s USING (sale_id)
                LEFT JOIN LATERAL (
                    SELECT pi.purchase_price
                    FROM purchase_items pi
                    JOIN purchases p USING (purchase_id)
                    WHERE pi.vehicle_id = si.vehicle_id
                      AND pi.business_id = p.business_id
                      AND p.business_id = s.business_id
                      AND p.purchase_status = 'RECEIVED'
                      AND p.purchase_date <= s.sale_date
                    ORDER BY p.purchase_date DESC, p.purchase_id DESC, pi.purchase_item_id DESC
                    LIMIT 1
                ) ac ON TRUE
                WHERE s.business_id = %s AND si.business_id = s.business_id
                  AND s.sale_status = 'COMPLETED'
                """,
                (user["business_id"],),
            )
            profit = dict(cur.fetchone())
        totals.update(profit)
        return {
            "currency": "PKR",
            "tax_policy": "No tax",
            "totals": totals,
            "monthly": monthly,
            "gross_profit_note": (
                "Gross profit excludes sold vehicles without a recorded received purchase cost; "
                "the count is reported rather than estimating legacy acquisition values."
            ),
        }
    finally:
        conn.close()
