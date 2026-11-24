"""Certificate parsing/validation. The private key never leaves this module in
plaintext except to be encrypted; no API ever returns it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from ..errors import AppError, E
from ..security import utcnow

MAX_CERT_BYTES = 64 * 1024
MAX_KEY_BYTES = 32 * 1024


@dataclass
class CertFacts:
    common_name: str
    sans: list[str]
    serial: str
    fingerprint: str
    not_before: datetime
    not_after: datetime
    cert_pem: str
    chain_pem: str | None
    key_pem: str  # caller must encrypt immediately and discard


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def parse_certificate(pem: bytes) -> x509.Certificate:
    if len(pem) > MAX_CERT_BYTES:
        raise AppError(E["CERT_INVALID"], "证书文件过大", 422)
    try:
        return x509.load_pem_x509_certificate(pem)
    except Exception:
        raise AppError(E["CERT_INVALID"], "证书不是有效的 PEM/X.509 格式", 422)


def parse_chain(pem: bytes | None) -> tuple[str | None, list[x509.Certificate]]:
    if not pem or not pem.strip():
        return None, []
    if len(pem) > MAX_CERT_BYTES * 2:
        raise AppError(E["CERT_INVALID"], "证书链文件过大", 422)
    certs: list[x509.Certificate] = []
    for block in pem.split(b"-----END CERTIFICATE-----"):
        if b"BEGIN CERTIFICATE" not in block:
            continue
        block = block.strip() + b"\n-----END CERTIFICATE-----\n"
        try:
            certs.append(x509.load_pem_x509_certificate(block))
        except Exception:
            raise AppError(E["CERT_INVALID"], "证书链中存在无法解析的证书", 422)
    return pem.decode("utf-8", "replace"), certs


def parse_private_key(pem: bytes, password: str | None = None):
    if len(pem) > MAX_KEY_BYTES:
        raise AppError(E["CERT_INVALID"], "私钥文件过大", 422)
    try:
        return serialization.load_pem_private_key(pem, password=password.encode() if password else None)
    except TypeError:
        raise AppError(E["CERT_KEY_MISMATCH"], "私钥已加密，请提供口令或改用未加密私钥", 422)
    except Exception:
        raise AppError(E["CERT_INVALID"], "私钥不是有效的 PEM 格式", 422)


def _public_der(key) -> bytes:  # noqa: ANN001
    return key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _check_key_strength(key) -> None:  # noqa: ANN001
    if isinstance(key, rsa.RSAPrivateKey):
        if key.key_size < 2048:
            raise AppError(E["CERT_INVALID"], "RSA 私钥至少 2048 位", 422)
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        if key.key_size < 256:
            raise AppError(E["CERT_INVALID"], "ECDSA 私钥至少 256 位", 422)
    else:
        raise AppError(E["CERT_INVALID"], "仅支持 RSA / ECDSA 私钥", 422)


def _names(cert: x509.Certificate) -> tuple[str, list[str]]:
    try:
        cn = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
    except IndexError:
        cn = ""
    sans: list[str] = []
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        for n in ext.value:
            if isinstance(n, x509.DNSName):
                sans.append(str(n.value).lower())
    except x509.ExtensionNotFound:
        pass
    return str(cn).lower(), sans


def validate_for_domain(fqdn: str, cert_pem: bytes, key_pem: bytes,
                        chain_pem: bytes | None, key_password: str | None = None) -> CertFacts:
    cert = parse_certificate(cert_pem)
    key = parse_private_key(key_pem, key_password)
    _check_key_strength(key)

    cert_pub = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if cert_pub != _public_der(key):
        raise AppError(E["CERT_KEY_MISMATCH"], "私钥与证书不匹配", 422)

    cn, sans = _names(cert)
    names = set(sans) | ({cn} if cn else set())
    ok = fqdn in names or f"*.{'.'.join(fqdn.split('.')[1:])}" in names
    if not ok:
        # wildcard only matches one label, but accept `*.example.com` for a.example.com
        for n in names:
            if n.startswith("*.") and fqdn.endswith(n[1:]) and fqdn.count(".") == n.count("."):
                ok = True
    if not ok:
        raise AppError(E["CERT_DOMAIN_MISMATCH"], f"证书未覆盖域名 {fqdn}", 422)

    not_before, not_after = _naive(cert.not_valid_before_utc), _naive(cert.not_valid_after_utc)
    if not_after <= utcnow():
        raise AppError(E["CERT_EXPIRED"], "该证书已过期", 422)
    if not_before > utcnow():
        raise AppError(E["CERT_INVALID"], "该证书尚未生效", 422)

    chain_text, _ = parse_chain(chain_pem)
    fp = cert.fingerprint(hashes.SHA256()).hex()
    return CertFacts(
        common_name=cn or fqdn,
        sans=sans or ([cn] if cn else []),
        serial=format(cert.serial_number, "x"),
        fingerprint=":".join(fp[i : i + 2] for i in range(0, len(fp), 2)).upper(),
        not_before=not_before,
        not_after=not_after,
        cert_pem=cert_pem.decode("utf-8", "replace"),
        chain_pem=chain_text,
        key_pem=key_pem.decode("utf-8", "replace"),
    )


def days_left(not_after: datetime) -> int:
    return max(0, (not_after - utcnow()).days)
