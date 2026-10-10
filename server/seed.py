"""Seed script for StockPilot AI.

Populates the SQLite database with realistic repair-workshop data:
- 30 parts (including brake pads, oil filters, spark plugs, steel & zinc 10mm bolts)
- 10 jobs (including Job 51 and a mix of open/done)
- 90 days of realistic usage history
- Brake pads seeded with stock level just above reorder level for demo flow
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import random
import sqlite3

from storage import SqliteStorage


def seed_database(db_path: str = None) -> None:
    """Recreates and populates the database with realistic seed data."""
    # Fixed random seed for deterministic generation
    random.seed(42)

    storage = SqliteStorage(db_path=db_path)
    storage.init_db(drop_existing=True)

    # 1. 30 Parts
    parts_data = [
        # Brake pads: stock level just above reorder level for demo
        ("BP-CER-001", "Front Ceramic Brake Pads", "Brakes", 11, 10, 42.50, "Akebono"),
        ("BP-MET-002", "Rear Semi-Metallic Brake Pads", "Brakes", 9, 8, 34.00, "Brembo"),
        # Ambiguous 10mm bolts in steel AND zinc
        ("BLT-10MM-STL", "10mm Bolt (Steel)", "Fasteners", 120, 50, 0.45, "Fastenal"),
        ("BLT-10MM-ZNC", "10mm Bolt (Zinc)", "Fasteners", 95, 50, 0.55, "Fastenal"),
        # Filters and Oils (High usage)
        ("FLT-OIL-SPN", "Oil Filter (Spin-On)", "Filters", 24, 12, 6.50, "Wix Filters"),
        ("FLT-OIL-CRT", "Oil Filter (Cartridge)", "Filters", 18, 10, 8.20, "Wix Filters"),
        ("OIL-5W30-SYN", "Full Synthetic 5W-30 Motor Oil (1 Qt)", "Fluids", 65, 30, 7.99, "Valvoline"),
        ("OIL-0W20-SYN", "Full Synthetic 0W-20 Motor Oil (1 Qt)", "Fluids", 48, 25, 8.50, "Mobil 1"),
        ("FLT-AIR-ENG", "Engine Air Filter", "Filters", 15, 8, 14.50, "Fram"),
        ("FLT-AIR-CAB", "Cabin Air Filter", "Filters", 14, 8, 12.00, "Fram"),
        # Ignition
        ("SPK-IRD-001", "Spark Plug (Iridium)", "Ignition", 36, 20, 9.00, "NGK"),
        ("SPK-PLT-002", "Spark Plug (Platinum)", "Ignition", 22, 16, 6.50, "Bosch"),
        ("IGN-COIL-01", "Ignition Coil Pack", "Ignition", 12, 6, 42.00, "Delphi"),
        # Wipers
        ("WPR-BLD-20", "Wiper Blade 20-Inch", "Wipers", 14, 6, 11.00, "Rain-X"),
        ("WPR-BLD-22", "Wiper Blade 22-Inch", "Wipers", 12, 6, 11.50, "Rain-X"),
        ("WPR-BLD-24", "Wiper Blade 24-Inch", "Wipers", 10, 6, 12.00, "Rain-X"),
        # Electrical & Batteries
        ("BAT-12V-AGM", "12V AGM Car Battery", "Electrical", 7, 4, 145.00, "Interstate Batteries"),
        ("BAT-12V-STD", "12V Standard Lead-Acid Battery", "Electrical", 6, 4, 105.00, "Interstate Batteries"),
        ("ALT-130A-REM", "Alternator 130A (Reman)", "Electrical", 3, 2, 185.00, "Denso"),
        ("STR-MTR-REM", "Starter Motor (Reman)", "Electrical", 4, 2, 165.00, "Denso"),
        # Rotors & Suspension
        ("RTR-FRT-VNT", "Front Vented Brake Rotor", "Brakes", 8, 6, 48.00, "Brembo"),
        ("RTR-RR-SLD", "Rear Solid Brake Rotor", "Brakes", 8, 6, 38.00, "Brembo"),
        ("WHL-BRG-HUB", "Wheel Bearing Hub Assembly", "Suspension", 5, 3, 89.00, "Timken"),
        # Fluids
        ("FLD-BRK-DOT4", "DOT 4 Brake Fluid (32 oz)", "Fluids", 16, 8, 9.25, "Prestone"),
        ("FLD-CLN-5050", "Universal 50/50 Antifreeze/Coolant (1 Gal)", "Fluids", 20, 10, 15.00, "Prestone"),
        ("FLD-TRN-ATF", "Automatic Transmission Fluid (1 Qt)", "Fluids", 28, 12, 11.00, "Castrol"),
        # Engine accessories & sensors
        ("BLT-SERP-6PK", "Serpentine Belt 6PK1200", "Belts", 8, 4, 21.00, "Gates"),
        ("RAD-HSE-UPR", "Radiator Hose (Upper)", "Cooling", 7, 4, 18.50, "Continental"),
        ("SNS-O2-UP", "Oxygen Sensor (Upstream)", "Sensors", 5, 3, 62.00, "Bosch"),
        ("FLT-FUEL-INL", "In-Line Fuel Filter", "Filters", 9, 5, 16.50, "Wix Filters"),
    ]

    part_id_map = {}
    with storage._get_connection() as conn:
        cursor = conn.cursor()
        for sku, name, category, qty, reorder_level, unit_cost, supplier in parts_data:
            cursor.execute(
                """
                INSERT INTO parts (sku, name, category, qty, reorder_level, unit_cost, supplier)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sku, name, category, qty, reorder_level, unit_cost, supplier),
            )
            part_id_map[sku] = cursor.lastrowid
        conn.commit()

    # 2. 10 Jobs (including Job 51 and a mix of open/done)
    jobs_data = [
        (45, "2015 Honda Civic", "Alice Walker", "Transmission flush and routine safety inspection", "done"),
        (46, "2018 Toyota RAV4", "Bob Smith", "Front brake rotor and pad replacement", "done"),
        (47, "2020 Subaru Outback", "Claire Redfield", "Oil change, air filters, and tire rotation", "done"),
        (48, "2017 Chevrolet Silverado", "David Miller", "Starter motor replacement and battery load test", "done"),
        (49, "2016 BMW 328i", "Elena Rostova", "Ignition coil pack and spark plug replacement", "done"),
        (50, "2014 Jeep Grand Cherokee", "Frank Castle", "Upper radiator hose leak repair and coolant flush", "done"),
        (51, "2019 Ford F-150", "Mike Johnson", "Brake pad replacement and oil change", "open"),
        (52, "2021 Toyota Camry", "Grace Hopper", "Cabin and engine air filter replacement", "open"),
        (53, "2013 Hyundai Elantra", "Harry Potter", "Alternator diagnostic and battery install", "open"),
        (54, "2018 Mazda CX-5", "Irene Adler", "Serpentine belt check and 60,000-mile service", "open"),
    ]

    with storage._get_connection() as conn:
        cursor = conn.cursor()
        for job_id, vehicle, customer, description, status in jobs_data:
            cursor.execute(
                """
                INSERT INTO jobs (id, vehicle, customer, description, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, vehicle, customer, description, status),
            )
        conn.commit()

    # 3. 90 Days of Realistic Usage History
    # Brake pads and oil filters used frequently; specialty parts rarely.
    now = datetime.now(timezone.utc)
    done_job_ids = [45, 46, 47, 48, 49, 50]

    # Part usage profiles: (sku, total_events_over_90d, min_qty, max_qty)
    usage_profiles = [
        # Very high frequency
        ("BP-CER-001", 38, 2, 4),    # Brake pads: used frequently
        ("BP-MET-002", 28, 2, 4),
        ("FLT-OIL-SPN", 42, 1, 1),   # Oil filters: used very frequently
        ("FLT-OIL-CRT", 32, 1, 1),
        ("OIL-5W30-SYN", 45, 4, 6),
        ("OIL-0W20-SYN", 35, 4, 6),
        # Medium frequency
        ("SPK-IRD-001", 20, 4, 6),
        ("SPK-PLT-002", 14, 4, 4),
        ("FLT-AIR-ENG", 22, 1, 1),
        ("FLT-AIR-CAB", 18, 1, 1),
        ("WPR-BLD-20", 15, 1, 2),
        ("WPR-BLD-22", 16, 1, 2),
        ("WPR-BLD-24", 12, 1, 2),
        ("BLT-10MM-STL", 25, 2, 8),
        ("BLT-10MM-ZNC", 20, 2, 6),
        ("FLD-BRK-DOT4", 16, 1, 2),
        ("FLD-CLN-5050", 18, 1, 2),
        # Rare parts
        ("BAT-12V-AGM", 6, 1, 1),
        ("BAT-12V-STD", 5, 1, 1),
        ("ALT-130A-REM", 3, 1, 1),
        ("STR-MTR-REM", 4, 1, 1),
        ("IGN-COIL-01", 7, 1, 4),
        ("RTR-FRT-VNT", 8, 2, 2),
        ("RTR-RR-SLD", 6, 2, 2),
        ("WHL-BRG-HUB", 3, 1, 2),
        ("BLT-SERP-6PK", 5, 1, 1),
        ("RAD-HSE-UPR", 4, 1, 1),
        ("SNS-O2-UP", 3, 1, 1),
        ("FLT-FUEL-INL", 4, 1, 1),
        ("FLD-TRN-ATF", 8, 3, 5),
    ]

    usage_records = []
    for sku, num_events, min_qty, max_qty in usage_profiles:
        part_id = part_id_map[sku]
        # Spread events across 90 days with deterministic spacing
        days_ago_pool = sorted(random.sample(range(1, 91), min(num_events, 90)))
        for days_ago in days_ago_pool:
            qty = random.randint(min_qty, max_qty)
            # Assign to a completed job or workshop maintenance
            job_id = random.choice(done_job_ids) if random.random() < 0.75 else None
            # Event timestamp
            event_time = now - timedelta(
                days=days_ago,
                hours=random.randint(8, 17),
                minutes=random.randint(0, 59),
            )
            usage_records.append((part_id, job_id, qty, event_time.isoformat()))

    # Sort chronologically
    usage_records.sort(key=lambda r: r[3])

    with storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO usage_log (part_id, job_id, qty, used_at)
            VALUES (?, ?, ?, ?)
            """,
            usage_records,
        )
        conn.commit()

    print(f"Seed complete: {len(parts_data)} parts, {len(jobs_data)} jobs, {len(usage_records)} usage logs created.")


if __name__ == "__main__":
    seed_database()
