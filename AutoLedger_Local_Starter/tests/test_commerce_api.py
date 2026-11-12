import asyncio
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from psycopg2.extras import RealDictCursor

from backend.commerce import _require_commerce_schema
from backend.commerce_schemas import PaymentCreate, SaleCreate, SupplierCreate
from backend.database import get_connection
from backend.main import app
from backend.security import ROLE_PERMISSION_DEFAULTS, get_current_user


TEST_ROLE_USERS = {
    "Super Admin": 15,
    "Admin": 1,
    "Business Owner": 2,
    "Manager": 3,
    "Accountant": 6,
    "Staff": 4,
    "Viewer": 16,
}


def _test_business_id() -> int:
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT business_id FROM businesses WHERE business_name = %s",
                    ("AutoLedger isolated test business",),
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
                cursor.execute(
                    "INSERT INTO businesses (business_name) VALUES (%s) RETURNING business_id",
                    ("AutoLedger isolated test business",),
                )
                return cursor.fetchone()[0]
    finally:
        connection.close()


def _create_test_business(name: str) -> int:
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO businesses (business_name) VALUES (%s) RETURNING business_id",
                    (name,),
                )
                return cursor.fetchone()[0]
    finally:
        connection.close()


def _ensure_membership(role_name: str, user_id: int | None = None, business_id: int | None = None) -> tuple[int, int]:
    user_id = user_id if user_id is not None else TEST_ROLE_USERS.get(role_name, 999999)
    business_id = business_id or _test_business_id()
    if role_name not in TEST_ROLE_USERS:
        return user_id, business_id
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT role_id FROM roles WHERE role_name = %s", (role_name,))
                role = cursor.fetchone()
                if role is None:
                    raise AssertionError(f"Required test role is missing from the clone: {role_name}")
                cursor.execute(
                    """
                    INSERT INTO business_memberships (user_id, business_id, role_id, is_active)
                    VALUES (%s, %s, %s, TRUE)
                    ON CONFLICT (user_id, business_id)
                    DO UPDATE SET role_id = EXCLUDED.role_id, is_active = TRUE
                    """,
                    (user_id, business_id, role[0]),
                )
    finally:
        connection.close()
    return user_id, business_id


def _request_as(
    role_name: str,
    user_id: int | None = None,
    method: str = "GET",
    path: str = "/",
    business_id: int | None = None,
    ensure_membership: bool = True,
    **kwargs,
):
    if ensure_membership:
        user_id, business_id = _ensure_membership(role_name, user_id, business_id)
    else:
        user_id = user_id if user_id is not None else 999999
        business_id = business_id or _test_business_id()
    headers = dict(kwargs.pop("headers", {}))
    headers["X-Business-ID"] = str(business_id)
    async def request():
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": user_id,
            "role_name": role_name,
            "permissions": sorted(ROLE_PERMISSION_DEFAULTS.get(role_name, ())),
            "full_name": "Phase 5 test",
            "email": f"phase5-{role_name.lower().replace('/', '-') }@example.test",
        }
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path, headers=headers, **kwargs)
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    return asyncio.run(request())


def test_commerce_request_schemas_validate_money_parties_and_tax():
    with pytest.raises(ValidationError):
        SupplierCreate(supplier_name="   ")

    with pytest.raises(ValidationError):
        PaymentCreate(
            purchase_id=1,
            sale_id=2,
            amount=Decimal("10.00"),
            payment_method="CASH",
        )

    with pytest.raises(ValidationError, match="tax_amount must be 0.00"):
        SaleCreate(
            customer_id=1,
            sale_date=date.today(),
            items=[
                {
                    "vehicle_id": 1,
                    "selling_price": "100.00",
                    "tax_amount": "5.00",
                }
            ],
        )

    with pytest.raises(ValidationError, match="only once"):
        SaleCreate(
            customer_id=1,
            sale_date=date.today(),
            items=[
                {"vehicle_id": 1, "selling_price": "100.00"},
                {"vehicle_id": 1, "selling_price": "90.00"},
            ],
        )


def test_admin_supplier_and_customer_crud_writes_audit_records():
    marker = uuid.uuid4().hex[:12]
    supplier_name = f"Phase5 Supplier {marker}"
    customer_name = f"Phase5 Customer {marker}"
    supplier = _request_as(
        "Admin",
        method="POST",
        path="/api/suppliers",
        json={"supplier_name": supplier_name, "email": f"{marker}@example.test"},
    )
    assert supplier.status_code == 201, supplier.text
    supplier_id = supplier.json()["supplier_id"]

    customer = _request_as(
        "Admin",
        method="POST",
        path="/api/customers",
        json={"customer_name": customer_name, "phone": "+923001234567"},
    )
    assert customer.status_code == 201, customer.text
    customer_id = customer.json()["customer_id"]

    listed_suppliers = _request_as("Accountant", path="/api/suppliers", params={"q": marker})
    listed_customers = _request_as("Accountant", path="/api/customers", params={"q": marker})
    assert listed_suppliers.status_code == 200
    assert listed_customers.status_code == 200
    assert listed_suppliers.json()["suppliers"][0]["supplier_id"] == supplier_id
    assert listed_customers.json()["customers"][0]["customer_id"] == customer_id

    updated_supplier = _request_as(
        "Admin",
        method="PATCH",
        path=f"/api/suppliers/{supplier_id}",
        json={"supplier_name": supplier_name + " Updated"},
    )
    updated_customer = _request_as(
        "Admin",
        method="PATCH",
        path=f"/api/customers/{customer_id}",
        json={"customer_name": customer_name + " Updated"},
    )
    assert updated_supplier.status_code == 200
    assert updated_customer.status_code == 200

    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT entity_name, action, COUNT(*)
                FROM audit_logs
                WHERE (entity_name = 'suppliers' AND entity_id = %s)
                   OR (entity_name = 'customers' AND entity_id = %s)
                GROUP BY entity_name, action
                """,
                (supplier_id, customer_id),
            )
            audit_rows = {(row[0], row[1]): row[2] for row in cursor.fetchall()}
    finally:
        connection.close()
    assert audit_rows[("suppliers", "INSERT")] == 1
    assert audit_rows[("suppliers", "UPDATE")] == 1
    assert audit_rows[("customers", "INSERT")] == 1
    assert audit_rows[("customers", "UPDATE")] == 1


def test_unassigned_legacy_partners_are_visible_only_to_super_admin():
    marker = uuid.uuid4().hex[:12]
    supplier_name = f"Unassigned legacy supplier {marker}"
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO suppliers (business_id, supplier_name)
                    VALUES (NULL, %s)
                    RETURNING supplier_id
                    """,
                    (supplier_name,),
                )
                supplier_id = cursor.fetchone()[0]
    finally:
        connection.close()

    try:
        manager_list = _request_as(
            "Manager",
            path="/api/suppliers",
            params={"q": marker},
        )
        super_admin_list = _request_as(
            "Super Admin",
            path="/api/suppliers",
            params={"q": marker},
        )
        manager_detail = _request_as(
            "Manager",
            path=f"/api/suppliers/{supplier_id}",
        )
        super_admin_detail = _request_as(
            "Super Admin",
            path=f"/api/suppliers/{supplier_id}",
        )
        assert manager_list.status_code == 200
        assert manager_list.json()["suppliers"] == []
        assert manager_detail.status_code == 404
        assert super_admin_list.status_code == 200
        assert super_admin_list.json()["suppliers"][0]["supplier_id"] == supplier_id
        assert super_admin_detail.status_code == 200
    finally:
        connection = get_connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM suppliers WHERE supplier_id = %s", (supplier_id,))
                    cursor.execute(
                        "DELETE FROM audit_logs WHERE entity_name = 'suppliers' AND entity_id = %s",
                        (supplier_id,),
                    )
        finally:
            connection.close()


@pytest.mark.parametrize(
    ("role_name", "method", "path", "expected_status"),
    [
        ("Dealer", "POST", "/api/suppliers", 403),
        ("Inspector", "POST", "/api/customers", 403),
        ("Verification User", "GET", "/api/inventory", 403),
        ("Verification User", "GET", "/api/purchases", 403),
    ],
)
def test_commerce_role_permissions_and_migration_gate(role_name, method, path, expected_status):
    payload = {"supplier_name": "Denied"} if path == "/api/suppliers" else {"customer_name": "Denied"}
    response = _request_as(role_name, method=method, path=path, json=payload if method == "POST" else None)
    assert response.status_code == expected_status, response.text


def _commerce_schema_is_available() -> bool:
    connection = get_connection()
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            try:
                _require_commerce_schema(cursor)
            except HTTPException:
                return False
            return True
    finally:
        connection.close()


def test_viewer_cannot_read_business_inventory_without_permission():
    response = _request_as("Viewer", path="/api/inventory")
    assert response.status_code == 403, response.text


def test_commerce_endpoints_are_gated_only_when_schema_is_absent():
    expected_status = 200 if _commerce_schema_is_available() else 503
    for path in ("/api/purchases", "/api/sales", "/api/inventory", "/api/payments"):
        response = _request_as("Admin", path=path)
        assert response.status_code == expected_status, (path, response.text)
        if expected_status == 503:
            assert "proposed only" in response.json()["detail"]


def test_business_membership_list_and_selection_header():
    response = _request_as("Manager", path="/api/auth/businesses")
    assert response.status_code == 200, response.text
    assert any(
        entry["business_id"] == _test_business_id()
        and entry["role_name"] == "Manager"
        for entry in response.json()["businesses"]
    )


@pytest.fixture
def commerce_schema():
    connection = get_connection()
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            try:
                _require_commerce_schema(cursor)
            except HTTPException as exc:
                pytest.skip(exc.detail)
    finally:
        connection.close()


def _create_vehicle(marker: str) -> int:
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO vehicles (vin, registration_no, brand, model, model_year)
                    VALUES (%s, %s, 'Test', 'Commerce', 2026)
                    RETURNING vehicle_id
                    """,
                    (f"COMM{marker}"[:17], f"COMM-{marker}"),
                )
                return cursor.fetchone()[0]
    finally:
        connection.close()


def _create_party(table: str, name_column: str, name: str) -> int:
    if table not in {"suppliers", "customers"} or name_column not in {
        "supplier_name",
        "customer_name",
    }:
        raise ValueError("Unsupported test party table.")
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {table} (business_id, {name_column}) VALUES (%s, %s) RETURNING {table[:-1]}_id",
                    (_test_business_id(), name),
                )
                return cursor.fetchone()[0]
    finally:
        connection.close()


def _onboard_vehicle(vehicle_id: int, marker: str) -> None:
    response = _request_as(
        "Manager",
        method="POST",
        path=f"/api/inventory/{vehicle_id}",
        json={"source_note": f"Verified test source {marker}", "source_reference": marker},
    )
    assert response.status_code == 201, response.text


def test_purchase_creation_calculates_total_inventory_and_payment(commerce_schema):
    marker = uuid.uuid4().hex[:12].upper()
    vehicle_id = _create_vehicle(marker)
    supplier_id = _create_party("suppliers", "supplier_name", f"Commerce Supplier {marker}")
    response = _request_as(
        "Manager",
        method="POST",
        path="/api/purchases",
        json={
            "supplier_id": supplier_id,
            "purchase_date": date.today().isoformat(),
            "purchase_reference": f"TEST-PUR-{marker}",
            "items": [{"vehicle_id": vehicle_id, "purchase_price": "1250000.00"}],
            "initial_payment": {"amount": "250000.00", "payment_method": "BANK_TRANSFER"},
        },
    )
    assert response.status_code == 201, response.text
    purchase = response.json()
    assert purchase["total_amount"] == "1250000.00"
    assert purchase["paid_amount"] == "250000.00"
    assert purchase["balance_due"] == "1000000.00"
    assert purchase["items"][0]["vehicle_id"] == vehicle_id

    inventory = _request_as("Manager", path=f"/api/inventory/{vehicle_id}")
    assert inventory.status_code == 200
    assert inventory.json()["stock_status"] == "AVAILABLE"

    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE entity_name='purchases' AND entity_id=%s",
                (purchase["purchase_id"],),
            )
            assert cursor.fetchone()[0] >= 1
            cursor.execute("SELECT COUNT(*) FROM ownership_records WHERE vehicle_id=%s", (vehicle_id,))
            assert cursor.fetchone()[0] == 0
    finally:
        connection.close()


def test_sale_partial_full_payment_and_duplicate_sale_prevention(commerce_schema):
    marker = uuid.uuid4().hex[:12].upper()
    vehicle_id = _create_vehicle(marker)
    customer_id = _create_party("customers", "customer_name", f"Commerce Customer {marker}")
    _onboard_vehicle(vehicle_id, marker)
    payload = {
        "customer_id": customer_id,
        "sale_date": date.today().isoformat(),
        "sale_reference": f"TEST-SALE-{marker}",
        "items": [{"vehicle_id": vehicle_id, "selling_price": "2000000.00"}],
        "initial_payment": {"amount": "500000.00", "payment_method": "CASH"},
    }
    response = _request_as("Manager", method="POST", path="/api/sales", json=payload)
    assert response.status_code == 201, response.text
    sale = response.json()
    assert sale["sale_status"] == "COMPLETED"
    assert sale["total_amount"] == "2000000.00"
    assert sale["paid_amount"] == "500000.00"
    assert sale["balance_due"] == "1500000.00"

    inventory = _request_as("Admin", path=f"/api/inventory/{vehicle_id}")
    assert inventory.json()["stock_status"] == "SOLD"

    payment = _request_as(
        "Accountant",
        method="POST",
        path="/api/payments",
        json={
            "sale_id": sale["sale_id"],
            "amount": "1500000.00",
            "payment_method": "BANK_TRANSFER",
            "idempotency_key": f"full-payment-{sale['sale_id']}",
        },
    )
    assert payment.status_code == 201, payment.text
    duplicate_payment = _request_as(
        "Accountant",
        method="POST",
        path="/api/payments",
        json={
            "sale_id": sale["sale_id"],
            "amount": "1500000.00",
            "payment_method": "BANK_TRANSFER",
            "idempotency_key": f"full-payment-{sale['sale_id']}",
        },
    )
    assert duplicate_payment.status_code == 201, duplicate_payment.text
    assert duplicate_payment.json()["payment_id"] == payment.json()["payment_id"]

    updated_sale = _request_as("Manager", path=f"/api/sales/{sale['sale_id']}")
    assert updated_sale.json()["paid_amount"] == "2000000.00"
    assert updated_sale.json()["balance_due"] == "0.00"

    invoice = _request_as("Admin", path=f"/api/sales/{sale['sale_id']}/invoice.pdf")
    receipt = _request_as("Admin", path=f"/api/payments/{payment.json()['payment_id']}/receipt.pdf")
    assert invoice.status_code == 200 and invoice.content.startswith(b"%PDF-")
    assert receipt.status_code == 200 and receipt.content.startswith(b"%PDF-")
    report = _request_as("Admin", path="/api/reports/financial")
    assert report.status_code == 200, report.text
    assert report.json()["currency"] == "PKR"
    assert report.json()["tax_policy"] == "No tax"
    assert Decimal(report.json()["totals"]["customer_balance_due"]) >= Decimal("0.00")

    duplicate = _request_as(
        "Manager",
        method="POST",
        path="/api/sales",
        json={
            **payload,
            "sale_reference": f"TEST-SALE-DUP-{marker}",
            "initial_payment": None,
        },
    )
    assert duplicate.status_code == 409, duplicate.text


def test_failed_initial_payment_rolls_back_sale_and_inventory(commerce_schema):
    marker = uuid.uuid4().hex[:12].upper()
    vehicle_id = _create_vehicle(marker)
    customer_id = _create_party("customers", "customer_name", f"Rollback Customer {marker}")
    _onboard_vehicle(vehicle_id, marker)
    reference = f"ROLLBACK-SALE-{marker}"
    response = _request_as(
        "Manager",
        method="POST",
        path="/api/sales",
        json={
            "customer_id": customer_id,
            "sale_date": date.today().isoformat(),
            "sale_reference": reference,
            "items": [{"vehicle_id": vehicle_id, "selling_price": "1000.00"}],
            "initial_payment": {"amount": "1001.00", "payment_method": "CASH"},
        },
    )
    assert response.status_code == 409

    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM sales WHERE sale_reference=%s", (reference,))
            assert cursor.fetchone()[0] == 0
    finally:
        connection.close()
    inventory = _request_as("Admin", path=f"/api/inventory/{vehicle_id}")
    assert inventory.json()["stock_status"] == "AVAILABLE"


def test_concurrent_sales_only_sell_vehicle_once(commerce_schema):
    marker = uuid.uuid4().hex[:12].upper()
    vehicle_id = _create_vehicle(marker)
    customer_id = _create_party("customers", "customer_name", f"Race Customer {marker}")
    _onboard_vehicle(vehicle_id, marker)
    user_id, business_id = _ensure_membership("Manager", user_id=3)

    async def submit_competing_sales():
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": 1,
            "role_name": "Manager",
            "permissions": sorted(ROLE_PERMISSION_DEFAULTS["Manager"]),
            "full_name": "Concurrency test",
            "email": "concurrency@example.test",
        }
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                async def submit(reference):
                    return await client.post(
                        "/api/sales",
                        headers={"X-Business-ID": str(business_id)},
                        json={
                            "customer_id": customer_id,
                            "sale_date": date.today().isoformat(),
                            "sale_reference": reference,
                            "items": [{"vehicle_id": vehicle_id, "selling_price": "1000.00"}],
                        },
                    )

                return await asyncio.gather(
                    submit(f"RACE-A-{marker}"),
                    submit(f"RACE-B-{marker}"),
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    responses = asyncio.run(submit_competing_sales())
    assert sorted(response.status_code for response in responses) == [201, 409]


def test_cross_business_commerce_data_is_not_visible_or_mutable(commerce_schema):
    marker = uuid.uuid4().hex[:10].upper()
    report_before = _request_as("Business Owner", path="/api/reports/financial")
    assert report_before.status_code == 200, report_before.text
    business_b = _create_test_business(f"Isolation business {marker}")
    _ensure_membership("Manager", user_id=4, business_id=business_b)
    business_a = _test_business_id()
    no_membership = _request_as(
        "Manager",
        user_id=999999,
        business_id=business_a,
        ensure_membership=False,
        path="/api/suppliers",
    )
    assert no_membership.status_code == 403, no_membership.text

    supplier = _request_as(
        "Manager",
        user_id=4,
        business_id=business_b,
        method="POST",
        path="/api/suppliers",
        json={"supplier_name": f"Private supplier {marker}"},
    )
    customer = _request_as(
        "Manager",
        user_id=4,
        business_id=business_b,
        method="POST",
        path="/api/customers",
        json={"customer_name": f"Private customer {marker}"},
    )
    assert supplier.status_code == 201, supplier.text
    assert customer.status_code == 201, customer.text

    business_a = _test_business_id()
    audit_a = _request_as(
        "Super Admin",
        business_id=business_a,
        path="/api/records/audit",
    )
    audit_b = _request_as(
        "Super Admin",
        business_id=business_b,
        path="/api/records/audit",
    )
    assert audit_a.status_code == 200, audit_a.text
    assert audit_b.status_code == 200, audit_b.text
    assert not any(
        row["entity_name"] == "suppliers" and row["entity_id"] == supplier.json()["supplier_id"]
        for row in audit_a.json()["items"]
    )
    assert any(
        row["entity_name"] == "suppliers" and row["entity_id"] == supplier.json()["supplier_id"]
        for row in audit_b.json()["items"]
    )

    vehicle_id = _create_vehicle(marker)
    supplier_id = supplier.json()["supplier_id"]
    customer_id = customer.json()["customer_id"]
    purchase = _request_as(
        "Manager",
        user_id=4,
        business_id=business_b,
        method="POST",
        path="/api/purchases",
        json={
            "supplier_id": supplier_id,
            "purchase_date": date.today().isoformat(),
            "purchase_reference": f"ISOLATION-PUR-{marker}",
            "items": [{"vehicle_id": vehicle_id, "purchase_price": "1000.00"}],
            "initial_payment": {"amount": "100.00", "payment_method": "CASH"},
        },
    )
    assert purchase.status_code == 201, purchase.text
    sale = _request_as(
        "Manager",
        user_id=4,
        business_id=business_b,
        method="POST",
        path="/api/sales",
        json={
            "customer_id": customer_id,
            "sale_date": date.today().isoformat(),
            "sale_reference": f"ISOLATION-SALE-{marker}",
            "items": [{"vehicle_id": vehicle_id, "selling_price": "2000.00"}],
            "initial_payment": {"amount": "200.00", "payment_method": "CASH"},
        },
    )
    assert sale.status_code == 201, sale.text
    payments_b = _request_as("Manager", user_id=4, business_id=business_b, path="/api/payments")
    assert payments_b.status_code == 200, payments_b.text
    sale_payment = next(
        payment for payment in payments_b.json()["payments"]
        if payment["sale_id"] == sale.json()["sale_id"]
    )
    sale_invoice_b = _request_as(
        "Business Owner",
        user_id=2,
        business_id=business_b,
        path=f"/api/sales/{sale.json()['sale_id']}/invoice.pdf",
    )
    payment_receipt_b = _request_as(
        "Business Owner",
        user_id=2,
        business_id=business_b,
        path=f"/api/payments/{sale_payment['payment_id']}/receipt.pdf",
    )
    assert sale_invoice_b.status_code == 200
    assert payment_receipt_b.status_code == 200
    supplier_history_b = _request_as(
        "Business Owner",
        user_id=2,
        business_id=business_b,
        path=f"/api/suppliers/{supplier_id}/purchases",
    )
    customer_history_b = _request_as(
        "Business Owner",
        user_id=2,
        business_id=business_b,
        path=f"/api/customers/{customer_id}/sales",
    )
    assert supplier_history_b.status_code == 200
    assert customer_history_b.status_code == 200
    assert len(supplier_history_b.json()["purchases"]) == 1
    assert len(customer_history_b.json()["sales"]) == 1
    for path in ("/api/suppliers", "/api/customers"):
        response = _request_as("Business Owner", path=path, params={"q": marker})
        assert response.status_code == 200, response.text
        assert marker not in response.text

    list_paths = ("/api/purchases", "/api/sales", "/api/payments")
    for path in list_paths:
        response = _request_as("Business Owner", path=path)
        assert response.status_code == 200, response.text
        collection = response.json()[path.rsplit("/", 1)[-1]]
        assert all(
            item.get("purchase_id") != purchase.json()["purchase_id"]
            and item.get("sale_id") != sale.json()["sale_id"]
            for item in collection
        )

    for path in (
        f"/api/suppliers/{supplier_id}",
        f"/api/customers/{customer_id}",
        f"/api/suppliers/{supplier_id}/purchases",
        f"/api/customers/{customer_id}/sales",
        f"/api/purchases/{purchase.json()['purchase_id']}",
        f"/api/sales/{sale.json()['sale_id']}",
        f"/api/inventory/{vehicle_id}",
        f"/api/payments/{sale_payment['payment_id']}",
        f"/api/sales/{sale.json()['sale_id']}/invoice.pdf",
        f"/api/payments/{sale_payment['payment_id']}/receipt.pdf",
    ):
        response = _request_as("Business Owner", path=path)
        assert response.status_code == 404, (path, response.text)

    cross_update = _request_as(
        "Business Owner",
        method="PATCH",
        path=f"/api/suppliers/{supplier_id}",
        json={"supplier_name": "Unauthorized cross-business edit"},
    )
    assert cross_update.status_code == 404, cross_update.text
    cross_payment_update = _request_as(
        "Business Owner",
        method="PATCH",
        path=f"/api/payments/{sale_payment['payment_id']}",
        json={"payment_status": "FAILED"},
    )
    assert cross_payment_update.status_code == 404, cross_payment_update.text
    report_after = _request_as("Business Owner", path="/api/reports/financial")
    assert report_after.status_code == 200, report_after.text
    assert (
        report_after.json()["totals"]["total_sales"]
        == report_before.json()["totals"]["total_sales"]
    )
    assert (
        report_after.json()["totals"]["total_purchases"]
        == report_before.json()["totals"]["total_purchases"]
    )
    assert business_a != business_b
