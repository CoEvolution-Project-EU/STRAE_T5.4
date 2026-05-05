from datetime import datetime, timezone


def utc_now_datetime() -> datetime:
    return datetime.now(timezone.utc)
    # return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def uuid_from_serial_number(serial_number: str) -> str:
    if serial_number.startswith("urn:uuid:"):
        return serial_number.split("urn:uuid:")[1]
    raise ValueError(f"Invalid serial number format: {serial_number}")


report_to_comment = {
    "aimodelinfo": "Model Information",
    "assessments": "Model Assessment Reports",
    "datasets": "Dataset Information",
    "defences": "Defence Report",
    "euaiact": "Model Development Guidelines",
    "gadgets": "Gadget List",
    "riskreport": "Risk Assessment",
}
