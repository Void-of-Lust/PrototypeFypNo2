import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from werkzeug.utils import secure_filename

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB per image
MAX_IMAGE_MB = MAX_IMAGE_BYTES // (1024 * 1024)
VALID_TABLES = tuple(f'A{i}' for i in range(1, 11))
MYT = timezone(timedelta(hours=8))


class UploadError(ValueError):
    """Raised when an uploaded file fails validation. The message is safe to show to the user."""


def _detect_image_type(header):
    """Identify the real image format from the first bytes of the file."""
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if header.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return 'webp'
    return None


def save_image(file, folder):
    """Validate an uploaded image and save it into `folder`.

    Checks the extension, the file size and the real file content (magic bytes),
    so a renamed .html or .py file cannot get through. The file is stored under a
    generated name, never the name the client sent. Returns the stored filename.
    """
    if file is None or not file.filename:
        raise UploadError('Tiada fail dipilih.')

    extension = os.path.splitext(file.filename)[1].lower().lstrip('.')
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ', '.join(sorted(e.upper() for e in ALLOWED_IMAGE_EXTENSIONS))
        raise UploadError(f'Jenis fail tidak dibenarkan. Gunakan: {allowed}.')

    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size == 0:
        raise UploadError('Fail kosong.')
    if size > MAX_IMAGE_BYTES:
        raise UploadError(f'Saiz fail terlalu besar. Maksimum {MAX_IMAGE_MB} MB.')

    header = file.stream.read(12)
    file.stream.seek(0)
    detected = _detect_image_type(header)
    if detected is None:
        raise UploadError('Kandungan fail bukan gambar yang sah.')

    stem = secure_filename(os.path.splitext(file.filename)[0])[:40] or 'gambar'
    filename = f'{uuid.uuid4().hex[:12]}_{stem}.{detected}'

    os.makedirs(folder, exist_ok=True)
    file.save(os.path.join(folder, filename))
    return filename


def delete_upload(folder, filename):
    """Remove a previously saved upload. Ignores empty names, paths and missing files."""
    if not filename or os.path.basename(filename) != filename:
        return
    try:
        os.remove(os.path.join(folder, filename))
    except OSError:
        pass


def parse_price(raw, maximum=Decimal('9999.99')):
    """Turn form input into a Decimal with 2 places, or None if it is not a valid price."""
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value < 0 or value > maximum:
        return None
    return value.quantize(Decimal('0.01'))


def normalize_table(raw):
    """Return a valid table code (A1-A10) or None if the input is invalid."""
    if not raw:
        return None
    cleaned = str(raw).strip().upper()
    return cleaned if cleaned in VALID_TABLES else None


def utc_now():
    """Current UTC timestamp as a naive datetime (matches SQLite/MySQL DATETIME columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_myt(dt):
    """Convert a naive UTC (or tz-aware) datetime to Malaysia Time (UTC+8)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MYT)


def myt_today():
    """Today's date in Malaysia Time (UTC+8)."""
    return datetime.now(MYT).date()


def myt_start_of_today_utc():
    """Midnight today in MYT, returned as a naive UTC datetime for DB filtering."""
    start_myt = datetime.now(MYT).replace(hour=0, minute=0, second=0, microsecond=0)
    return start_myt.astimezone(timezone.utc).replace(tzinfo=None)
