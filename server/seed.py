"""Seed script for LifeVault.

Populates the SQLite database with realistic life-admin records:
- Warranties (laptop, phone, headphones, fridge)
- Subscriptions (Netflix, Spotify, gym, cloud storage, prime)
- Insurance (auto, health, home, pet)
- Bills (electric, internet, mobile phone, water, gas)
- Documents (passport, driver license, Global Entry)

All dates are generated dynamically relative to date.today() so that
deadlines are always upcoming and spending summaries work reliably.
"""

from datetime import date, timedelta
from pathlib import Path
import random
from typing import Optional

from storage import Storage, get_storage


def seed_database(storage_instance: Optional[Storage] = None, db_path: Optional[str] = None) -> None:
    """Populate the LifeVault database with realistic records using the selected backend."""
    random.seed(42)

    if storage_instance is not None:
        storage = storage_instance
    elif db_path is not None:
        storage = get_storage(backend="sqlite", db_path=db_path)
    else:
        storage = get_storage()

    # Clear existing data for selected backend
    if hasattr(storage, "clear_all"):
        storage.clear_all()
    elif hasattr(storage, "init_db"):
        storage.init_db(drop_existing=True)

    today = date.today()

    records = [
        # --- WARRANTIES ---
        # 1. Laptop warranty expiring in ~20 days
        {
            "type": "warranty",
            "name": "MacBook Pro 16-inch",
            "vendor": "Apple",
            "amount": 2499.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=710)).isoformat(),
            "expiry_date": (today + timedelta(days=20)).isoformat(),
            "renewal_cycle": None,
            "reminder_date": (today - timedelta(days=10)).isoformat(),
            "notes": "AppleCare+ expiring in 20 days",
        },
        # 2. Second laptop for ambiguity testing
        {
            "type": "warranty",
            "name": "Dell XPS 15 Laptop",
            "vendor": "Dell",
            "amount": 1799.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=180)).isoformat(),
            "expiry_date": (today + timedelta(days=550)).isoformat(),
            "renewal_cycle": None,
            "reminder_date": (today + timedelta(days=520)).isoformat(),
            "notes": "Dell Premium Support 2-year warranty",
        },
        # 3. Smartphone warranty
        {
            "type": "warranty",
            "name": "iPhone 15 Pro",
            "vendor": "Apple",
            "amount": 999.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=120)).isoformat(),
            "expiry_date": (today + timedelta(days=245)).isoformat(),
            "renewal_cycle": None,
            "reminder_date": (today + timedelta(days=215)).isoformat(),
            "notes": "Standard 1-year Apple limited warranty",
        },
        # 4. Expired headphones warranty
        {
            "type": "warranty",
            "name": "Sony WH-1000XM5 Headphones",
            "vendor": "Sony",
            "amount": 399.99,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=400)).isoformat(),
            "expiry_date": (today - timedelta(days=35)).isoformat(),
            "reminder_date": (today - timedelta(days=65)).isoformat(),
            "notes": "1-year warranty expired 35 days ago",
        },
        # 5. Earbuds warranty active
        {
            "type": "warranty",
            "name": "Bose QuietComfort Earbuds",
            "vendor": "Bose",
            "amount": 279.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=90)).isoformat(),
            "expiry_date": (today + timedelta(days=275)).isoformat(),
            "reminder_date": (today + timedelta(days=245)).isoformat(),
            "notes": "1-year manufacturer warranty",
        },
        # 6. Major appliance warranty
        {
            "type": "warranty",
            "name": "Samsung French Door Refrigerator",
            "vendor": "Samsung",
            "amount": 1499.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=300)).isoformat(),
            "expiry_date": (today + timedelta(days=430)).isoformat(),
            "renewal_cycle": None,
            "reminder_date": (today + timedelta(days=400)).isoformat(),
            "notes": "2-year compressor and parts warranty",
        },

        # --- SUBSCRIPTIONS ---
        # 7. Gym membership renewing in ~5 days
        {
            "type": "subscription",
            "name": "Equinox Gym Membership",
            "vendor": "Equinox",
            "amount": 220.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=25)).isoformat(),
            "expiry_date": (today + timedelta(days=5)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=5)).isoformat(),
            "notes": "Monthly recurring auto-debit renewing in 5 days",
        },
        # 8. Netflix streaming
        {
            "type": "subscription",
            "name": "Netflix Premium",
            "vendor": "Netflix",
            "amount": 22.99,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=14)).isoformat(),
            "expiry_date": (today + timedelta(days=16)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=14)).isoformat(),
            "notes": "4K Ultra HD 4-screen streaming plan",
        },
        # 9. Spotify music
        {
            "type": "subscription",
            "name": "Spotify Family",
            "vendor": "Spotify",
            "amount": 16.99,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=8)).isoformat(),
            "expiry_date": (today + timedelta(days=22)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=8)).isoformat(),
            "notes": "Family plan up to 6 accounts",
        },
        # 10. Cloud storage
        {
            "type": "subscription",
            "name": "Google One Cloud Storage",
            "vendor": "Google",
            "amount": 99.99,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=200)).isoformat(),
            "expiry_date": (today + timedelta(days=165)).isoformat(),
            "renewal_cycle": "yearly",
            "reminder_date": (today + timedelta(days=135)).isoformat(),
            "notes": "2TB annual storage and VPN plan",
        },
        # 11. Amazon Prime
        {
            "type": "subscription",
            "name": "Amazon Prime",
            "vendor": "Amazon",
            "amount": 139.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=280)).isoformat(),
            "expiry_date": (today + timedelta(days=85)).isoformat(),
            "renewal_cycle": "yearly",
            "reminder_date": (today + timedelta(days=55)).isoformat(),
            "notes": "Annual delivery and Prime Video membership",
        },
        # 12. Expired subscription
        {
            "type": "subscription",
            "name": "The Athletic Sports",
            "vendor": "The New York Times",
            "amount": 36.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=400)).isoformat(),
            "expiry_date": (today - timedelta(days=35)).isoformat(),
            "renewal_cycle": "yearly",
            "reminder_date": (today - timedelta(days=65)).isoformat(),
            "notes": "Canceled annual sports subscription",
        },

        # --- INSURANCE ---
        # 13. Auto insurance renewing in ~40 days
        {
            "type": "insurance",
            "name": "GEICO Auto Insurance",
            "vendor": "GEICO",
            "amount": 540.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=140)).isoformat(),
            "expiry_date": (today + timedelta(days=40)).isoformat(),
            "renewal_cycle": "6-month",
            "reminder_date": (today + timedelta(days=10)).isoformat(),
            "notes": "Comprehensive and collision coverage renewing in 40 days",
        },
        # 14. Health insurance
        {
            "type": "insurance",
            "name": "Blue Cross Blue Shield Health",
            "vendor": "Blue Cross",
            "amount": 340.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=10)).isoformat(),
            "expiry_date": (today + timedelta(days=20)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=10)).isoformat(),
            "notes": "Individual PPO gold health plan",
        },
        # 15. Homeowners insurance
        {
            "type": "insurance",
            "name": "Travelers Home Insurance",
            "vendor": "Travelers",
            "amount": 1150.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=250)).isoformat(),
            "expiry_date": (today + timedelta(days=115)).isoformat(),
            "renewal_cycle": "yearly",
            "reminder_date": (today + timedelta(days=85)).isoformat(),
            "notes": "Annual homeowner and hazard policy",
        },
        # 16. Expired pet insurance
        {
            "type": "insurance",
            "name": "Healthy Paws Pet Insurance",
            "vendor": "Healthy Paws",
            "amount": 48.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=45)).isoformat(),
            "expiry_date": (today - timedelta(days=15)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=45)).isoformat(),
            "notes": "Past dog health policy, expired 15 days ago",
        },

        # --- BILLS ---
        # 17. 6 months of Electric utility bills (latest is ~42% higher)
        {
            "type": "bill",
            "name": "City Electric Utility Bill",
            "vendor": "Con Edison",
            "amount": 116.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=154)).isoformat(),
            "expiry_date": (today - timedelta(days=136)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=146)).isoformat(),
            "notes": "Electric utility bill from 5 months ago",
        },
        {
            "type": "bill",
            "name": "City Electric Utility Bill",
            "vendor": "Con Edison",
            "amount": 119.50,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=124)).isoformat(),
            "expiry_date": (today - timedelta(days=106)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=116)).isoformat(),
            "notes": "Electric utility bill from 4 months ago",
        },
        {
            "type": "bill",
            "name": "City Electric Utility Bill",
            "vendor": "Con Edison",
            "amount": 118.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=94)).isoformat(),
            "expiry_date": (today - timedelta(days=76)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=86)).isoformat(),
            "notes": "Electric utility bill from 3 months ago",
        },
        {
            "type": "bill",
            "name": "City Electric Utility Bill",
            "vendor": "Con Edison",
            "amount": 117.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=64)).isoformat(),
            "expiry_date": (today - timedelta(days=46)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=56)).isoformat(),
            "notes": "Electric utility bill from 2 months ago",
        },
        {
            "type": "bill",
            "name": "City Electric Utility Bill",
            "vendor": "Con Edison",
            "amount": 120.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=34)).isoformat(),
            "expiry_date": (today - timedelta(days=16)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=26)).isoformat(),
            "notes": "Electric utility bill from last month",
        },
        {
            "type": "bill",
            "name": "City Electric Utility Bill",
            "vendor": "Con Edison",
            "amount": 168.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=4)).isoformat(),
            "expiry_date": (today + timedelta(days=14)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today + timedelta(days=4)).isoformat(),
            "notes": "Residential electric bill due in 14 days (spike detected)",
        },

        # 18. 6 months of Fiber internet bills with normal variation
        {
            "type": "bill",
            "name": "Verizon Fios Internet Bill",
            "vendor": "Verizon",
            "amount": 79.99,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=156)).isoformat(),
            "expiry_date": (today - timedelta(days=132)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=142)).isoformat(),
            "notes": "Fiber internet bill from 5 months ago",
        },
        {
            "type": "bill",
            "name": "Verizon Fios Internet Bill",
            "vendor": "Verizon",
            "amount": 81.50,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=126)).isoformat(),
            "expiry_date": (today - timedelta(days=102)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=112)).isoformat(),
            "notes": "Fiber internet bill from 4 months ago",
        },
        {
            "type": "bill",
            "name": "Verizon Fios Internet Bill",
            "vendor": "Verizon",
            "amount": 79.99,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=96)).isoformat(),
            "expiry_date": (today - timedelta(days=72)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=82)).isoformat(),
            "notes": "Fiber internet bill from 3 months ago",
        },
        {
            "type": "bill",
            "name": "Verizon Fios Internet Bill",
            "vendor": "Verizon",
            "amount": 80.25,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=66)).isoformat(),
            "expiry_date": (today - timedelta(days=42)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=52)).isoformat(),
            "notes": "Fiber internet bill from 2 months ago",
        },
        {
            "type": "bill",
            "name": "Verizon Fios Internet Bill",
            "vendor": "Verizon",
            "amount": 79.99,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=36)).isoformat(),
            "expiry_date": (today - timedelta(days=12)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=22)).isoformat(),
            "notes": "Fiber internet bill from last month",
        },
        {
            "type": "bill",
            "name": "Verizon Fios Internet Bill",
            "vendor": "Verizon",
            "amount": 79.99,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=6)).isoformat(),
            "expiry_date": (today + timedelta(days=18)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today + timedelta(days=8)).isoformat(),
            "notes": "1 Gbps fiber optic internet monthly bill",
        },
        # 19. Mobile wireless bill
        {
            "type": "bill",
            "name": "T-Mobile Wireless Bill",
            "vendor": "T-Mobile",
            "amount": 85.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=12)).isoformat(),
            "expiry_date": (today + timedelta(days=12)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today + timedelta(days=2)).isoformat(),
            "notes": "Magenta MAX cell phone plan",
        },
        # 20. Water bill from last month
        {
            "type": "bill",
            "name": "Municipal Water and Sewer Bill",
            "vendor": "City Water Board",
            "amount": 62.50,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=38)).isoformat(),
            "expiry_date": (today - timedelta(days=18)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=28)).isoformat(),
            "notes": "Water consumption bill from last month",
        },
        # 21. Natural gas heating bill
        {
            "type": "bill",
            "name": "National Grid Gas Bill",
            "vendor": "National Grid",
            "amount": 54.30,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=42)).isoformat(),
            "expiry_date": (today - timedelta(days=22)).isoformat(),
            "renewal_cycle": "monthly",
            "reminder_date": (today - timedelta(days=32)).isoformat(),
            "notes": "Heating and natural gas bill from last month",
        },
        # 22. Trash and recycling past bill
        {
            "type": "bill",
            "name": "Waste Management Recycling Bill",
            "vendor": "Waste Management",
            "amount": 95.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=75)).isoformat(),
            "expiry_date": (today - timedelta(days=55)).isoformat(),
            "renewal_cycle": "quarterly",
            "reminder_date": (today - timedelta(days=65)).isoformat(),
            "notes": "Quarterly waste disposal bill earlier this year",
        },

        # --- DOCUMENTS ---
        # 23. Passport expiring in ~150 days
        {
            "type": "document",
            "name": "US Passport",
            "vendor": "US Department of State",
            "amount": 130.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=3500)).isoformat(),
            "expiry_date": (today + timedelta(days=150)).isoformat(),
            "renewal_cycle": None,
            "reminder_date": (today + timedelta(days=120)).isoformat(),
            "notes": "10-year regular adult passport expiring in ~150 days",
        },
        # 24. Driver's License
        {
            "type": "document",
            "name": "State Driver's License",
            "vendor": "Department of Motor Vehicles",
            "amount": 38.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=700)).isoformat(),
            "expiry_date": (today + timedelta(days=395)).isoformat(),
            "renewal_cycle": None,
            "reminder_date": (today + timedelta(days=365)).isoformat(),
            "notes": "Class D driver license with REAL ID star",
        },
        # 25. Global Entry Card
        {
            "type": "document",
            "name": "Global Entry Trusted Traveler Card",
            "vendor": "US Customs and Border Protection",
            "amount": 100.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=1200)).isoformat(),
            "expiry_date": (today + timedelta(days=625)).isoformat(),
            "renewal_cycle": None,
            "reminder_date": (today + timedelta(days=595)).isoformat(),
            "notes": "Trusted traveler membership including TSA PreCheck",
        },
        # 26. Expired international permit
        {
            "type": "document",
            "name": "International Driving Permit",
            "vendor": "AAA",
            "amount": 20.00,
            "currency": "USD",
            "purchase_date": (today - timedelta(days=400)).isoformat(),
            "expiry_date": (today - timedelta(days=35)).isoformat(),
            "renewal_cycle": None,
            "reminder_date": (today - timedelta(days=65)).isoformat(),
            "notes": "1-year international translation booklet, expired 35 days ago",
        },
    ]

    for item in records:
        storage.add_record(item)

    if hasattr(storage, "db_path"):
        print(f"Successfully seeded LifeVault SQLite database at: {storage.db_path}")
    elif hasattr(storage, "table_name"):
        print(f"Successfully seeded LifeVault DynamoDB table '{storage.table_name}' in region '{storage.region_name}'.")
    else:
        print(f"Successfully seeded LifeVault database using {storage.__class__.__name__}.")
    print(f"Total records added: {len(records)}")


if __name__ == "__main__":
    seed_database()
