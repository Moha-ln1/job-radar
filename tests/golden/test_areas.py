"""Clasificación por áreas con títulos reales (auditoría del 16/11/2026 sobre 991 ofertas).

Cada caso: título real -> áreas que DEBE reconocer y áreas que NO debe reconocer. Los casos "no debe"
son falsos positivos que ya ocurrieron (nombre de empresa, "Spring 2027", "Growth Hacking"...).
"""
import pytest

from jobradar import radar
from jobradar.filters import Catalog, Synonyms, match_text

SYN = Synonyms.from_files(radar._DATA / "sinonimos.yaml")
CAT = Catalog.from_file(radar._DATA / "catalogo.yaml")

CASES = [
    # (título, debe, no_debe)
    ("Técnico Informático Junior – Granada", {"sistemas"}, set()),
    ("Prácticas Técnico/a de Sistemas y Soporte CAU", {"sistemas"}, set()),
    ("IT Support Technician Intern STP27", {"sistemas"}, set()),
    ("IT Systems Intern (Start December) - Hotel Arts Barcelona", {"sistemas"}, set()),
    ("Técnico/a Junior de Redes - Sistemas Espaciales", {"sistemas"}, set()),
    ("Prácticas DAM - Desarrollo de Aplicaciones Multiplataforma", {"programador"}, set()),
    ("Prácticas ASIR / SMR", {"sistemas"}, set()),
    ("PRÁCTICAS EN EMPRESA + DISEÑO Y DESARROLLO WEB", {"programador", "diseno"}, set()),
    ("Programador/a Java Junior con Francés", {"programador"}, set()),
    ("Desarrollador/a Junior C++ Sist. Comunicaciones -Cádiz", {"programador"}, set()),
    ("Junior Salesforce Developer", {"programador"}, set()),
    ("Junior ServiceNow Developer", {"programador"}, set()),
    ("Jr. Software Engineer", {"programador"}, set()),
    ("Spring Boot Developer Junior", {"programador"}, set()),
    ("Intern, Data Engineer", {"data"}, set()),
    ("Data Engineering graduate", {"data"}, set()),
    ("AI Trainee", {"data"}, set()),
    ("ML Engineer Intern", {"data"}, set()),
    ("Computer Vision Intern", {"data"}, set()),
    ("Prácticas Visión por Computador", {"data"}, set()),
    ("Becario/a Analista BI - Power BI", {"data"}, set()),
    ("Software QA Intern", {"qa"}, set()),
    ("Graduate security engineer", {"ciberseguridad"}, set()),
    ("University - 2027 Summer Games Cyber Security Intern", {"ciberseguridad"}, set()),
    ("2027 Summer Intern: Associate DevOps Engineer", {"sistemas"}, set()),
    ("AWS Support Associate (Trainee)", {"sistemas"}, set()),
    ("Estudiante en prácticas de Industria 4.0 y digitalización", {"ingenieria", "sistemas"}, set()),
    ("Prácticas en Calidad y Seguridad de Máquinas", {"ingenieria"}, set()),
    ("Estudiante en prácticas – departamento de producción MSE 1.1 (c)", {"ingenieria"}, set()),
    ("Prácticas en PRL", {"ingenieria"}, set()),
    ("QHSSE Junior", {"ingenieria"}, set()),
    ("Craft Worker Intern – Electric Meter Technician", {"ingenieria"}, set()),
    ("Ingeniero/a de Caminos Junior - Huelva", {"arquitectura"}, set()),
    ("Fontanero/a sin experiencia en Jaén", {"arquitectura"}, set()),
    ("Landscape Internship", {"arquitectura"}, set()),
    ("Property Junior - Promotora Inmobiliaria", {"arquitectura"}, set()),
    ("Prácticas Gestor de Proyectos", {"producto"}, set()),
    ("Becario/a de Creatividad y Contenido Publicitario", {"marketing"}, set()),
    ("Junior Market Analyst", {"marketing"}, set()),
    ("Digital Commerce Intern - Summer 2027", {"marketing"}, {"programador"}),
    ("Becario/a Campaña de la Renta 2027 (Prácticas Retribuidas)", {"finanzas"}, set()),
    ("M&A Praktikum Intern", {"finanzas"}, set()),
    ("Claims Intern", {"finanzas"}, set()),
    ("Prácticas en Headhunting", {"rrhh"}, set()),
    ("People Trainee - People Operations", {"rrhh"}, set()),
    ("Oferta de Prácticas – Departamento Laboral", {"legal"}, set()),
    ("Practicas Comercio Internacional", {"logistica"}, set()),
    ("Graduate Transport Planner", {"logistica"}, set()),
    ("España PRÁCTICAS EN ESCUELA INFANTIL CENTRO INFANTIL EL BARRIO GRANADA", {"educacion"}, set()),
    ("Psicopedagogos - Clases Particulares - Sin Experiencia", {"educacion"}, set()),
    ("España Prácticas en Atención Multilingüe (online)", {"atencion_cliente"}, set()),
    ("F&B Service Trainee", {"hosteleria"}, set()),
    ("Kitchen Trainee", {"hosteleria"}, set()),
    ("Summer Pharmacy Intern", {"salud"}, set()),
    ("Prácticas en Patronaje y Calidad Textil", {"diseno"}, set()),
    ("TalentLab FIATC | Gerente de Equipo Junior", {"ventas"}, set()),
    ("Data Entry Clerk (Junior)", {"administracion"}, {"data"}),
    # Falsos positivos que ya ocurrieron
    ("Prácticas remuneradas BPS NTT DATA | ADE, Economía o similares", {"finanzas"}, {"data"}),
    ("Communications Intern, HQ (Spring 2027)", {"comunicacion"}, {"programador"}),
    ("Audit Internship - Spring 2028", {"finanzas"}, {"programador"}),
    ("Growth Hacking Intern", {"marketing"}, {"ciberseguridad"}),
    ("Prácticas en Marketing Digital: Web, Redes Sociales, Seo y Geo", {"marketing"}, {"sistemas"}),
    ("PRÁCTICAS TÉCNICO CONTROL DE CALIDAD", {"ingenieria"}, {"qa"}),
]


TIPO_CASES = [
    # (título, debe, no_debe)
    ("Practicante de Ingeniería Industrial – Operaciones y Customer Support", {"practicas"}, set()),
    ("Estudiante en prácticas – departamento de producción (MSS4_USS)", {"practicas"}, set()),
    ("Becario/a Campaña de la Renta 2027", {"practicas"}, set()),
    ("Marketing Student Assistant", {"practicas"}, set()),
    ("M&A Praktikum Intern", {"practicas"}, set()),
    ("Prácticas FCT - Técnico de Sistemas", {"practicas"}, set()),
    ("Graduate Programme 2027: Software Engineer (Java)", {"trainee"}, set()),
    ("Early Careers Programme - Software", {"trainee"}, set()),
    ("Fontanero/a sin experiencia en Jaén", {"junior"}, set()),
    ("Jr. Software Engineer", {"junior"}, set()),
    ("COORDINADOR/A DE GRUPOS ESTUDIANTES EXTRANJEROS", set(), {"practicas"}),
    ("Senior Data Engineer", set(), {"practicas", "trainee", "junior", "bootcamp"}),
]


def tipos_of(title: str) -> set[str]:
    text = match_text(title)
    return {key for key in CAT.tipos if SYN.search(key, text)}


@pytest.mark.parametrize("title,must,must_not", TIPO_CASES, ids=[c[0][:50] for c in TIPO_CASES])
def test_tipo(title, must, must_not):
    found = tipos_of(title)
    assert must <= found, f"faltan {must - found}; reconocidos {found}"
    assert not (must_not & found), f"no debería reconocer {must_not & found}"


def areas_of(title: str) -> set[str]:
    text = match_text(title)
    return {key for key in CAT.areas if SYN.search(key, text)}


@pytest.mark.parametrize("title,must,must_not", CASES, ids=[c[0][:50] for c in CASES])
def test_area(title, must, must_not):
    found = areas_of(title)
    assert must <= found, f"faltan {must - found}; reconocidas {found}"
    assert not (must_not & found), f"no debería reconocer {must_not & found}"
