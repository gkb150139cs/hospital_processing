"""Parsing and validation of uploaded hospital CSV files."""

import csv
import io

from pydantic import ValidationError

from .models import CsvRowError, HospitalRow

REQUIRED_COLUMNS = {"name", "address"}
ALLOWED_COLUMNS = {"name", "address", "phone"}


class CsvFormatError(Exception):
    """Raised when the CSV file itself is malformed (not row-level errors)."""


def parse_hospitals_csv(
    content: bytes, max_rows: int
) -> tuple[list[HospitalRow], list[CsvRowError]]:
    """Parse CSV bytes into validated hospital rows plus per-row errors.

    Raises CsvFormatError for file-level problems (bad encoding, missing
    header columns, empty file, too many rows).
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvFormatError("File is not valid UTF-8 encoded text") from exc

    if not text.strip():
        raise CsvFormatError("CSV file is empty")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise CsvFormatError("CSV file has no header row")

    header = [name.strip().lower() for name in reader.fieldnames]
    missing = REQUIRED_COLUMNS - set(header)
    if missing:
        raise CsvFormatError(
            f"CSV header is missing required column(s): {', '.join(sorted(missing))}. "
            "Expected header: name,address,phone"
        )
    unknown = set(header) - ALLOWED_COLUMNS
    if unknown:
        raise CsvFormatError(
            f"CSV header contains unknown column(s): {', '.join(sorted(unknown))}. "
            "Expected header: name,address,phone"
        )

    raw_rows = list(reader)
    if len(raw_rows) > max_rows:
        raise CsvFormatError(
            f"CSV contains {len(raw_rows)} hospitals; maximum allowed is {max_rows}"
        )
    if not raw_rows:
        raise CsvFormatError("CSV contains a header but no hospital rows")

    rows: list[HospitalRow] = []
    errors: list[CsvRowError] = []
    for index, raw in enumerate(raw_rows, start=1):
        data = {
            (key.strip().lower() if key else key): value
            for key, value in raw.items()
            if key is not None
        }
        try:
            rows.append(
                HospitalRow(
                    row=index,
                    name=data.get("name") or "",
                    address=data.get("address") or "",
                    phone=data.get("phone"),
                )
            )
        except ValidationError as exc:
            reasons = "; ".join(
                f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
                for err in exc.errors()
            )
            errors.append(CsvRowError(row=index, error=reasons))

    return rows, errors
