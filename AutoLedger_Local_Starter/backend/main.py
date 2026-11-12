from pathlib import Path
import logging
from datetime import date

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.auth import router as auth_router
from backend.database import get_connection
from backend.records import router as records_router
from backend.security import require_roles

PROJECT_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)

class VehicleCreate(BaseModel):
    vin: str = Field(min_length=1, max_length=17)
    registration_no: str = Field(min_length=1, max_length=30)
    brand: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=50)
    model_year: int = Field(ge=1980, le=2035)
    color: str | None = Field(default=None, max_length=30)
    fuel_type: str | None = Field(default=None, max_length=20)
    transmission: str | None = Field(default=None, max_length=20)
    engine_no: str | None = Field(default=None, max_length=50)

class OwnershipTransfer(BaseModel):
    new_owner_id: int = Field(ge=1)
    transfer_date: date

app = FastAPI(title="AutoLedger API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(records_router)

@app.get("/api/health")
def health():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        logger.exception("Database health check failed")
        raise HTTPException(
            status_code=503,
            detail="Database health check failed. Check the server logs for the underlying error.",
        ) from exc
    finally:
        conn.close()

@app.get("/api/vehicles")
def search_vehicles(
    search: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
    brand: str | None = None,
    fuel_type: str | None = None,
    model_year: int | None = Query(default=None, ge=1980, le=2035),
    status: str | None = Query(default=None, pattern="^(ACTIVE|UNASSIGNED)$"),
    sort: str = Query(default="vehicle_id", pattern="^(vehicle_id|registration_no|brand|model_year)$"),
    direction: str = Query(default="asc", pattern="^(asc|desc)$"),
    user=Depends(require_roles("Admin", "Inspector", "Dealer", "Owner/Viewer")),
):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filters = []
            params = []
            if search.strip():
                term = f"%{search.strip()}%"
                filters.append("(registration_no ILIKE %s OR vin ILIKE %s OR brand ILIKE %s OR model ILIKE %s)")
                params.extend([term, term, term, term])
            if brand:
                filters.append("brand = %s")
                params.append(brand)
            if fuel_type:
                filters.append("fuel_type = %s")
                params.append(fuel_type)
            if model_year is not None:
                filters.append("model_year = %s")
                params.append(model_year)
            if status == "ACTIVE":
                filters.append("EXISTS (SELECT 1 FROM ownership_records ow WHERE ow.vehicle_id=vehicles.vehicle_id AND ow.ownership_status='ACTIVE')")
            elif status == "UNASSIGNED":
                filters.append("NOT EXISTS (SELECT 1 FROM ownership_records ow WHERE ow.vehicle_id=vehicles.vehicle_id AND ow.ownership_status='ACTIVE')")
            where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
            cur.execute(f"SELECT COUNT(*) AS total FROM vehicles {where_sql}", params)
            total = cur.fetchone()["total"]
            cur.execute(
                f"""
                SELECT vehicle_id, vin, registration_no, brand, model,
                       model_year, color, fuel_type, transmission, engine_no
                FROM vehicles {where_sql}
                ORDER BY {sort} {direction.upper()}
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            return {"count": total, "vehicles": cur.fetchall(), "page": page, "page_size": page_size}
    finally:
        conn.close()

@app.post("/api/vehicles", status_code=201)
def create_vehicle(vehicle: VehicleCreate, user=Depends(require_roles("Admin", "Dealer"))):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user["user_id"]),))
                cur.execute(
                    """
                    INSERT INTO vehicles
                        (vin, registration_no, brand, model, model_year,
                         color, fuel_type, transmission, engine_no)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING vehicle_id, vin, registration_no, brand, model,
                              model_year, color, fuel_type, transmission, engine_no
                    """,
                    (
                        vehicle.vin,
                        vehicle.registration_no,
                        vehicle.brand,
                        vehicle.model,
                        vehicle.model_year,
                        vehicle.color,
                        vehicle.fuel_type,
                        vehicle.transmission,
                        vehicle.engine_no,
                    ),
                )
                created_vehicle = cur.fetchone()
        return {"vehicle": created_vehicle}
    except psycopg2.IntegrityError as exc:
        if not isinstance(exc, psycopg2.IntegrityError):
            raise
        raise HTTPException(
            status_code=409,
            detail="Vehicle could not be saved because VIN, registration number, or engine number is already in use, or a database constraint was violated.",
        ) from exc
    finally:
        conn.close()

@app.get("/api/vehicles/{vehicle_id}")
def get_vehicle(vehicle_id: int, user=Depends(require_roles("Admin", "Inspector", "Dealer", "Owner/Viewer"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT vehicle_id, vin, registration_no, brand, model, model_year,
                       color, fuel_type, transmission, engine_no
                FROM vehicles WHERE vehicle_id=%s
                """,
                (vehicle_id,),
            )
            vehicle = cur.fetchone()
        if vehicle is None:
            raise HTTPException(status_code=404, detail="Vehicle not found.")
        return {"vehicle": vehicle}
    finally:
        conn.close()

@app.put("/api/vehicles/{vehicle_id}")
def update_vehicle(vehicle_id: int, vehicle: VehicleCreate, user=Depends(require_roles("Admin", "Dealer"))):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user["user_id"]),))
                cur.execute(
                    """
                    UPDATE vehicles
                    SET vin=%s, registration_no=%s, brand=%s, model=%s,
                        model_year=%s, color=%s, fuel_type=%s, transmission=%s,
                        engine_no=%s
                    WHERE vehicle_id=%s
                    RETURNING vehicle_id, vin, registration_no, brand, model,
                              model_year, color, fuel_type, transmission, engine_no
                    """,
                    (
                        vehicle.vin, vehicle.registration_no, vehicle.brand, vehicle.model,
                        vehicle.model_year, vehicle.color, vehicle.fuel_type,
                        vehicle.transmission, vehicle.engine_no, vehicle_id,
                    ),
                )
                updated = cur.fetchone()
                if updated is None:
                    raise HTTPException(status_code=404, detail="Vehicle not found.")
        return {"vehicle": updated}
    except psycopg2.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Vehicle update conflicts with a unique value or database constraint.") from exc
    finally:
        conn.close()

@app.delete("/api/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: int, user=Depends(require_roles("Admin"))):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user["user_id"]),))
                cur.execute("DELETE FROM vehicles WHERE vehicle_id=%s RETURNING vehicle_id", (vehicle_id,))
                deleted = cur.fetchone()
                if deleted is None:
                    raise HTTPException(status_code=404, detail="Vehicle not found.")
    except psycopg2.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This vehicle has linked ledger records and cannot be deleted.") from exc
    finally:
        conn.close()
    return None

@app.post("/api/vehicles/{vehicle_id}/transfer", status_code=201)
def transfer_vehicle_ownership(
    vehicle_id: int,
    transfer: OwnershipTransfer,
    user=Depends(require_roles("Admin", "Dealer")),
):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user["user_id"]),))
                cur.execute(
                    "SELECT transfer_ownership(%s, %s, %s)",
                    (vehicle_id, transfer.new_owner_id, transfer.transfer_date),
                )
                ownership_id = cur.fetchone()[0]
        return {"ownership_id": ownership_id, "message": "Ownership transferred."}
    except psycopg2.errors.ForeignKeyViolation as exc:
        raise HTTPException(status_code=404, detail="The vehicle or new owner does not exist.") from exc
    except psycopg2.errors.CheckViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc.diag.message_primary)) from exc
    except psycopg2.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Ownership could not be transferred because a ledger constraint was violated.") from exc
    finally:
        conn.close()

@app.get("/api/vehicles/{vehicle_id}/history")
def vehicle_history(vehicle_id: int, user=Depends(require_roles("Admin", "Inspector", "Dealer", "Owner/Viewer"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT vehicle_id, vin, registration_no, brand, model, model_year,
                       color, fuel_type, transmission
                FROM vehicles WHERE vehicle_id = %s
                """,
                (vehicle_id,),
            )
            vehicle = cur.fetchone()
            if not vehicle:
                raise HTTPException(status_code=404, detail="Vehicle not found")

            cur.execute(
                """
                SELECT ow.ownership_id, o.owner_id, o.full_name, ow.start_date, ow.end_date, ow.ownership_status
                FROM ownership_records ow
                JOIN owners o ON o.owner_id = ow.owner_id
                WHERE ow.vehicle_id = %s
                ORDER BY ow.start_date DESC
                """,
                (vehicle_id,),
            )
            ownership = cur.fetchall()

            cur.execute(
                """
                SELECT service_id, vehicle_id, service_date, service_type, mileage, workshop_name, notes, cost
                FROM service_records
                WHERE vehicle_id = %s
                ORDER BY service_date DESC
                """,
                (vehicle_id,),
            )
            services = cur.fetchall()

            cur.execute(
                """
                SELECT repair_id, vehicle_id, repair_date, repair_type, description, cost, workshop_name
                FROM repair_records
                WHERE vehicle_id = %s
                ORDER BY repair_date DESC
                """,
                (vehicle_id,),
            )
            repairs = cur.fetchall()

            cur.execute(
                """
                SELECT verification_id, vehicle_id, verified_by, verification_date, result, remarks
                FROM verification_records
                WHERE vehicle_id = %s
                ORDER BY verification_date DESC
                """,
                (vehicle_id,),
            )
            verifications = cur.fetchall()

            cur.execute(
                """
                SELECT mileage_id, vehicle_id, recorded_date, mileage, source
                FROM mileage_records WHERE vehicle_id=%s
                ORDER BY recorded_date, mileage_id
                """,
                (vehicle_id,),
            )
            mileage = cur.fetchall()

            cur.execute(
                """
                SELECT i.inspection_id, i.vehicle_id, i.inspector_id, inspection_date, result, remarks, u.full_name AS inspector
                FROM inspections i JOIN users u ON u.user_id=i.inspector_id
                WHERE vehicle_id=%s ORDER BY inspection_date DESC
                """,
                (vehicle_id,),
            )
            inspections = cur.fetchall()

            cur.execute(
                """
                SELECT document_id, vehicle_id, document_type, document_number, issue_date, expiry_date,
                       CASE WHEN status <> 'CANCELLED' AND expiry_date < CURRENT_DATE
                            THEN 'EXPIRED' ELSE status END AS status
                FROM documents WHERE vehicle_id=%s ORDER BY expiry_date DESC NULLS LAST
                """,
                (vehicle_id,),
            )
            documents = cur.fetchall()

        return {
            "vehicle": vehicle,
            "ownership": ownership,
            "services": services,
            "repairs": repairs,
            "verifications": verifications,
            "mileage": mileage,
            "inspections": inspections,
            "documents": documents,
        }
    finally:
        conn.close()

FRONTEND_DIR = PROJECT_DIR / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")
