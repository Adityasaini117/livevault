"""Privacy guardrails and sensitive-data filtering for LifeVault.

Detects and rejects:
- Card-number-like digit runs (Luhn-valid 13-19 digits)
- CVV / PIN / password / OTP phrasing
- Bank account / IBAN patterns
- SSN / Aadhaar / passport-number-like IDs

Does not block normal records:
- Dates (e.g. 2026-10-16)
- Amounts (e.g. 249, 1200.50)
- Phone-model numbers (e.g. iPhone 15 Pro, Pixel 8)
- Serial-like short tokens (e.g. SN-123456, AB12CD34)
- Purchase IDs under 13 digits (e.g. Order #987654321)
- Bare 12-digit runs (without Aadhaar keyword or 4-4-4 grouping)

Never logs, echoes, or stores rejected values.
"""

import re
from typing import Optional

PRIVACY_REJECTION_MESSAGE = (
    "I can't store card numbers, passwords or ID numbers. Tell me just the item and dates."
)


def is_luhn_valid(digits: str) -> bool:
    """Verify Luhn checksum for a string of digits."""
    if not digits.isdigit() or len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    reverse_digits = digits[::-1]
    for i, char in enumerate(reverse_digits):
        n = int(char)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _check_card_numbers(text: str) -> bool:
    """Detect card numbers (13-19 digits with Luhn checksum validity).

    Strips spaces and hyphens within candidate digit runs.
    Ignores digit runs that fail Luhn.
    """
    # Matches complete sequences of digits separated by spaces or hyphens.
    candidate_pattern = re.compile(r"\b\d+(?:[ -]+\d+)*\b")
    for match in candidate_pattern.finditer(text):
        digits_only = re.sub(r"[ -]", "", match.group(0))
        if 13 <= len(digits_only) <= 19 and is_luhn_valid(digits_only):
            return True
    return False


def _check_cvv_pin_password_otp(text: str) -> bool:
    """Detect CVV, PIN, password, or OTP phrasing."""
    lower = text.lower()

    # CVV / CVC phrasing (e.g., "cvv 123", "cvv: 456", "my cvc is 789")
    if re.search(r"\b(?:cvv2?|cvc2?)\b", lower):
        return True
    if re.search(r"\bsecurity\s+code\b\s*[:=]?\s*\d{3,4}\b", lower):
        return True

    # PIN phrasing (e.g., "pin: 1234", "my pin is 1234", "atm pin 1234", "pin code 1234")
    # Must avoid matching words like "bowling pin", "safety pin", "alpine", etc.
    if re.search(r"\b(?:atm|card|secret)\s+pin\b", lower):
        return True
    if re.search(r"\bpin\s+code\b", lower):
        return True
    if re.search(r"\bpin\b\s*(?:is|:|=)\s*\d{3,8}\b", lower):
        return True
    if re.search(r"\bmy\s+pin\s*(?:is)?\s*\d{3,8}\b", lower):
        return True

    # Password / passcode phrasing
    if re.search(r"\b(?:passwords?|passcodes?|passwd)\b", lower):
        return True
    if re.search(r"\bpwd\b\s*[:=]\s*\S+", lower):
        return True

    # OTP phrasing
    if re.search(r"\b(?:otp|one[- ]time\s+passwords?|verification\s+codes?|auth\s+codes?)\b", lower):
        return True

    return False


def _check_bank_and_iban(text: str) -> bool:
    """Detect IBAN patterns and bank account / routing numbers."""
    # IBAN pattern: 2 uppercase country letters + 2 check digits + 11 to 30 alphanumeric characters
    # Allowed with optional spaces every 4 characters.
    # Note: minimum length of clean IBAN is 15 characters.
    clean_text = text.strip()
    iban_candidates = re.finditer(r"\b([A-Za-z]{2}\d{2}(?:[ ]?[A-Za-z0-9]){11,30})\b", clean_text)
    for match in iban_candidates:
        candidate = match.group(1).replace(" ", "")
        # Valid IBAN starts with 2 letters and 2 digits, and total length between 15 and 34
        if len(candidate) >= 15 and len(candidate) <= 34 and candidate[:2].isalpha() and candidate[2:4].isdigit():
            return True

    lower = text.lower()
    # Bank account phrasing followed by digit runs (6-17 digits)
    if re.search(r"\b(?:bank\s+account|account\s+(?:number|no|num|#)|acct\s+(?:number|no|num|#)|checking\s+account)\b\s*[:=]?\s*\d{6,17}\b", lower):
        return True
    # Routing number phrasing
    if re.search(r"\brouting\s+(?:number|no|num|#)\b\s*[:=]?\s*\d{9}\b", lower):
        return True

    return False


def _check_government_ids(text: str) -> bool:
    """Detect SSN, Aadhaar, and passport number patterns.

    - SSN: standard 3-2-4 format or keyword with 9 digits.
    - Aadhaar: strict 4-4-4 grouped format (e.g. 1234 5678 9012 or 1234-5678-9012)
      or with adjacent keyword 'aadhaar'. Bare 12-digit runs without grouping or keyword are NOT rejected.
    - Passport: only when adjacent keywords (passport number, passport #, etc.) or passport: <ID> are present.
    """
    lower = text.lower()

    # SSN: formatted 3-2-4 digits (e.g. 123-45-6789 or 123 45 6789)
    if re.search(r"(?<!\d)(?<!\d[- ])\d{3}[- ]\d{2}[- ]\d{4}(?!\d|[- ]\d)", text):
        return True
    # SSN with keyword (e.g. "ssn: 123456789", "social security: 123456789")
    if re.search(r"\b(?:ssn|social\s+security(?:\s+number)?)\b\s*[:=]?\s*\d{3}[- ]?\d{2}[- ]?\d{4}\b", lower):
        return True
    if re.search(r"\b(?:ssn|social\s+security(?:\s+number)?)\b\s*[:=]?\s*\d{9}\b", lower):
        return True

    # Aadhaar: strict 12-digit grouped format (4-4-4 digits with spaces or hyphens)
    # Must be exactly 3 groups of 4 digits, not part of a 16-digit card number or longer sequence
    if re.search(r"(?<!\d)(?<!\d[- ])\d{4}[ -]\d{4}[ -]\d{4}(?!\d|[- ]\d)", text):
        return True
    # Aadhaar with keyword (allows contiguous or grouped digits, but bare 12 digits alone without keyword are not matched)
    if re.search(r"\b(?:aadhaar|aadhar)\b(?:\s*(?:number|no|num|#|id|card))?\s*[:=]?\s*\d{4}[ -]?\d{4}[ -]?\d{4}\b", lower):
        return True
    if re.search(r"\b(?:aadhaar|aadhar)\b", lower):
        return True

    # Passport: requires adjacent keywords or passport: ID syntax
    # Avoids rejecting document names like "US Passport" or "Passport renewal"
    if re.search(r"\bpassport\s*(?:number|no|num|#|id)\s*[:=]?\s*[A-Za-z0-9]{6,12}\b", lower):
        return True
    if re.search(r"\bpassport\s*[:=]\s*[A-Za-z0-9]{6,12}\b", lower):
        return True
    # "passport" followed directly by an alphanumeric identifier that contains at least one digit
    match_passport = re.search(r"\bpassport\s+([A-Za-z0-9]{6,12})\b", text, re.IGNORECASE)
    if match_passport:
        token = match_passport.group(1)
        # If the token has at least one digit (like A1234567 or 12345678), treat as passport number
        if any(c.isdigit() for c in token):
            return True

    # Generic ID phrasing (e.g. "id number: 123456", "national id: 7891011")
    if re.search(r"\b(?:id\s+(?:number|no|num|#)|national\s+id|gov(?:ernment)?\s+id)\b\s*[:=]?\s*[A-Za-z0-9]{6,20}\b", lower):
        return True

    return False


def is_sensitive(text: Optional[str]) -> bool:
    """Check if the provided text contains sensitive data.

    Returns True if sensitive data is detected, False otherwise.
    Never logs or stores the input value.
    """
    if not text or not isinstance(text, str):
        return False

    trimmed = text.strip()
    if not trimmed:
        return False

    if _check_card_numbers(trimmed):
        return True
    if _check_cvv_pin_password_otp(trimmed):
        return True
    if _check_bank_and_iban(trimmed):
        return True
    if _check_government_ids(trimmed):
        return True

    return False


def check_sensitive_data(text: Optional[str]) -> Optional[str]:
    """Inspect text and return friendly rejection message if sensitive data is found.

    Returns PRIVACY_REJECTION_MESSAGE if sensitive data is detected, None otherwise.
    Never logs or echoes the rejected value.
    """
    if is_sensitive(text):
        return PRIVACY_REJECTION_MESSAGE
    return None
