import pytest

from app.csv_parser import CsvFormatError, parse_hospitals_csv


def test_parses_valid_csv():
    content = (
        "name,address,phone\n"
        "General Hospital,123 Main St,555-1234\n"
        "City Clinic,456 Oak Ave,\n"
    ).encode()
    rows, errors = parse_hospitals_csv(content, max_rows=20)
    assert errors == []
    assert len(rows) == 2
    assert rows[0].name == "General Hospital"
    assert rows[0].phone == "555-1234"
    assert rows[1].phone is None  # phone is optional


def test_handles_utf8_bom_and_whitespace():
    content = "\ufeffname,address,phone\n  Padded Hospital  , 1 Way ,\n".encode()
    rows, errors = parse_hospitals_csv(content, max_rows=20)
    assert errors == []
    assert rows[0].name == "Padded Hospital"
    assert rows[0].address == "1 Way"


def test_rejects_empty_file():
    with pytest.raises(CsvFormatError, match="empty"):
        parse_hospitals_csv(b"", max_rows=20)


def test_rejects_missing_required_columns():
    with pytest.raises(CsvFormatError, match="missing required column"):
        parse_hospitals_csv(b"name,phone\nA,1\n", max_rows=20)


def test_rejects_unknown_columns():
    with pytest.raises(CsvFormatError, match="unknown column"):
        parse_hospitals_csv(b"name,address,phone,extra\nA,B,C,D\n", max_rows=20)


def test_rejects_header_only():
    with pytest.raises(CsvFormatError, match="no hospital rows"):
        parse_hospitals_csv(b"name,address,phone\n", max_rows=20)


def test_enforces_max_rows():
    body = "".join(f"H{i},Addr {i},\n" for i in range(21))
    with pytest.raises(CsvFormatError, match="maximum allowed is 20"):
        parse_hospitals_csv(f"name,address,phone\n{body}".encode(), max_rows=20)


def test_reports_row_level_errors():
    content = (
        "name,address,phone\n"
        "Valid Hospital,123 Main St,555\n"
        ",Missing Name St,\n"
        "Missing Address,,\n"
    ).encode()
    rows, errors = parse_hospitals_csv(content, max_rows=20)
    assert len(rows) == 1
    assert {error.row for error in errors} == {2, 3}


def test_rejects_non_utf8():
    with pytest.raises(CsvFormatError, match="UTF-8"):
        parse_hospitals_csv(b"\xff\xfe\x00bad", max_rows=20)
