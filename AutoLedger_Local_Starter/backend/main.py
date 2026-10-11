import logging
import os
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = PROJECT_DIR.parent
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(WORKSPACE_DIR / ".env")
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

app = FastAPI(title="AutoLedger API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Local development only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_connection():
    try:
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "autoledger_db"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            connect_timeout=5,
        )
    except Exception as exc:
        logger.exception("Database connection failed")
        raise HTTPException(
            status_code=503,
            detail="Database connection failed. Check the server logs for the underlying error."
        ) from exc

@app.get("/api/health")
def health():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return {"status": "ok", "database": "connected"}
    finally:
        conn.close()

@app.get("/api/vehicles")
def search_vehicles(search: str = Query(default="", max_length=100)):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if search.strip():
                term = f"%{search.strip()}%"
                cur.execute(
                    """
                    SELECT vehicle_id, vin, registration_no, brand, model,
                           model_year, color, fuel_type, transmission
                    FROM vehicles
                    WHERE registration_no ILIKE %s
                       OR vin ILIKE %s
                       OR brand ILIKE %s
                       OR model ILIKE %s
                    ORDER BY vehicle_id
                    LIMIT 100
                    """,
                    (term, term, term, term),
                )
            else:
                cur.execute(
                    """
                    SELECT vehicle_id, vin, registration_no, brand, model,
                           model_year, color, fuel_type, transmission
                    FROM vehicles
                    ORDER BY vehicle_id
                    LIMIT 100
                    """
                )
            return {"count": cur.rowcount, "vehicles": cur.fetchall()}
    finally:
        conn.close()

@app.post("/api/vehicles", status_code=201)
def create_vehicle(vehicle: VehicleCreate):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO vehicles
                        (vin, registration_no, brand, model, model_year,
                         color, fuel_type, transmission)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING vehicle_id, vin, registration_no, brand, model,
                              model_year, color, fuel_type, transmission
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
                    ),
                )
                created_vehicle = cur.fetchone()
        return {"vehicle": created_vehicle}
    except psycopg2.IntegrityError as exc:
        logger.exception("Vehicle creation failed because of a database constraint")
        raise HTTPException(
            status_code=409,
            detail="The VIN or registration number is already in use.",
        ) from exc
    finally:
        conn.close()

@app.get("/api/vehicles/{vehicle_id}/history")
def vehicle_history(vehicle_id: int):
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
                SELECT o.full_name, ow.start_date, ow.end_date, ow.ownership_status
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
                SELECT service_date, service_type, mileage, workshop_name, notes
                FROM service_records
                WHERE vehicle_id = %s
                ORDER BY service_date DESC
                """,
                (vehicle_id,),
            )
            services = cur.fetchall()

            cur.execute(
                """
                SELECT repair_date, repair_type, description, cost, workshop_name
                FROM repair_records
                WHERE vehicle_id = %s
                ORDER BY repair_date DESC
                """,
                (vehicle_id,),
            )
            repairs = cur.fetchall()

            cur.execute(
                """
                SELECT verification_date, result, remarks
                FROM verification_records
                WHERE vehicle_id = %s
                ORDER BY verification_date DESC
                """,
                (vehicle_id,),
            )
            verifications = cur.fetchall()

        return {
            "vehicle": vehicle,
            "ownership": ownership,
            "services": services,
            "repairs": repairs,
            "verifications": verifications,
        }
    finally:
        conn.close()

FRONTEND_DIR = PROJECT_DIR / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")
