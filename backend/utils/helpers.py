import secrets
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from backend.config import get_settings
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

settings = get_settings()
ph = PasswordHasher()

CODE_ALPHABET = settings.CODE_ALPHABET
DEFAULT_CODE_LENGTH = settings.DEFAULT_CODE_LENGTH


def normalize_url(raw: str, strip_utm: bool = True) -> str:
    raw = raw.strip()
    parsed = urlparse(raw, scheme="http")
    if not parsed.netloc:
        parsed = urlparse("http://" + raw)
    scheme = parsed.scheme.lower()
    netloc = parsed.hostname.lower() if parsed.hostname else ""
    if parsed.port and (
        (scheme == "http" and parsed.port != 80)
        or (scheme == "https" and parsed.port != 443)
    ):
        netloc += f":{parsed.port}"
    q = parse_qsl(parsed.query, keep_blank_values=True)
    if strip_utm:
        q = [(k, v) for k, v in q if not k.lower().startswith("utm_")]
    q.sort()
    query = urlencode(q, doseq=True)
    return urlunparse(
        (scheme, netloc, parsed.path or "/", parsed.params, query, parsed.fragment)
    )


def generate_code(lenght: int = DEFAULT_CODE_LENGTH, alphabet: str = CODE_ALPHABET):
    return "".join(secrets.choice(alphabet) for _ in range(lenght))


def password_hash(password: str):
    if not password:
        raise ValueError("Password cannot be Empty!")

    return ph.hash(password)


def verify_password(hashed_password: str, login_password: str) -> bool:
    if not hashed_password or not login_password:
        return False
    try:
        return ph.verify(hashed_password, login_password)
    except Argon2Error:
        return False
