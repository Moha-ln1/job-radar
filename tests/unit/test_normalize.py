from jobradar.normalize import fold, norm_company, norm_title


def test_fold():
    assert fold("  Prácticas   DE  Diseño ") == "practicas de diseno"


def test_norm_title_quita_genero_y_sufijos():
    assert norm_title("Trainee Java (H/M)") == "trainee java"
    assert norm_title("Becario/a (m/f/d) - Madrid") == norm_title("Becario/a")
    assert norm_title("Data Analyst (h/m/x) – Remoto") == "data analyst"
    assert norm_title("[URGENTE] QA Tester (Remote)") == "qa tester"
    assert norm_title("Trainee m/f/d Java") == "trainee java"


def test_norm_title_conserva_sufijo_que_distingue():
    assert norm_title("Trainee - Java") != norm_title("Trainee - QA")


def test_norm_company():
    assert norm_company("NTT DATA Spain S.L.") == norm_company("NTT Data") == "ntt data"
    assert norm_company("Acme Group, Inc.") == "acme"
    assert norm_company(None) == ""


def test_parse_iso_formatos_de_fuentes_externas():
    from datetime import datetime, timezone
    from jobradar.normalize import parse_iso
    utc = timezone.utc
    assert parse_iso("2026-11-13T10:00:00.0000000") == datetime(2026, 11, 13, 10, 0, tzinfo=utc)  # Jooble
    assert parse_iso("2026-11-12T09:30:00.000Z") == datetime(2026, 11, 12, 9, 30, tzinfo=utc)
    assert parse_iso("2026-11-12T09:30:00+0100") == datetime(2026, 11, 12, 8, 30, tzinfo=utc)
    assert parse_iso("2026-11-12 09:30:00 UTC") == datetime(2026, 11, 12, 9, 30, tzinfo=utc)
    assert parse_iso("2026-11-12") == datetime(2026, 11, 12, tzinfo=utc)
    assert parse_iso("ayer") is None and parse_iso(None) is None
