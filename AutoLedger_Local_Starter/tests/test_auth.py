import asyncio
import csv
import io
import secrets
import uuid
from datetime import date

import httpx

from backend.auth import hash_password, verify_password
from backend.database import get_connection
from backend.main import app


def test_bcrypt_password_hash_round_trip_and_long_input():
    password = "AutoLedger-" + secrets.token_urlsafe(80)
    encoded = hash_password(password)

    assert encoded.startswith("$2")
    assert verify_password(password, encoded)
    assert not verify_password("not-the-password", encoded)


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

                logged_in = await client.post("/api/auth/login", json={"email": email, "password": password})
                assert logged_in.status_code == 200, logged_in.text
                token = logged_in.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}

                profile = await client.get("/api/auth/me", headers=headers)
                assert profile.status_code == 200
                assert profile.json()["role_name"] == "Owner/Viewer"
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
                        cursor.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
                        cursor.execute(
                            "DELETE FROM audit_logs WHERE user_id=%s OR (entity_name='users' AND entity_id=%s)",
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
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                for role_name in ("Admin", "Inspector", "Dealer", "Owner/Viewer"):
                    cursor.execute("SELECT role_id FROM roles WHERE role_name=%s", (role_name,))
                    role = cursor.fetchone()
                    email = f"pytest-{role_name.lower().replace('/', '-')}-{uuid.uuid4().hex}@example.test"
                    cursor.execute(
                        "INSERT INTO users (role_id, full_name, email, password_hash) VALUES (%s, %s, %s, %s) RETURNING user_id",
                        (role[0], f"Pytest {role_name}", email, hash_password(password)),
                    )
                    accounts[role_name] = {"user_id": cursor.fetchone()[0], "email": email}
                cursor.execute("SELECT vehicle_id, vin, brand FROM vehicles ORDER BY vehicle_id LIMIT 1")
                existing_vehicle_id, existing_vin, existing_brand = cursor.fetchone()
    finally:
        connection.close()

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
                    headers_by_role[role_name] = {"Authorization": f"Bearer {response.json()['access_token']}"}

                admin_headers = headers_by_role["Admin"]
                inspector_headers = headers_by_role["Inspector"]
                viewer_headers = headers_by_role["Owner/Viewer"]
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
                assert (await client.get("/api/auth/users", headers=admin_headers)).status_code == 200
                fetched_user = await client.get(
                    f"/api/auth/users/{accounts['Inspector']['user_id']}",
                    headers=admin_headers,
                )
                assert fetched_user.status_code == 200
                assert fetched_user.json()["user"]["role_name"] == "Inspector"
                assert (await client.get("/api/auth/users", headers=inspector_headers)).status_code == 403
                assert (await client.get("/api/records/audit", headers=admin_headers)).status_code == 200
                assert (await client.get("/api/records/audit", headers=inspector_headers)).status_code == 403

                duplicate = await client.post(
                    "/api/vehicles",
                    headers=admin_headers,
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
                    created = await client.post(f"/api/records/{resource}", headers=inspector_headers, json=payload)
                    assert created.status_code == 201, created.text
                    record_id = created.json()["id"]
                    created_records[resource].append(record_id)
                    fetched = await client.get(f"/api/records/{resource}/{record_id}", headers=inspector_headers)
                    assert fetched.status_code == 200, fetched.text
                    updated = await client.patch(f"/api/records/{resource}/{record_id}", headers=inspector_headers, json=patch)
                    assert updated.status_code == 200, updated.text
                    deleted = await client.delete(f"/api/records/{resource}/{record_id}", headers=admin_headers)
                    assert deleted.status_code == 204, deleted.text

                inspection = await client.post(
                    "/api/records/inspections",
                    headers=inspector_headers,
                    json={"vehicle_id": 1, "inspection_date": date.today().isoformat(), "result": "PASS"},
                )
                assert inspection.status_code == 201, inspection.text
                created_records["inspections"].append(inspection.json()["id"])

                verification = await client.post(
                    "/api/records/verification",
                    headers=inspector_headers,
                    json={"vehicle_id": 1, "verification_date": date.today().isoformat(), "result": "VERIFIED"},
                )
                assert verification.status_code == 201, verification.text
                created_records["verification"].append(verification.json()["id"])

                denied = await client.post(
                    "/api/records/inspections",
                    headers=viewer_headers,
                    json={"vehicle_id": 1, "inspection_date": date.today().isoformat(), "result": "PASS"},
                )
                assert denied.status_code == 403

                owner = await client.post(
                    "/api/records/owners",
                    headers=admin_headers,
                    json={"full_name": f"Pytest CRUD {uuid.uuid4().hex}"},
                )
                assert owner.status_code == 201, owner.text
                owner_id = owner.json()["id"]
                created_owner_ids.append(owner_id)
                fetched_owner = await client.get(f"/api/records/owners/{owner_id}", headers=admin_headers)
                assert fetched_owner.status_code == 200
                assert fetched_owner.json()["record"]["owner_id"] == owner_id
                changed = await client.patch(
                    f"/api/records/owners/{owner_id}",
                    headers=admin_headers,
                    json={"phone": "TEST-ONLY"},
                )
                assert changed.status_code == 200, changed.text
                removed_owner = await client.delete(f"/api/records/owners/{owner_id}", headers=admin_headers)
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
                    headers=admin_headers,
                )
                assert conflict.status_code == 409

                deactivated = await client.patch(
                    f"/api/auth/users/{accounts['Inspector']['user_id']}",
                    headers=admin_headers,
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
                    user_ids = [account["user_id"] for account in accounts.values()]
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