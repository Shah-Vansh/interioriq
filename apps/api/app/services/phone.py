"""Phone numbers are typed every possible way: '+91 98765-43210', '098765 43210', '(+91) 98765 43210', '0091 9876543210'.
normalize_phone() turns all of them into ONE canonical form (+919876543210) so duplicates are caught; it rejects text that isn't a phone number."""
import re

_ALLOWED = re.compile(r"^[\d\s\-().+/]+$")


class PhoneError(ValueError):
    pass


def normalize_phone(raw: str | None) -> str | None:
    if raw is None or not raw.strip(): return None
    s = raw.strip()
    if not _ALLOWED.match(s): raise PhoneError("A phone number may contain only digits, spaces, + - ( ) . /")
    if s.count("+") > 1: raise PhoneError("A phone number can have only one +")
    plus = s.lstrip("( ").startswith("+")
    if "+" in s and not plus: raise PhoneError("+ must come first (country code)")
    d = re.sub(r"\D", "", s)
    if not plus and d.startswith("00"): plus, d = True, d[2:]                 # 0091 98765 43210
    if plus:
        if not 8 <= len(d) <= 15: raise PhoneError("International numbers have 8 to 15 digits after the +")
        if d.startswith("91") and len(d) != 12: raise PhoneError("Indian numbers have 10 digits after +91")
        out = d
    elif len(d) == 10 and d[0] != "0": out = "91" + d                          # 98765 43210 / 79 2658 1234
    elif len(d) == 11 and d[0] == "0" and d[1] != "0": out = "91" + d[1:]      # 098765 43210 / 079 2658 1234 (STD code)
    elif len(d) == 12 and d.startswith("91") and d[2] != "0": out = d          # 91 98765 43210
    else: raise PhoneError("Enter a 10-digit number, or include the country code with +")
    if len(set(out[-10:])) == 1: raise PhoneError("That doesn't look like a real phone number")
    return "+" + out
