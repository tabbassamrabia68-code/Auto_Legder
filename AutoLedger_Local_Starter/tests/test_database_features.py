import asyncio
from datetime import date, timedelta
import uuid

import httpx
import psycopg2
import pytest

from backend.database import get_connection
from backend.main import app
from backend.schemas import validate_record


@pytest.fixture
def connection():
    database = get_connection()
    try:
        yield database
    finally:
        database.rollback()
        database.close()


def test_health_executes_database_check():
    async def request_health():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/api/health")

    response = asyncio.run(request_health())
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_record_schemas_reject_invalid_values_and_unknown_fields():
    with pytest.raises(ValueError, match="mileage.*greater than or equal to 0"):
        validate_record(
            "mileage",
            {"vehicle_id": 1, "recorded_date": date.today(), "mileage": -1, "source": "OWNER"},
        )

    with pytest.raises(ValueError, match="expiry_date cannot precede issue_date"):
        validate_record(
            "documents",
            {
                "vehicle_id": 1,
                "document_type": "Registration",
                "issue_date": date.today(),
                "expiry_date": date.today().replace(year=date.today().year - 1),
                "status": "VALID",
            },
        )

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_record(
            "owners",
            {"full_name": "Valid Owner", "role_id": 1},
        )


def test_mileage_trigger_rejects_lower_odometer(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT mileage FROM mileage_records WHERE vehicle_id=1 ORDER BY recorded_date DESC, mileage_id DESC LIMIT 1"
        )
        latest = cursor.fetchone()
        if latest is None or latest[0] == 0:
            pytest.skip("Vehicle 1 needs an existing positive mileage reading for this test.")

        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO mileage_records (vehicle_id, recorded_date, mileage, source) VALUES (1, %s, %s, 'OTHER')",
                (date.today(), latest[0] - 1),
            )
    connection.rollback()


def test_mileage_trigger_rejects_rollback_for_temporary_vehicle(connection):
    marker = uuid.uuid4().hex[:10].upper()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO vehicles (vin, registration_no, brand, model, model_year) VALUES (%s, %s, 'Test', 'Mileage', 2026) RETURNING vehicle_id",
            (f"MILEAGE{marker}"[:17], f"MILEAGE-{marker}"),
        )
        vehicle_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO mileage_records (vehicle_id, recorded_date, mileage, source) VALUES (%s, %s, 100, 'OTHER')",
            (vehicle_id, date.today()),
        )
        cursor.execute("SAVEPOINT before_rollback_attempt")
        with pytest.raises(psycopg2.errors.CheckViolation, match="Mileage rollback rejected"):
            cursor.execute(
                "INSERT INTO mileage_records (vehicle_id, recorded_date, mileage, source) VALUES (%s, %s, 99, 'OTHER')",
                (vehicle_id, date.today()),
            )
        cursor.execute("ROLLBACK TO SAVEPOINT before_rollback_attempt")
        cursor.execute(
            "SELECT mileage FROM mileage_records WHERE vehicle_id=%s ORDER BY recorded_date, mileage_id",
            (vehicle_id,),
        )
        assert [row[0] for row in cursor.fetchall()] == [100]


def test_ownership_transfer_is_atomic_and_single_active(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ownership_id, owner_id, start_date FROM ownership_records WHERE vehicle_id=1 AND ownership_status='ACTIVE'"
        )
        current = cursor.fetchone()
        if current is None:
            pytest.skip("Vehicle 1 needs an active ownership row for this test.")
        cursor.execute("SELECT MIN(owner_id) FROM owners WHERE owner_id <> %s", (current[1],))
        new_owner_id = cursor.fetchone()[0]
        transfer_date = max(date.today(), current[2])

        cursor.execute("SELECT transfer_ownership(%s, %s, %s)", (1, new_owner_id, transfer_date))
        new_ownership_id = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM ownership_records WHERE vehicle_id=1 AND ownership_status='ACTIVE'"
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT ownership_status, end_date FROM ownership_records WHERE ownership_id=%s",
            (current[0],),
        )
        previous = cursor.fetchone()
        assert previous == ("TRANSFERRED", transfer_date)
        cursor.execute(
            "SELECT ownership_status FROM ownership_records WHERE ownership_id=%s",
            (new_ownership_id,),
        )
        assert cursor.fetchone()[0] == "ACTIVE"
        cursor.execute(
            """
            SELECT COUNT(*) FROM audit_logs
            WHERE entity_name='ownership_records' AND entity_id IN (%s, %s)
              AND action IN ('UPDATE', 'INSERT')
            """,
            (current[0], new_ownership_id),
        )
        assert cursor.fetchone()[0] == 2
    connection.rollback()


def test_transfer_function_success_and_failure_are_atomic_for_temporary_vehicle(connection):
    marker = uuid.uuid4().hex[:10].upper()
    transfer_date = date.today()
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO owners (full_name) VALUES (%s) RETURNING owner_id", (f"Transfer Old {marker}",))
        old_owner_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO owners (full_name) VALUES (%s) RETURNING owner_id", (f"Transfer New {marker}",))
        new_owner_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO vehicles (vin, registration_no, brand, model, model_year) VALUES (%s, %s, 'Test', 'Transfer', 2026) RETURNING vehicle_id",
            (f"TRANSFER{marker}"[:17], f"TRANSFER-{marker}"),
        )
        vehicle_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO ownership_records (vehicle_id, owner_id, start_date, ownership_status) VALUES (%s, %s, %s, 'ACTIVE') RETURNING ownership_id",
            (vehicle_id, old_owner_id, transfer_date),
        )
        old_ownership_id = cursor.fetchone()[0]

        cursor.execute("SAVEPOINT before_invalid_transfer")
        with pytest.raises(psycopg2.errors.CheckViolation, match="Transfer date cannot precede"):
            cursor.execute(
                "SELECT transfer_ownership(%s, %s, %s)",
                (vehicle_id, new_owner_id, transfer_date - timedelta(days=1)),
            )
        cursor.execute("ROLLBACK TO SAVEPOINT before_invalid_transfer")
        cursor.execute(
            "SELECT owner_id, ownership_status, end_date FROM ownership_records WHERE vehicle_id=%s AND ownership_status='ACTIVE'",
            (vehicle_id,),
        )
        assert cursor.fetchone() == (old_owner_id, "ACTIVE", None)

        cursor.execute(
            "SELECT transfer_ownership(%s, %s, %s)",
            (vehicle_id, new_owner_id, transfer_date),
        )
        new_ownership_id = cursor.fetchone()[0]
        cursor.execute(
            "SELECT owner_id, ownership_status, end_date FROM ownership_records WHERE ownership_id=%s",
            (old_ownership_id,),
        )
        assert cursor.fetchone() == (old_owner_id, "TRANSFERRED", transfer_date)
        cursor.execute(
            "SELECT owner_id, ownership_status, end_date FROM ownership_records WHERE ownership_id=%s",
            (new_ownership_id,),
        )
        assert cursor.fetchone() == (new_owner_id, "ACTIVE", None)
        cursor.execute(
            "SELECT COUNT(*) FROM ownership_records WHERE vehicle_id=%s AND ownership_status='ACTIVE'",
            (vehicle_id,),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT action FROM audit_logs WHERE entity_name='ownership_records' AND entity_id IN (%s, %s) ORDER BY audit_id",
            (old_ownership_id, new_ownership_id),
        )
        assert [row[0] for row in cursor.fetchall()] == ["INSERT", "UPDATE", "INSERT"]


def test_vehicle_audit_trigger_records_insert(connection):
    marker = uuid.uuid4().hex[:10].upper()
    vin = f"TEST{marker}"[:17]
    registration = f"TEST-{marker}"
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO vehicles (vin, registration_no, brand, model, model_year) VALUES (%s, %s, 'Test', 'Audit', 2026) RETURNING vehicle_id",
            (vin, registration),
        )
        vehicle_id = cursor.fetchone()[0]
        cursor.execute("UPDATE vehicles SET color='Blue' WHERE vehicle_id=%s", (vehicle_id,))
        cursor.execute("DELETE FROM vehicles WHERE vehicle_id=%s", (vehicle_id,))
        cursor.execute(
            "SELECT action FROM audit_logs WHERE entity_name='vehicles' AND entity_id=%s ORDER BY audit_id",
            (vehicle_id,),
        )
        assert [row[0] for row in cursor.fetchall()] == ["INSERT", "UPDATE", "DELETE"]
    connection.rollback()


def test_owner_audit_trigger_records_all_changes(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO owners (full_name) VALUES ('Pytest Audit Owner') RETURNING owner_id"
        )
        owner_id = cursor.fetchone()[0]
        cursor.execute(
            "UPDATE owners SET full_name='Pytest Updated Owner' WHERE owner_id=%s",
            (owner_id,),
        )
        cursor.execute("DELETE FROM owners WHERE owner_id=%s", (owner_id,))
        cursor.execute(
            "SELECT action FROM audit_logs WHERE entity_name='owners' AND entity_id=%s ORDER BY audit_id",
            (owner_id,),
        )
        assert [row[0] for row in cursor.fetchall()] == ["INSERT", "UPDATE", "DELETE"]
    connection.rollback()


def test_expired_document_trigger_sets_status(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO documents (vehicle_id, document_type, document_number, issue_date, expiry_date, status)
            VALUES (1, 'Pytest expiry', %s, CURRENT_DATE - 30, CURRENT_DATE - 1, 'VALID')
            RETURNING status
            """,
            (f"TEST-{uuid.uuid4().hex}",),
        )
        assert cursor.fetchone()[0] == "EXPIRED"
    connection.rollback()


def test_reporting_views_are_queryable(connection):
    with connection.cursor() as cursor:
        for view in (
            "vw_vehicle_summary",
            "vw_expiring_documents",
            "vw_monthly_costs",
            "vw_owner_history",
        ):
            cursor.execute(f"SELECT COUNT(*) FROM {view}")
            assert cursor.fetchone()[0] >= 0