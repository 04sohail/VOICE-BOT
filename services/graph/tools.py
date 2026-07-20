import json
import os

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "database.json"
)


def load_db():
    if not os.path.exists(DB_PATH):
        return {"calendar": {}, "appointments": [], "accepted_insurance": []}
    with open(DB_PATH, "r") as f:
        return json.load(f)


def save_db(data):
    with open(DB_PATH, "w") as f:
        json.dump(data, f, indent=2)


def check_availability(day: str) -> str:
    """Returns the available time slots for a specific day (e.g., 'Monday', 'Tuesday')."""
    db = load_db()
    slots = db.get("calendar", {}).get(day.capitalize(), [])
    if not slots:
        return f"No appointments available on {day}."
    return f"Available slots on {day}: {', '.join(slots)}"


def book_appointment(
    patient_name: str, patient_location: str, day: str, time: str
) -> str:
    """Books an appointment for a patient on a specific day and time."""
    db = load_db()
    day_cap = day.capitalize()

    slots = db.get("calendar", {}).get(day_cap, [])
    if time not in slots:
        return f"Sorry, {time} on {day} is not available."

    # Remove from available calendar
    slots.remove(time)
    db["calendar"][day_cap] = slots

    # Save to appointments
    db["appointments"].append(
        {
            "name": patient_name,
            "location": patient_location,
            "day": day_cap,
            "time": time,
        }
    )

    save_db(db)
    return f"Appointment successfully booked for {patient_name} from {patient_location} on {day_cap} at {time}."


def check_insurance(provider: str) -> str:
    """Checks if a specific insurance provider is accepted."""
    db = load_db()
    accepted = db.get("accepted_insurance", [])
    if any(provider.lower() in p.lower() for p in accepted):
        return f"Yes, we accept {provider}."
    return f"No, we do not accept {provider}."
