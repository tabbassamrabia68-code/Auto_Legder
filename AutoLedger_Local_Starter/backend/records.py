import csv
import io
from datetime import date
from html import escape
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
import psycopg2
from psycopg2.extras import RealDictCursor
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.database import get_connection
from backend.schemas import validate_record
from backend.services import delete_ledger_record, get_ledger_record, insert_ledger_record, update_ledger_record
from backend.security import (
    authorize_platform_admin,
    authorize_permissions,
    get_business_context,
    get_current_user,
    has_permission,
    require_business_permissions,
    require_platform_admin,
)

router = APIRouter(prefix="/api", tags=["Ledger and reports"])
RESOURCE_READ_PERMISSIONS = {
    "owners": "owners.read",
    "ownership": "owners.read",
    "services": "history.read",
    "repairs": "history.read",
    "mileage": "history.read",
    "inspections": "verification.read",
    "documents": "history.read",
    "verification": "verification.read",
    "audit": "audit.read",
}

RESOURCE_QUERIES = {
    "owners": {
        "select": "SELECT o.owner_id, o.full_name, o.email, o.phone, o.created_at, COUNT(ow.ownership_id) FILTER (WHERE ow.ownership_status='ACTIVE') AS active_vehicles",
        "from": "FROM owners o LEFT JOIN ownership_records ow ON ow.owner_id=o.owner_id",
        "group": "GROUP BY o.owner_id",
        "search": ["o.full_name", "o.email", "o.phone"],
        "sort": {"owner_id": "o.owner_id", "name": "o.full_name", "created_at": "o.created_at"},
        "order": "o.full_name",
    },
    "ownership": {
        "select": "SELECT ow.ownership_id, ow.vehicle_id, ow.owner_id, ow.start_date, ow.end_date, ow.ownership_status, o.full_name AS owner_name, v.registration_no, v.brand, v.model",
        "from": "FROM ownership_records ow JOIN owners o USING(owner_id) JOIN vehicles v USING(vehicle_id)",
        "search": ["o.full_name", "v.registration_no", "v.vin"],
        "sort": {"start_date": "ow.start_date", "status": "ow.ownership_status", "name": "o.full_name"},
        "order": "ow.start_date DESC",
    },
    "services": {
        "select": "SELECT sr.service_id AS record_id, sr.vehicle_id, v.registration_no, v.brand, v.model, sr.service_date AS event_date, sr.service_type AS category, sr.mileage, sr.workshop_name, sr.cost, sr.notes",
        "from": "FROM service_records sr JOIN vehicles v USING(vehicle_id)",
        "search": ["v.registration_no", "v.brand", "sr.service_type", "sr.workshop_name"],
        "sort": {"date": "sr.service_date", "cost": "sr.cost", "brand": "v.brand"},
        "order": "sr.service_date DESC",
    },
    "repairs": {
        "select": "SELECT rr.repair_id AS record_id, rr.vehicle_id, v.registration_no, v.brand, v.model, rr.repair_date AS event_date, rr.repair_type AS category, rr.cost, rr.workshop_name, rr.description",
        "from": "FROM repair_records rr JOIN vehicles v USING(vehicle_id)",
        "search": ["v.registration_no", "v.brand", "rr.repair_type", "rr.workshop_name"],
        "sort": {"date": "rr.repair_date", "cost": "rr.cost", "brand": "v.brand"},
        "order": "rr.repair_date DESC",
    },
    "mileage": {
        "select": "SELECT mr.mileage_id AS record_id, mr.vehicle_id, v.registration_no, v.brand, mr.recorded_date AS event_date, mr.mileage, mr.source",
        "from": "FROM mileage_records mr JOIN vehicles v USING(vehicle_id)",
        "search": ["v.registration_no", "v.brand", "mr.source"],
        "sort": {"date": "mr.recorded_date", "mileage": "mr.mileage", "brand": "v.brand"},
        "order": "mr.recorded_date DESC",
    },
    "inspections": {
        "select": "SELECT i.inspection_id AS record_id, i.vehicle_id, v.registration_no, i.inspection_date AS event_date, i.result, i.remarks, u.full_name AS inspector",
        "from": "FROM inspections i JOIN vehicles v USING(vehicle_id) JOIN users u ON u.user_id=i.inspector_id",
        "search": ["v.registration_no", "i.result", "u.full_name"],
        "sort": {"date": "i.inspection_date", "result": "i.result", "vehicle": "v.registration_no"},
        "order": "i.inspection_date DESC",
    },
    "documents": {
        "select": "SELECT d.document_id AS record_id, d.vehicle_id, v.registration_no, d.document_type, d.document_number, d.issue_date, d.expiry_date, CASE WHEN d.status <> 'CANCELLED' AND d.expiry_date < CURRENT_DATE THEN 'EXPIRED' ELSE d.status END AS status, d.expiry_date-CURRENT_DATE AS days_until_expiry",
        "from": "FROM documents d JOIN vehicles v USING(vehicle_id)",
        "search": ["v.registration_no", "d.document_type", "d.document_number", "d.status"],
        "sort": {"expiry": "d.expiry_date", "type": "d.document_type", "status": "d.status"},
        "order": "d.expiry_date NULLS LAST",
    },
    "verification": {
        "select": "SELECT vr.verification_id AS record_id, vr.vehicle_id, v.registration_no, vr.verification_date AS event_date, vr.result, vr.remarks, u.full_name AS verified_by",
        "from": "FROM verification_records vr JOIN vehicles v USING(vehicle_id) JOIN users u ON u.user_id=vr.verified_by",
        "search": ["v.registration_no", "vr.result", "u.full_name"],
        "sort": {"date": "vr.verification_date", "result": "vr.result", "vehicle": "v.registration_no"},
        "order": "vr.verification_date DESC",
    },
    "audit": {
        "select": "SELECT al.audit_id, al.action, al.entity_name, al.entity_id, al.action_timestamp, al.details, u.full_name AS actor",
        "from": "FROM audit_logs al LEFT JOIN users u USING(user_id)",
        "search": ["al.action", "al.entity_name", "al.details", "u.full_name"],
        "sort": {"date": "al.action_timestamp", "action": "al.action", "entity": "al.entity_name"},
        "order": "al.action_timestamp DESC",
    },
}

WRITE_RESOURCES = {
    "owners": ("owners", "owner_id", {"full_name", "email", "phone"}),
    "services": ("service_records", "service_id", {"vehicle_id", "service_date", "service_type", "mileage", "workshop_name", "notes", "cost"}),
    "repairs": ("repair_records", "repair_id", {"vehicle_id", "repair_date", "repair_type", "description", "cost", "workshop_name"}),
    "mileage": ("mileage_records", "mileage_id", {"vehicle_id", "recorded_date", "mileage", "source"}),
    "inspections": ("inspections", "inspection_id", {"vehicle_id", "inspection_date", "result", "remarks"}),
    "documents": ("documents", "document_id", {"vehicle_id", "document_type", "document_number", "issue_date", "expiry_date", "status"}),
    "verification": ("verification_records", "verification_id", {"vehicle_id", "verification_date", "result", "remarks"}),
}

RECORD_TABLES = {
    "owners": ("owners", "owner_id"),
    "ownership": ("ownership_records", "ownership_id"),
    "services": ("service_records", "service_id"),
    "repairs": ("repair_records", "repair_id"),
    "mileage": ("mileage_records", "mileage_id"),
    "inspections": ("inspections", "inspection_id"),
    "documents": ("documents", "document_id"),
    "verification": ("verification_records", "verification_id"),
    "audit": ("audit_logs", "audit_id"),
}


@router.get("/dashboard", tags=["Dashboard"])
def dashboard(user=Depends(require_business_permissions("vehicles.read"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS total FROM vehicles")
            total_vehicles = cur.fetchone()["total"]
            if has_permission(user, "owners.read"):
                cur.execute("SELECT COUNT(DISTINCT owner_id) AS total FROM ownership_records WHERE ownership_status='ACTIVE'")
                active_owners = cur.fetchone()["total"]
            else:
                active_owners = None
            if has_permission(user, "history.read"):
                cur.execute("SELECT COUNT(*) AS total FROM vw_expiring_documents")
                expiring_documents = cur.fetchone()["total"]
                cur.execute(
                    """
                    WITH ordered AS (
                        SELECT mileage, LAG(mileage) OVER (PARTITION BY vehicle_id ORDER BY recorded_date, mileage_id) AS previous
                        FROM mileage_records
                    )
                    SELECT COUNT(*) AS total FROM ordered WHERE previous IS NOT NULL AND mileage < previous
                    """
                )
                mileage_anomalies = cur.fetchone()["total"]
            else:
                expiring_documents = None
                mileage_anomalies = None
            if has_permission(user, "financial.read"):
                cur.execute("SELECT COALESCE(total_cost, 0) AS total FROM vw_monthly_costs WHERE month=DATE_TRUNC('month', CURRENT_DATE)::DATE")
                current_cost = cur.fetchone()
                cur.execute("SELECT month, service_cost, repair_cost, total_cost FROM vw_monthly_costs ORDER BY month DESC LIMIT 6")
                monthly_costs = cur.fetchall()
            else:
                current_cost = None
                monthly_costs = []
            cur.execute("SELECT brand AS label, COUNT(*) AS value FROM vehicles GROUP BY brand ORDER BY value DESC, brand LIMIT 8")
            vehicles_by_brand = cur.fetchall()
            cur.execute("SELECT COALESCE(fuel_type, 'Not recorded') AS label, COUNT(*) AS value FROM vehicles GROUP BY fuel_type ORDER BY value DESC")
            fuel_split = cur.fetchall()
            if has_permission(user, "audit.read"):
                cur.execute(
                    """
                    SELECT audit_id, action, entity_name, entity_id, action_timestamp, details
                    FROM audit_logs
                    WHERE business_id = %s
                       OR (business_id IS NULL AND %s)
                    ORDER BY action_timestamp DESC
                    LIMIT 8
                    """,
                    (user["business_id"], user["role_name"] == "Super Admin"),
                )
                activity = cur.fetchall()
            else:
                activity = []
        return {
            "kpis": {
                "total_vehicles": total_vehicles,
                "active_owners": active_owners,
                "expiring_documents": expiring_documents,
                "maintenance_cost_month": current_cost["total"] if current_cost else None,
                "mileage_anomalies": mileage_anomalies,
            },
            "charts": {
                "monthly_costs": list(reversed(monthly_costs)),
                "vehicles_by_brand": vehicles_by_brand,
                "fuel_split": fuel_split,
            },
            "activity": activity,
        }
    finally:
        conn.close()


@router.get("/search", tags=["Search"])
def global_search(q: str = Query(min_length=1, max_length=100), user=Depends(get_business_context)):
    if not (has_permission(user, "vehicles.read") or has_permission(user, "owners.read")):
        raise HTTPException(
            status_code=403,
            detail="Your role does not have permission to search business records.",
        )
    term = f"%{q.strip()}%"
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            results = []
            if has_permission(user, "vehicles.read"):
                cur.execute(
                    """
                    SELECT 'vehicle' AS kind, vehicle_id AS id, registration_no AS title,
                           brand || ' ' || model AS subtitle
                    FROM vehicles
                    WHERE vin ILIKE %s OR registration_no ILIKE %s OR brand ILIKE %s OR model ILIKE %s
                    LIMIT 20
                    """,
                    (term, term, term, term),
                )
                results.extend(cur.fetchall())
            if has_permission(user, "owners.read"):
                cur.execute(
                    """
                    SELECT 'owner' AS kind, MIN(owner_id) AS id, full_name AS title,
                           COALESCE(email, phone, '') AS subtitle
                    FROM owners
                    WHERE full_name ILIKE %s OR email ILIKE %s
                    GROUP BY full_name, email, phone
                    LIMIT 20
                    """,
                    (term, term),
                )
                results.extend(cur.fetchall())
            return {"results": results[:20]}
    finally:
        conn.close()


@router.get("/records/{resource}", tags=["Ledger records"])
def list_records(
    resource: str,
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    sort: str | None = None,
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    user=Depends(get_business_context),
):
    spec = RESOURCE_QUERIES.get(resource)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown ledger section.")
    permission = RESOURCE_READ_PERMISSIONS.get(resource)
    if permission is None:
        raise HTTPException(status_code=404, detail="Unknown ledger section.")
    authorize_permissions(user, permission)

    where_conditions: list[str] = []
    params: list[object] = []
    if resource == "audit":
        where_conditions.append(
            "(al.business_id = %s OR (al.business_id IS NULL AND %s))"
        )
        params.extend(
            [user["business_id"], user["role_name"] == "Super Admin"]
        )
    if q.strip():
        where_conditions.append(
            "(" + " OR ".join(f"{column} ILIKE %s" for column in spec["search"]) + ")"
        )
        params.extend([f"%{q.strip()}%"] * len(spec["search"]))
    where_sql = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
    group_sql = spec.get("group", "")
    sort_sql = spec["sort"].get(sort, spec["order"]) if sort else spec["order"]
    if sort:
        sort_sql = f"{sort_sql} {direction.upper()}"
    offset = (page - 1) * page_size

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT COUNT(*) AS total FROM (SELECT 1 {spec['from']}{where_sql} {group_sql}) AS resource_rows",
                params,
            )
            total = cur.fetchone()["total"]
            cur.execute(
                f"{spec['select']} {spec['from']}{where_sql} {group_sql} ORDER BY {sort_sql} LIMIT %s OFFSET %s",
                [*params, page_size, offset],
            )
            items = cur.fetchall()
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        conn.close()


@router.get("/records/{resource}/{record_id}", tags=["Ledger records"])
def get_record(resource: str, record_id: int, user=Depends(get_business_context)):
    table_spec = RECORD_TABLES.get(resource)
    if table_spec is None:
        raise HTTPException(status_code=404, detail="Unknown ledger section.")
    permission = RESOURCE_READ_PERMISSIONS.get(resource)
    if permission is None:
        raise HTTPException(status_code=404, detail="Unknown ledger section.")
    authorize_permissions(user, permission)
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if resource == "audit":
                cur.execute(
                    """
                    SELECT *
                    FROM audit_logs
                    WHERE audit_id = %s
                      AND (
                          business_id = %s
                          OR (business_id IS NULL AND %s)
                      )
                    """,
                    (
                        record_id,
                        user["business_id"],
                        user["role_name"] == "Super Admin",
                    ),
                )
                record = cur.fetchone()
            else:
                record = get_ledger_record(conn, *table_spec, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Ledger record not found.")
        return {"record": record}
    finally:
        conn.close()


@router.post("/records/{resource}", status_code=201, tags=["Ledger records"])
def create_record(resource: str, payload: dict, user=Depends(get_current_user)):
    spec = WRITE_RESOURCES.get(resource)
    if spec is None:
        raise HTTPException(status_code=404, detail="This ledger section does not accept direct inserts.")
    table_name, id_column, allowed_fields = spec
    authorize_platform_admin(user)

    try:
        values = validate_record(resource, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if resource == "inspections":
        values["inspector_id"] = user["user_id"]
    elif resource == "verification":
        values["verified_by"] = user["user_id"]

    conn = get_connection()
    try:
        with conn:
            record_id = insert_ledger_record(conn, table_name, id_column, values, user["user_id"])
        return {"id": record_id, "resource": resource, "message": "Ledger record created."}
    except psycopg2.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="A record with one of these unique values already exists.") from exc
    except psycopg2.errors.ForeignKeyViolation as exc:
        raise HTTPException(status_code=422, detail="The selected vehicle or related record does not exist.") from exc
    except psycopg2.errors.CheckViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc.diag.message_primary)) from exc
    except psycopg2.errors.NotNullViolation as exc:
        raise HTTPException(status_code=422, detail=f"Required field missing: {exc.diag.column_name}.") from exc
    finally:
        conn.close()


@router.patch("/records/{resource}/{record_id}", tags=["Ledger records"])
def patch_record(resource: str, record_id: int, payload: dict, user=Depends(get_current_user)):
    spec = WRITE_RESOURCES.get(resource)
    table_spec = RECORD_TABLES.get(resource)
    if spec is None or table_spec is None:
        raise HTTPException(status_code=404, detail="This ledger section cannot be updated directly.")
    table_name, id_column = table_spec
    authorize_platform_admin(user)
    try:
        values = validate_record(resource, payload, partial=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    conn = get_connection()
    try:
        with conn:
            updated_id = update_ledger_record(conn, table_name, id_column, record_id, values, user["user_id"])
        if updated_id is None:
            raise HTTPException(status_code=404, detail="Ledger record not found.")
        return {"id": updated_id, "resource": resource, "message": "Ledger record updated."}
    except psycopg2.errors.ForeignKeyViolation as exc:
        raise HTTPException(status_code=422, detail="The selected vehicle or related record does not exist.") from exc
    except psycopg2.errors.CheckViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc.diag.message_primary)) from exc
    except psycopg2.errors.NotNullViolation as exc:
        raise HTTPException(status_code=422, detail=f"This field cannot be empty: {exc.diag.column_name}.") from exc
    except psycopg2.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="The update conflicts with an existing unique value.") from exc
    finally:
        conn.close()


@router.delete("/records/{resource}/{record_id}", status_code=204, tags=["Ledger records"])
def delete_record(resource: str, record_id: int, user=Depends(require_platform_admin())):
    spec = WRITE_RESOURCES.get(resource)
    table_spec = RECORD_TABLES.get(resource)
    if spec is None or table_spec is None:
        raise HTTPException(status_code=409, detail="This ledger section is immutable; use the ownership transfer workflow where applicable.")
    table_name, id_column = table_spec
    conn = get_connection()
    try:
        with conn:
            deleted = delete_ledger_record(conn, table_name, id_column, record_id, user["user_id"])
        if deleted is None:
            raise HTTPException(status_code=404, detail="Ledger record not found.")
    except psycopg2.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This record is referenced by related history and cannot be deleted.") from exc
    finally:
        conn.close()
    return None


@router.get("/reports/vehicles.csv", tags=["Reports"])
def export_vehicles_csv(
    brand: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user=Depends(require_business_permissions("vehicles.read")),
):
    filters = []
    params = []
    if brand:
        filters.append("s.brand ILIKE %s")
        params.append(brand)
    if date_from:
        filters.append("v.created_at::DATE >= %s")
        params.append(date_from)
    if date_to:
        filters.append("v.created_at::DATE <= %s")
        params.append(date_to)
    where_sql = " WHERE " + " AND ".join(filters) if filters else ""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT s.registration_no, s.vin, s.brand, s.model, s.model_year, s.current_owner, s.latest_mileage, s.last_service_date FROM vw_vehicle_summary s JOIN vehicles v USING (vehicle_id)" + where_sql + " ORDER BY s.registration_no",
                params,
            )
            rows = cur.fetchall()
            headers = [column.name for column in cur.description]
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([f"'{value}" if isinstance(value, str) and value[:1] in "=+-@" else value for value in row])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=autoledger-vehicles.csv"},
    )


@router.get("/reports/vehicles/{vehicle_id}.pdf", tags=["Reports"])
def export_vehicle_history_pdf(
    vehicle_id: int,
    user=Depends(require_business_permissions("history.read")),
):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM vw_vehicle_summary WHERE vehicle_id=%s", (vehicle_id,))
            vehicle = cur.fetchone()
            if vehicle is None:
                raise HTTPException(status_code=404, detail="Vehicle not found.")

            sections = [
                (
                    "Ownership history",
                    "SELECT o.full_name, ow.start_date, ow.end_date, ow.ownership_status FROM ownership_records ow JOIN owners o USING(owner_id) WHERE ow.vehicle_id=%s ORDER BY ow.start_date, ow.ownership_id",
                    ["Owner", "Start date", "End date", "Status"],
                ),
                (
                    "Service history",
                    "SELECT service_date, service_type, mileage, workshop_name, cost FROM service_records WHERE vehicle_id=%s ORDER BY service_date, service_id",
                    ["Date", "Service", "Mileage", "Workshop", "Cost (PKR)"],
                ),
                (
                    "Repair history",
                    "SELECT repair_date, repair_type, description, workshop_name, cost FROM repair_records WHERE vehicle_id=%s ORDER BY repair_date, repair_id",
                    ["Date", "Repair", "Description", "Workshop", "Cost (PKR)"],
                ),
                (
                    "Mileage history",
                    "SELECT recorded_date, mileage, source FROM mileage_records WHERE vehicle_id=%s ORDER BY recorded_date, mileage_id",
                    ["Date", "Mileage", "Source"],
                ),
                (
                    "Inspections",
                    "SELECT i.inspection_date, i.result, u.full_name AS inspector, i.remarks FROM inspections i JOIN users u ON u.user_id=i.inspector_id WHERE i.vehicle_id=%s ORDER BY i.inspection_date, i.inspection_id",
                    ["Date", "Result", "Inspector", "Remarks"],
                ),
                (
                    "Documents",
                    "SELECT document_type, document_number, issue_date, expiry_date, CASE WHEN status <> 'CANCELLED' AND expiry_date < CURRENT_DATE THEN 'EXPIRED' ELSE status END AS status FROM documents WHERE vehicle_id=%s ORDER BY expiry_date NULLS LAST, document_id",
                    ["Document", "Reference", "Issued", "Expiry", "Status"],
                ),
                (
                    "Verification history",
                    "SELECT vr.verification_date, vr.result, u.full_name AS verified_by, vr.remarks FROM verification_records vr JOIN users u ON u.user_id=vr.verified_by WHERE vr.vehicle_id=%s ORDER BY vr.verification_date, vr.verification_id",
                    ["Date", "Result", "Verified by", "Remarks"],
                ),
            ]
            section_rows = []
            for title, query, _ in sections:
                cur.execute(query, (vehicle_id,))
                section_rows.append((title, cur.fetchall()))
    finally:
        conn.close()

    output = BytesIO()
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#24483D")
    styles["Title"].fontSize = 18
    styles["Heading2"].textColor = colors.HexColor("#24483D")
    styles["BodyText"].fontSize = 8
    cell_style = styles["BodyText"]
    story = [
        Paragraph("AutoLedger Vehicle History", styles["Title"]),
        Paragraph(
            f"{escape(str(vehicle['registration_no']))} · {escape(str(vehicle['brand']))} {escape(str(vehicle['model']))} · {vehicle['model_year']}",
            styles["Heading2"],
        ),
        Paragraph(
            f"VIN: {escape(str(vehicle['vin']))} · Current owner: {escape(str(vehicle['current_owner'] or 'Unassigned'))} · Latest mileage: {escape(str(vehicle['latest_mileage'] or 'Not recorded'))}",
            cell_style,
        ),
        Spacer(1, 5 * mm),
    ]

    def format_cell(value):
        if value is None:
            return "—"
        if hasattr(value, "strftime"):
            return value.strftime("%d %b %Y")
        if hasattr(value, "quantize"):
            return f"PKR {value:,.0f}"
        return str(value)

    for (title, query, headers), (_, rows) in zip(sections, section_rows):
        story.append(Paragraph(title, styles["Heading2"]))
        if not rows:
            story.append(Paragraph("No records.", cell_style))
            story.append(Spacer(1, 3 * mm))
            continue
        table_data = [[Paragraph(escape(header), cell_style) for header in headers]]
        table_data.extend(
            [Paragraph(escape(format_cell(row[key])), cell_style) for key in row]
            for row in rows
        )
        table = Table(table_data, repeatRows=1, colWidths=[(A4[0] - 32 * mm) / len(headers)] * len(headers))
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#24483D")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D5DED8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F3")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([table, Spacer(1, 4 * mm)])

    SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"AutoLedger Vehicle {vehicle_id} History",
    ).build(story)
    return Response(
        content=output.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=autoledger-vehicle-{vehicle_id}-history.pdf"},
    )