import asyncio
import csv
import io
import secrets
import uuid
from datetime import date

import httpx
import pytest
from fastapi import HTTPException

from backend.auth import hash_password, verify_password
from backend.database import get_connection
from backend.main import app
from backend.security import (
    ACTIVE_BUSINESS_ROLES,
    LEGACY_ROLES,
    ROLE_PERMISSION_DEFAULTS,
    authorize_platform_admin,
    resolve_permissions,
)


def _ensure_test_business_membership(user_id: int, role_name: str) -> int:
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT business_id FROM businesses WHERE business_name = %s",
                    ("AutoLedger auth test business",),
                )
                business = cursor.fetchone()
                if business is None:
                    cursor.execute(
                        "INSERT INTO businesses (business_name) VALUES (%s) RETURNING business_id",
                        ("AutoLedger auth test business",),
                    )
                    business_id = cursor.fetchone()[0]
                else:
                    business_id = business[0]
                cursor.execute("SELECT role_id FROM roles WHERE role_name = %s", (role_name,))
                role_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO business_memberships (user_id, business_id, role_id, is_active)
                    VALUES (%s, %s, %s, TRUE)
                    ON CONFLICT (user_id, business_id)
                    DO UPDATE SET role_id = EXCLUDED.role_id, is_active = TRUE
                    """,
                    (user_id, business_id, role_id),
                )
        return business_id
    finally:
        connection.close()


def test_bcrypt_password_hash_round_trip_and_long_input():
    password = "AutoLedger-" + secrets.token_urlsafe(80)
    encoded = hash_password(password)

    assert encoded.startswith("$2")
    assert verify_password(password, encoded)
    assert not verify_password("not-the-password", encoded)


def test_approved_role_permission_defaults():
    assert ACTIVE_BUSINESS_ROLES == {
        "Super Admin", "Admin", "Business Owner", "Manager",
        "Accountant", "Staff", "Viewer",
    }
    assert LEGACY_ROLES == {"Dealer", "Inspector", "Owner/Viewer", "Verification User"}
    admin = ROLE_PERMISSION_DEFAULTS["Admin"]
    assert {"vehicles.read", "history.read", "customers.manage", "suppliers.manage",
            "inventory.manage", "purchases.manage", "sales.manage", "payments.manage"}.issubset(admin)
    assert not {
        "users.manage", "audit.read", "vehicles.manage", "vehicles.delete",
        "owners.manage", "history.manage", "verification.manage",
    }.intersection(admin)
    for role_name in ACTIVE_BUSINESS_ROLES - {"Super Admin"}:
        assert not {
            "vehicles.manage", "vehicles.delete", "owners.manage",
            "history.manage", "verification.manage",
        }.intersection(ROLE_PERMISSION_DEFAULTS[role_name])

    assert ROLE_PERMISSION_DEFAULTS["Accountant"].issuperset(
        {"payments.manage", "financial.read", "reports.financial", "invoices.read"}
    )
    assert resolve_permissions("Viewer", {"vehicles.read", "vehicles.manage"}) == {"vehicles.read"}
    assert resolve_permissions("Dealer", {"vehicles.read", "sales.manage"}) == frozenset()
    assert resolve_permissions("Super Admin", set()) == {"*"}


def test_only_super_admin_can_change_shared_vehicle_or_history_data():
    with pytest.raises(HTTPException) as exc_info:
        authorize_platform_admin({"role_name": "Admin"})
    assert getattr(exc_info.value, "status_code", None) == 403
    assert authorize_platform_admin({"role_name": "Super Admin"})["role_name"] == "Super Admin"


def test_vehicle_read_routes_require_authentication():
    async def request_vehicle_routes():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            responses = await asyncio.gather(
                client.get("/api/vehicles"),
                client.get("/api/vehicles/1"),
                client.get("/api/vehicles/1/history"),
            )
            assert [response.status_code for response in responses] == [401, 401, 401]

    asyncio.run(request_vehicle_routes())


def test_viewer_registration_login_and_role_restrictions():
    email = f"pytest-{uuid.uuid4().hex}@example.test"
    password = secrets.token_urlsafe(24)
    user_id = None

    try:
        async def exercise_auth_flow():
            nonlocal user_id
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                created = await client.post(
                    "/api/auth/register",
                    json={"full_name": "Pytest Viewer", "email": email, "password": password},
                )
                assert created.status_code == 201, created.text
                user_id = created.json()["user"]["user_id"]
                business_id = _ensure_test_business_membership(user_id, "Viewer")

                logged_in = await client.post("/api/auth/login", json={"email": email, "password": password})
                assert logged_in.status_code == 200, logged_in.text
                token = logged_in.json()["access_token"]
                headers = {
                    "Authorization": f"Bearer {token}",
                    "X-Business-ID": str(business_id),
                }

                profile = await client.get("/api/auth/me", headers=headers)
                assert profile.status_code == 200
                assert profile.json()["role_name"] == "Viewer"
                dashboard = await client.get("/api/dashboard", headers=headers)
                assert dashboard.status_code == 200
                assert dashboard.json()["activity"] == []
                assert (await client.get("/api/records/audit", headers=headers)).status_code == 403
                assert (await client.get("/api/dashboard")).status_code == 401

        asyncio.run(exercise_auth_flow())
    finally:
        if user_id is not None:
            connection = get_connection()
            try:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "DELETE FROM business_memberships WHERE user_id = %s",
                            (user_id,),
                        )
                        cursor.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
                        cursor.execute(
                            "DELETE FROM audit_logs WHERE user_id=%s OR (entity_name='users' AND entity_id=%s)",
                            (user_id, user_id),
                        )
            finally:
                connection.close()


def test_refresh_rotation_password_change_and_logout_revoke_sessions():
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.auth_refresh_tokens')")
            if cursor.fetchone()[0] is None:
                pytest.skip("The proposed authentication migration is not installed on this test database.")
    finally:
        connection.close()

    email = f"pytest-session-{uuid.uuid4().hex}@example.test"
    initial_password = secrets.token_urlsafe(24)
    next_password = secrets.token_urlsafe(24)
    user_id = None

    async def exercise_sessions():
        nonlocal user_id
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                registration = await client.post(
                    "/api/auth/register",
                    json={"full_name": "Session Test", "email": email, "password": initial_password},
                )
                assert registration.status_code == 201, registration.text
                user_id = registration.json()["user"]["user_id"]

                login = await client.post(
                    "/api/auth/login",
                    json={"email": email, "password": initial_password},
                )
                assert login.status_code == 200, login.text
                old_access = login.json()["access_token"]
                original_refresh = client.cookies.get("autoledger_refresh")
                assert original_refresh

                rotated = await client.post("/api/auth/refresh")
                assert rotated.status_code == 200, rotated.text
                rotated_refresh = client.cookies.get("autoledger_refresh")
                assert rotated_refresh and rotated_refresh != original_refresh
                client.cookies.set("autoledger_refresh", original_refresh, path="/api/auth")
                replay = await client.post("/api/auth/refresh")
                assert replay.status_code == 401
                client.cookies.set("autoledger_refresh", rotated_refresh, path="/api/auth")

                headers = {"Authorization": f"Bearer {rotated.json()['access_token']}"}
                profile = await client.patch("/api/auth/me", headers=headers, json={"full_name": "Session Test Updated"})
                assert profile.status_code == 200, profile.text
                changed = await client.post(
                    "/api/auth/password",
                    headers=headers,
                    json={"current_password": initial_password, "new_password": next_password},
                )
                assert changed.status_code == 200, changed.text
                assert (await client.get("/api/auth/me", headers=headers)).status_code == 401
                assert (await client.post("/api/auth/refresh")).status_code == 401

                new_login = await client.post(
                    "/api/auth/login",
                    json={"email": email, "password": next_password},
                )
                assert new_login.status_code == 200, new_login.text
                signed_out = await client.post("/api/auth/logout")
                assert signed_out.status_code == 200, signed_out.text
                assert (await client.post("/api/auth/refresh")).status_code == 401

    try:
        asyncio.run(exercise_sessions())
    finally:
        if user_id is not None:
                connection = get_connection()
                try:
                    with connection:
                        with connection.cursor() as cursor:
                            cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
                            cursor.execute(
                                "DELETE FROM audit_logs WHERE user_id = %s OR (entity_name = 'users' AND entity_id = %s)",
                                (user_id, user_id),
                            )
                finally:
                    connection.close()


def test_role_logins_permissions_and_duplicate_vin_response():
    password = secrets.token_urlsafe(24)
    accounts = {}
    created_records = {
        "services": [],
        "repairs": [],
        "mileage": [],
        "documents": [],
        "inspections": [],
        "verification": [],
    }
    created_owner_ids = []
    created_user_ids = []
    test_business_id = None
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                for role_name in (
                    "Admin", "Super Admin", "Business Owner", "Manager", "Accountant",
                    "Staff", "Viewer", "Inspector", "Dealer", "Owner/Viewer",
                    "Verification User",
                ):
                    cursor.execute("SELECT role_id FROM roles WHERE role_name=%s", (role_name,))
                    role = cursor.fetchone()
                    email_role = role_name.lower().replace("/", "-").replace(" ", "-")
                    email = f"pytest-{email_role}-{uuid.uuid4().hex}@example.test"
                    cursor.execute(
                        "INSERT INTO users (role_id, full_name, email, password_hash) VALUES (%s, %s, %s, %s) RETURNING user_id",
                        (role[0], f"Pytest {role_name}", email, hash_password(password)),
                    )
                    accounts[role_name] = {"user_id": cursor.fetchone()[0], "email": email}
                cursor.execute("SELECT vehicle_id, vin, brand FROM vehicles ORDER BY vehicle_id LIMIT 1")
                existing_vehicle_id, existing_vin, existing_brand = cursor.fetchone()
    finally:
        connection.close()

    for role_name in ACTIVE_BUSINESS_ROLES:
        test_business_id = _ensure_test_business_membership(
            accounts[role_name]["user_id"], role_name
        )

    try:
        async def exercise_role_permissions():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                headers_by_role = {}
                for role_name, account in accounts.items():
                    response = await client.post(
                        "/api/auth/login",
                        json={"email": account["email"], "password": password},
                    )
                    assert response.status_code == 200, response.text
                    assert response.json()["user"]["role"] == role_name
                    headers_by_role[role_name] = {
                        "Authorization": f"Bearer {response.json()['access_token']}",
                        "X-Business-ID": str(test_business_id),
                    }

                admin_headers = headers_by_role["Admin"]
                super_admin_headers = headers_by_role["Super Admin"]
                dealer_headers = headers_by_role["Dealer"]
                inspector_headers = headers_by_role["Viewer"]
                viewer_headers = headers_by_role["Viewer"]
                verification_headers = headers_by_role["Verification User"]
                verification_headers["X-Business-ID"] = "1"
                for role_name, headers in headers_by_role.items():
                    expected = 403 if role_name not in {
                        "Super Admin", "Admin", "Business Owner", "Manager", "Staff", "Viewer",
                    } else 200
                    vehicle_access = await client.get("/api/vehicles", headers=headers)
                    dashboard_access = await client.get("/api/dashboard", headers=headers)
                    assert vehicle_access.status_code == expected, (role_name, vehicle_access.text)
                    assert dashboard_access.status_code == expected, (
                        role_name,
                        dashboard_access.text,
                    )
                assert (await client.get("/api/auth/roles", headers=admin_headers)).status_code == 403
                assert (await client.get("/api/auth/roles", headers=super_admin_headers)).status_code == 200
                assert (await client.get("/api/auth/roles", headers=super_admin_headers)).json()["roles"]
                assert all(
                    role["role_name"] in ACTIVE_BUSINESS_ROLES
                    for role in (await client.get("/api/auth/roles", headers=super_admin_headers)).json()["roles"]
                )
                legacy_role_assignment = await client.post(
                    "/api/auth/users",
                    headers=super_admin_headers,
                    json={
                        "full_name": "Legacy Role Assignment",
                        "email": f"pytest-legacy-{uuid.uuid4().hex}@example.test",
                        "password": secrets.token_urlsafe(24),
                        "role": "Dealer",
                    },
                )
                assert legacy_role_assignment.status_code == 422
                proposed_super_admin = {
                    "full_name": "Second Super Admin",
                    "email": f"pytest-new-superadmin-{uuid.uuid4().hex}@example.test",
                    "password": secrets.token_urlsafe(24),
                    "role": "Super Admin",
                }
                denied_super_admin = await client.post(
                    "/api/auth/users",
                    headers=admin_headers,
                    json=proposed_super_admin,
                )
                assert denied_super_admin.status_code == 403
                created_super_admin = await client.post(
                    "/api/auth/users",
                    headers=super_admin_headers,
                    json=proposed_super_admin,
                )
                assert created_super_admin.status_code == 201, created_super_admin.text
                created_user_ids.append(created_super_admin.json()["user"]["user_id"])
                vehicle_search = await client.get(
                    "/api/vehicles",
                    params={"search": existing_vin},
                    headers=viewer_headers,
                )
                assert vehicle_search.status_code == 200
                assert vehicle_search.json()["count"] == 1
                assert vehicle_search.json()["vehicles"][0]["vehicle_id"] == existing_vehicle_id
                filtered_vehicles = await client.get(
                    "/api/vehicles",
                    params={"brand": existing_brand, "page_size": 100},
                    headers=viewer_headers,
                )
                assert filtered_vehicles.status_code == 200
                assert filtered_vehicles.json()["count"] >= 1
                assert all(vehicle["brand"] == existing_brand for vehicle in filtered_vehicles.json()["vehicles"])
                detail = await client.get(f"/api/vehicles/{existing_vehicle_id}", headers=viewer_headers)
                assert detail.status_code == 200
                assert detail.json()["vehicle"]["vin"] == existing_vin
                denied_vehicle_write = await client.post(
                    "/api/vehicles",
                    headers=viewer_headers,
                    json={
                        "vin": f"DENY{uuid.uuid4().hex[:13]}",
                        "registration_no": f"DENY-{uuid.uuid4().hex[:8]}",
                        "brand": "Test",
                        "model": "Denied",
                        "model_year": 2026,
                    },
                )
                assert denied_vehicle_write.status_code == 403
                denied_admin_vehicle_write = await client.post(
                    "/api/vehicles",
                    headers=admin_headers,
                    json={
                        "vin": f"ADMIN{uuid.uuid4().hex[:12]}",
                        "registration_no": f"ADMIN-{uuid.uuid4().hex[:8]}",
                        "brand": "Test",
                        "model": "Shared record denied",
                        "model_year": 2026,
                    },
                )
                assert denied_admin_vehicle_write.status_code == 403
                created_shared_vehicle = await client.post(
                    "/api/vehicles",
                    headers=super_admin_headers,
                    json={
                        "vin": f"PLATFORM{uuid.uuid4().hex[:9]}",
                        "registration_no": f"PLATFORM-{uuid.uuid4().hex[:8]}",
                        "brand": "Test",
                        "model": "Platform controlled",
                        "model_year": 2026,
                    },
                )
                assert created_shared_vehicle.status_code == 201, created_shared_vehicle.text
                created_vehicle_id = created_shared_vehicle.json()["vehicle"]["vehicle_id"]
                deleted_shared_vehicle = await client.delete(
                    f"/api/vehicles/{created_vehicle_id}",
                    headers=super_admin_headers,
                )
                assert deleted_shared_vehicle.status_code == 204
                denied_dealer_transfer = await client.post(
                    f"/api/vehicles/{existing_vehicle_id}/transfer",
                    headers=dealer_headers,
                    json={"new_owner_id": 1, "transfer_date": date.today().isoformat()},
                )
                assert denied_dealer_transfer.status_code == 403
                denied_admin_transfer = await client.post(
                    f"/api/vehicles/{existing_vehicle_id}/transfer",
                    headers=admin_headers,
                    json={"new_owner_id": 1, "transfer_date": date.today().isoformat()},
                )
                assert denied_admin_transfer.status_code == 403
                history = await client.get(f"/api/vehicles/{existing_vehicle_id}/history", headers=viewer_headers)
                assert history.status_code == 200
                assert history.json()["vehicle"]["vehicle_id"] == existing_vehicle_id
                assert "services" in history.json() and "mileage" in history.json()
                history_pdf = await client.get(
                    f"/api/reports/vehicles/{existing_vehicle_id}.pdf",
                    headers=viewer_headers,
                )
                assert history_pdf.status_code == 200
                assert history_pdf.headers["content-type"].startswith("application/pdf")
                assert history_pdf.content.startswith(b"%PDF-")
                assert b"%%EOF" in history_pdf.content[-2048:]
                dashboard = await client.get("/api/dashboard", headers=viewer_headers)
                assert dashboard.status_code == 200
                vehicle_count = await client.get(
                    "/api/vehicles",
                    params={"page_size": 1},
                    headers=viewer_headers,
                )
                assert dashboard.json()["kpis"]["total_vehicles"] == vehicle_count.json()["count"]
                csv_report = await client.get(
                    "/api/reports/vehicles.csv",
                    params={"brand": existing_brand, "date_from": "1980-01-01", "date_to": "2035-12-31"},
                    headers=viewer_headers,
                )
                assert csv_report.status_code == 200
                csv_rows = list(csv.DictReader(io.StringIO(csv_report.text)))
                assert csv_rows
                assert all(row["brand"] == existing_brand for row in csv_rows)
                date_filtered_csv = await client.get(
                    "/api/reports/vehicles.csv",
                    params={"brand": existing_brand, "date_from": "2099-01-01", "date_to": "2099-12-31"},
                    headers=viewer_headers,
                )
                assert date_filtered_csv.status_code == 200
                assert list(csv.DictReader(io.StringIO(date_filtered_csv.text))) == []
                assert (await client.get("/api/auth/users", headers=admin_headers)).status_code == 403
                assert (await client.get("/api/auth/users", headers=super_admin_headers)).status_code == 200
                fetched_user = await client.get(
                    f"/api/auth/users/{accounts['Inspector']['user_id']}",
                    headers=super_admin_headers,
                )
                assert fetched_user.status_code == 200
                assert fetched_user.json()["user"]["role_name"] == "Inspector"
                assert (await client.get("/api/auth/users", headers=inspector_headers)).status_code == 403
                assert (await client.get("/api/records/audit", headers=admin_headers)).status_code == 403
                assert (await client.get("/api/records/audit", headers=super_admin_headers)).status_code == 200
                assert (await client.get("/api/records/audit", headers=inspector_headers)).status_code == 403
                assert (await client.get("/api/vehicles", headers=dealer_headers)).status_code == 403

                duplicate = await client.post(
                    "/api/vehicles",
                    headers=super_admin_headers,
                    json={
                        "vin": existing_vin,
                        "registration_no": f"DUP-{uuid.uuid4().hex[:10]}",
                        "brand": "Test",
                        "model": "Duplicate",
                        "model_year": 2026,
                    },
                )
                assert duplicate.status_code == 409
                assert "VIN" in duplicate.json()["detail"]
                assert "duplicate key" not in duplicate.text.lower()

                latest_reading = get_connection()
                try:
                    with latest_reading.cursor() as cursor:
                        cursor.execute(
                            "SELECT mileage FROM mileage_records WHERE vehicle_id=1 ORDER BY recorded_date DESC, mileage_id DESC LIMIT 1"
                        )
                        mileage = cursor.fetchone()[0] + 100
                finally:
                    latest_reading.close()

                record_cases = [
                    ("services", {"vehicle_id": 1, "service_date": date.today().isoformat(), "service_type": "Pytest service", "cost": 1}, {"notes": "updated"}),
                    ("repairs", {"vehicle_id": 1, "repair_date": date.today().isoformat(), "repair_type": "Pytest repair", "cost": 1}, {"description": "updated"}),
                    ("mileage", {"vehicle_id": 1, "recorded_date": date.today().isoformat(), "mileage": mileage, "source": "OTHER"}, {"mileage": mileage + 1}),
                    ("documents", {"vehicle_id": 1, "document_type": "Pytest document", "issue_date": date.today().isoformat(), "expiry_date": date(date.today().year + 1, date.today().month, date.today().day).isoformat(), "status": "VALID"}, {"document_number": "TEST-UPDATED"}),
                    ("inspections", {"vehicle_id": 1, "inspection_date": date.today().isoformat(), "result": "PASS"}, {"remarks": "updated"}),
                    ("verification", {"vehicle_id": 1, "verification_date": date.today().isoformat(), "result": "VERIFIED"}, {"remarks": "updated"}),
                ]
                for resource, payload, patch in record_cases:
                    created = await client.post(f"/api/records/{resource}", headers=super_admin_headers, json=payload)
                    assert created.status_code == 201, created.text
                    record_id = created.json()["id"]
                    created_records[resource].append(record_id)
                    fetched = await client.get(f"/api/records/{resource}/{record_id}", headers=inspector_headers)
                    assert fetched.status_code == 200, fetched.text
                    updated = await client.patch(f"/api/records/{resource}/{record_id}", headers=super_admin_headers, json=patch)
                    assert updated.status_code == 200, updated.text
                    deleted = await client.delete(f"/api/records/{resource}/{record_id}", headers=super_admin_headers)
                    assert deleted.status_code == 204, deleted.text
                    denied_admin_write = await client.post(
                        f"/api/records/{resource}",
                        headers=admin_headers,
                        json=payload,
                    )
                    assert denied_admin_write.status_code == 403, (resource, denied_admin_write.text)

                inspection = await client.post(
                    "/api/records/inspections",
                    headers=super_admin_headers,
                    json={"vehicle_id": 1, "inspection_date": date.today().isoformat(), "result": "PASS"},
                )
                assert inspection.status_code == 201, inspection.text
                created_records["inspections"].append(inspection.json()["id"])

                verification = await client.post(
                    "/api/records/verification",
                    headers=super_admin_headers,
                    json={"vehicle_id": 1, "verification_date": date.today().isoformat(), "result": "VERIFIED"},
                )
                assert verification.status_code == 201, verification.text
                created_records["verification"].append(verification.json()["id"])

                for resource, payload, _patch in record_cases:
                    denied_write = await client.post(
                        f"/api/records/{resource}",
                        headers=inspector_headers,
                        json=payload,
                    )
                    assert denied_write.status_code == 403, (resource, denied_write.text)

                denied = await client.post(
                    "/api/records/inspections",
                    headers=viewer_headers,
                    json={"vehicle_id": 1, "inspection_date": date.today().isoformat(), "result": "PASS"},
                )
                assert denied.status_code == 403
                for path in (
                    "/api/dashboard",
                    "/api/search?q=test",
                    "/api/vehicles",
                    "/api/vehicles/1/history",
                    "/api/records/owners",
                    "/api/reports/vehicles.csv",
                    "/api/reports/vehicles/1.pdf",
                    "/api/inventory",
                ):
                    denied = await client.get(path, headers=verification_headers)
                    assert denied.status_code == 403, (path, denied.text)

                owner = await client.post(
                    "/api/records/owners",
                    headers=super_admin_headers,
                    json={"full_name": f"Pytest CRUD {uuid.uuid4().hex}"},
                )
                assert owner.status_code == 201, owner.text
                owner_id = owner.json()["id"]
                created_owner_ids.append(owner_id)
                fetched_owner = await client.get(f"/api/records/owners/{owner_id}", headers=super_admin_headers)
                assert fetched_owner.status_code == 200
                assert fetched_owner.json()["record"]["owner_id"] == owner_id
                changed = await client.patch(
                    f"/api/records/owners/{owner_id}",
                    headers=super_admin_headers,
                    json={"phone": "TEST-ONLY"},
                )
                assert changed.status_code == 200, changed.text
                removed_owner = await client.delete(f"/api/records/owners/{owner_id}", headers=super_admin_headers)
                assert removed_owner.status_code == 204, removed_owner.text

                referenced = get_connection()
                try:
                    with referenced.cursor() as cursor:
                        cursor.execute("SELECT owner_id FROM ownership_records ORDER BY ownership_id LIMIT 1")
                        referenced_owner_id = cursor.fetchone()[0]
                finally:
                    referenced.close()
                conflict = await client.delete(
                    f"/api/records/owners/{referenced_owner_id}",
                    headers=super_admin_headers,
                )
                assert conflict.status_code == 409

                deactivated = await client.patch(
                    f"/api/auth/users/{accounts['Inspector']['user_id']}",
                    headers=super_admin_headers,
                    json={"is_active": False},
                )
                assert deactivated.status_code == 200, deactivated.text
                assert deactivated.json()["user"]["is_active"] is False

        asyncio.run(exercise_role_permissions())
    finally:
        cleanup = get_connection()
        try:
            with cleanup:
                with cleanup.cursor() as cursor:
                    record_tables = {
                        "services": ("service_records", "service_id"),
                        "repairs": ("repair_records", "repair_id"),
                        "mileage": ("mileage_records", "mileage_id"),
                        "documents": ("documents", "document_id"),
                        "inspections": ("inspections", "inspection_id"),
                        "verification": ("verification_records", "verification_id"),
                    }
                    for resource, (table_name, id_column) in record_tables.items():
                        record_ids = created_records[resource]
                        if record_ids:
                            cursor.execute(f"DELETE FROM {table_name} WHERE {id_column} = ANY(%s)", (record_ids,))
                    user_ids = [account["user_id"] for account in accounts.values()] + created_user_ids
                    if user_ids:
                        cursor.execute(
                            "DELETE FROM business_memberships WHERE user_id = ANY(%s)",
                            (user_ids,),
                        )
                    if created_owner_ids:
                        cursor.execute("DELETE FROM owners WHERE owner_id = ANY(%s)", (created_owner_ids,))
                    if user_ids:
                        cursor.execute("DELETE FROM users WHERE user_id = ANY(%s)", (user_ids,))
                    audit_entities = {
                        "users": user_ids,
                        "service_records": created_records["services"],
                        "repair_records": created_records["repairs"],
                        "mileage_records": created_records["mileage"],
                        "documents": created_records["documents"],
                        "inspections": created_records["inspections"],
                        "verification_records": created_records["verification"],
                        "owners": created_owner_ids,
                    }
                    for entity_name, entity_ids in audit_entities.items():
                        if entity_ids:
                            cursor.execute(
                                "DELETE FROM audit_logs WHERE entity_name=%s AND entity_id = ANY(%s)",
                                (entity_name, entity_ids),
                            )
                    if user_ids:
                        cursor.execute("DELETE FROM audit_logs WHERE user_id = ANY(%s)", (user_ids,))
        finally:
            cleanup.close()