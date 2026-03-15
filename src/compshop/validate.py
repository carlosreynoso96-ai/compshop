"""
Stage 4: Validate extracted offers against REFERENCE allowed values.
Deduplicate on composite key. Flag errors.
"""

from collections import Counter


class ValidationResult:
    def __init__(self):
        self.valid_offers = []
        self.errors = []
        self.dupes_removed = 0
        self.dropdown_errors = []


def deduplicate(offers):
    """
    Remove duplicate offers based on composite key:
    (Name, StartDate, EndDate, OfferAmt, Segment)
    Keeps the first occurrence (from the most canonical source).
    """
    seen = set()
    unique = []
    dupes = 0

    for offer in offers:
        key = (
            offer.get("Name", ""),
            offer.get("StartDate", ""),
            offer.get("EndDate", ""),
            offer.get("OfferAmt", 0),
            offer.get("Segment", ""),
        )
        if key not in seen:
            seen.add(key)
            unique.append(offer)
        else:
            dupes += 1

    return unique, dupes


def validate_dropdowns(offers, ref_values):
    """
    Check that every offer's dropdown fields match REFERENCE exactly.
    Returns list of error strings.
    """
    errors = []
    props = set(ref_values["properties"])
    comps = set(ref_values["competitors"])
    types = set(ref_values["types"])
    cats = set(ref_values["categories"])

    for i, offer in enumerate(offers):
        row = i + 2  # Excel row (1-indexed + header)
        p = offer.get("Property", "")
        if p not in props:
            errors.append(f"Row {row}: Property '{p}' not in REFERENCE")
        c = offer.get("Competitor", "")
        if c not in comps:
            errors.append(f"Row {row}: Competitor '{c}' not in REFERENCE")
        t = offer.get("Type", "")
        if t not in types:
            errors.append(f"Row {row}: Type '{t}' not in REFERENCE")
        cat = offer.get("Category", "")
        if cat not in cats:
            errors.append(f"Row {row}: Category '{cat}' not in REFERENCE")

    return errors


def validate_required_fields(offers):
    """Check that required fields are populated for every offer."""
    required = [
        "Property", "Competitor", "StartDate", "EndDate", "Type",
        "Segment", "OfferAmt", "Category", "Name", "Description", "Source",
    ]
    errors = []
    for i, offer in enumerate(offers):
        row = i + 2
        for field in required:
            val = offer.get(field)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                errors.append(f"Row {row}: Missing required field '{field}'")
    return errors


def validate_numerics(offers):
    """Ensure numeric fields are numeric."""
    errors = []
    for i, offer in enumerate(offers):
        row = i + 2
        for field in ["OfferAmt", "PrizeAmtMin", "PrizeAmtMax"]:
            val = offer.get(field, 0)
            if not isinstance(val, (int, float)):
                try:
                    offer[field] = float(val)
                except (ValueError, TypeError):
                    errors.append(f"Row {row}: '{field}' is not numeric: {val}")
                    offer[field] = 0
    return errors


def run_validation(offers, ref_values):
    """Full validation pipeline. Returns ValidationResult."""
    result = ValidationResult()

    # Deduplicate
    unique, dupes = deduplicate(offers)
    result.dupes_removed = dupes

    # Validate
    result.dropdown_errors = validate_dropdowns(unique, ref_values)
    result.errors.extend(validate_required_fields(unique))
    result.errors.extend(validate_numerics(unique))
    result.errors.extend(result.dropdown_errors)

    result.valid_offers = unique
    return result
