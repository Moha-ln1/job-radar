"""Filtros: sinónimos, catálogo y evaluación de ofertas (reglas de docs/ARQUITECTURA.md 1.1 y 4.1)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .models import Decision, Exclusions, JobOffer, Modality, Search
from .normalize import fold, norm_company

LIVE_BOARDS = ("greenhouse:", "lever:", "ashby:", "smartrecruiters:", "workday:", "recruitee:",
               "personio:", "teamtailor:")
# Ubicaciones demasiado genéricas para descartar una búsqueda por ciudad: se incluyen.
_GENERIC_LOCATIONS = {"spain", "espana", "europe", "europa", "emea", "remote", "remoto",
                      "hybrid", "hibrido", "worldwide", "anywhere", "global"}


def _load_yaml(path: Path | None) -> dict:
    if path is None or not Path(path).exists():
        return {}
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _variants(word: str) -> str:
    """Regex de una palabra fold con femenino/plural opcionales."""
    if word.endswith("/a"):
        word = word[:-2]
    elif word.endswith("(a)"):
        word = word[:-3]
    if not word or not word[-1].isalpha():
        return re.escape(word)
    # Plural en la lista -> también el singular ("contenidos" casa con "contenido", "docentes" con
    # "docente", "operaciones" con "operación", "events" con "event")
    if len(word) - 2 >= 4 and word.endswith("es"):
        return re.escape(word[:-2]) + "(?:es|e|s)?"
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if word[-1] in "oa":
        return re.escape(word[:-1]) + "(?:o|a|os|as)"
    if word[-1] == "r":
        return re.escape(word) + "(?:a|es|as|s)?"  # programadora/es/as y careers/developers
    return re.escape(word) + "(?:s|es)?"


def _term_regex(term: str) -> str:
    words = [w for w in re.split(r"[\s\-]+", fold(term)) if w]
    return r"[\s\-]+".join(_variants(w) for w in words)


def word_pattern(terms: list[str], variants: bool = True) -> re.Pattern:
    """Patrón por palabra completa sobre texto fold para uno o varios términos."""
    if variants:
        alts = [_term_regex(t) for t in terms]
    else:
        alts = [re.escape(fold(t)) for t in terms]
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(alts) + r")(?![a-z0-9])")


class Synonyms:
    """Grupos de sinónimos. Un término que empieza por "!" es una excepción del grupo: ese texto se
    ignora antes de buscar (p. ej. "!ntt data" para que el nombre de la empresa no cuente como Datos)."""

    def __init__(self, groups: dict[str, list[str]]):
        self.groups: dict[str, list[str]] = {}
        self.negatives: dict[str, list[str]] = {}
        for k, v in groups.items():
            terms = [str(t) for t in v or []]
            self.groups[fold(k)] = list(dict.fromkeys(
                [fold(k)] + [fold(t) for t in terms if not t.startswith("!")]))
            self.negatives[fold(k)] = [fold(t[1:]) for t in terms if t.startswith("!") and t[1:].strip()]
        self._cache: dict[str, re.Pattern] = {}
        self._neg_cache: dict[str, re.Pattern | None] = {}

    @classmethod
    def from_files(cls, base: Path, user: Path | None = None) -> "Synonyms":
        groups: dict[str, list[str]] = {k: list(v) for k, v in _load_yaml(base).items()}
        for k, v in _load_yaml(user).items():
            groups.setdefault(k, []).extend(v or [])
        return cls(groups)

    def expand(self, term: str) -> list[str]:
        t = fold(term)
        out: list[str] = []
        for key, members in self.groups.items():
            if t == key or t in members:
                out.extend(m for m in members if m not in out)
        return out or [t]

    def pattern(self, term: str) -> re.Pattern:
        t = fold(term)
        if t not in self._cache:
            self._cache[t] = word_pattern(self.expand(t))
        return self._cache[t]

    def search(self, term: str, text: str) -> re.Match | None:
        """Busca el término (y sus sinónimos) en un texto ya plegado, quitando antes sus excepciones."""
        t = fold(term)
        if t not in self._neg_cache:
            negs = [n for key, members in self.groups.items() if t == key or t in members
                    for n in self.negatives.get(key, [])]
            self._neg_cache[t] = word_pattern(negs, variants=False) if negs else None
        neg = self._neg_cache[t]
        return self.pattern(t).search(neg.sub(" ", text) if neg else text)


class Catalog:
    def __init__(self, data: dict):
        self.tipos: dict[str, str] = data.get("tipos", {})
        self.areas: dict[str, str] = data.get("areas", {})
        self.ubicaciones: dict[str, dict] = data.get("ubicaciones", {})
        self.remote_regions_ok: list[str] = data.get("remote_regions_ok", [])
        self.remote_regions_no: list[str] = data.get("remote_regions_no", [])
        self.portal_words: dict[str, str] = data.get("consulta_portal", {})
        known = {fold(a) for e in self.ubicaciones.values() for a in e.get("aliases", [])}
        known |= {fold(k) for k in self.ubicaciones} | {fold(a) for a in data.get("otras_ubicaciones", [])}
        known -= _GENERIC_LOCATIONS
        self._known = word_pattern(sorted(known), variants=False) if known else None

    def portal_word(self, area: str) -> str:
        """Palabra con la que buscar un área en un portal ("programador", "data"...)."""
        if area in self.portal_words:
            return self.portal_words[area]
        label = self.areas.get(area)
        return label.split("/")[0].strip().lower() if label else area

    def known_place(self, location: str) -> bool:
        """¿La ubicación nombra algún lugar conocido (de cualquier región)?"""
        return bool(self._known and self._known.search(fold(location)))

    @classmethod
    def from_file(cls, path: Path) -> "Catalog":
        return cls(_load_yaml(path))

    def location_terms(self, key: str, _seen: frozenset = frozenset()) -> list[str]:
        """Alias de una ubicación del catálogo (más los de las zonas que `incluye`); si no está, el texto."""
        entry = self.ubicaciones.get(fold(key))
        if not entry:
            return [fold(key)]
        terms = [fold(a) for a in entry.get("aliases", [])] + [fold(key)]
        for sub in entry.get("incluye", []):
            if sub not in _seen:
                terms += self.location_terms(sub, _seen | {fold(key)})
        return list(dict.fromkeys(terms))


def detect_modality(offer: JobOffer, syn: Synonyms) -> Modality | None:
    if offer.modality:
        return offer.modality
    text = fold(f"{offer.title} {offer.location or ''}")
    for key in ("hibrido", "remoto", "presencial"):
        if syn.search(key, text):
            return key  # type: ignore[return-value]
    return None


def _first_match(terms: list[str], text: str, syn: Synonyms) -> tuple[str, str] | None:
    """Primer término de la lista que encaja con el texto: (término, texto encontrado)."""
    for term in terms:
        m = syn.search(term, text)
        if m:
            return term, m.group(0)
    return None


def _group_matches(terms: list[str], text: str, syn: Synonyms, labels: dict[str, str]):
    """None si la lista está vacía/'cualquiera'; si no, (etiqueta, hallado) o False."""
    if not terms or any(fold(t) == "cualquiera" for t in terms):
        return None
    hit = _first_match(terms, text, syn)
    if not hit:
        return False
    term, found = hit
    return labels.get(fold(term), term), found


def _location_ok(search: Search, location: str, catalog: Catalog) -> bool:
    loc = fold(location)
    if loc in _GENERIC_LOCATIONS:
        return True
    if any(word_pattern(catalog.location_terms(u), variants=False).search(loc)
           for u in search.ubicaciones):
        return True
    # Solo se descarta si la ubicación se reconoce como de otro sitio. Una ubicación
    # desconocida (municipio pequeño, "Location Negotiable"...) pasa: ante la duda, se incluye.
    return not catalog.known_place(loc)


def _remote_region_ok(search: Search, region: str, catalog: Catalog) -> bool:
    reg = fold(region)
    specific_ok = [fold(r) for r in catalog.remote_regions_ok if fold(r) != "remote"]
    if specific_ok and word_pattern(specific_ok, variants=False).search(reg):
        return True
    bad = [fold(r) for r in catalog.remote_regions_no]
    if bad and word_pattern(bad, variants=False).search(reg):
        # Se permite solo si la búsqueda pide expresamente esa región.
        return any(fold(u) and fold(u) in reg for u in search.ubicaciones)
    return True  # región desconocida: pasa


AREA_UNKNOWN = "área no indicada en el título"
# Marcas de género que cortan frases: "Técnico/a de redes", "Ingeniero (a) de caminos", "becario/as"
_GENDER = re.compile(r"(?<=[a-z])\s?(?:/\s?(?:a|as|o|os|es)|\(\s?(?:a|as|o|os|es)\s?\))(?![a-z])")


def match_text(text: str) -> str:
    """Texto plegado y sin marcas de género, listo para buscar sinónimos."""
    return _GENDER.sub("", fold(text))


def _any_area(text: str, syn: Synonyms, catalog: Catalog) -> bool:
    return any(syn.search(key, text) for key in catalog.areas)


def _eval_search(offer: JobOffer, s: Search, text: str, modality, syn: Synonyms,
                 catalog: Catalog) -> tuple[bool, str, bool]:
    """(encaja, motivo, dudosa) de una búsqueda concreta. Dudosa = pasa solo porque el título no
    dice el área (p. ej. "Estudiante en prácticas Departamento TEF7"): ante la duda, se incluye."""
    parts: list[str] = []
    uncertain = False
    tipo = _group_matches(s.tipos, text, syn, catalog.tipos)
    if tipo is False:
        return False, f"búsqueda '{s.name}': ningún tipo de {s.tipos} reconocido en el título", False
    if tipo:
        parts.append(f"tipo '{tipo[0]}' ({tipo[1]})")
    area = _group_matches(s.areas, text, syn, catalog.areas)
    if area is False:
        if _any_area(text, syn, catalog):  # el título es de otra área conocida
            return False, f"búsqueda '{s.name}': ningún área de {s.areas} reconocida en el título", False
        parts.append(AREA_UNKNOWN)
        uncertain = True
    elif area:
        parts.append(f"área '{area[0]}' ({area[1]})")
    if s.modalidades and modality is not None and modality not in s.modalidades:
        return False, f"búsqueda '{s.name}': modalidad '{modality}' no está en {s.modalidades}", False
    if modality == "remoto":
        # Sin campo de región, la región suele venir en la ubicación ("Remote (US only)").
        region = offer.remote_region or offer.location
        if region and not _remote_region_ok(s, region, catalog):
            return False, f"búsqueda '{s.name}': región remota '{region}' no admitida", False
    elif s.ubicaciones and offer.location and not _location_ok(s, offer.location, catalog):
        return False, (f"búsqueda '{s.name}': ubicación '{offer.location}' "
                       f"no está en {s.ubicaciones}"), False
    return True, f"encaja con '{s.name}'" + (": " + ", ".join(parts) if parts else ""), uncertain


def evaluate(offer: JobOffer, searches: list[Search], excl: Exclusions, syn: Synonyms,
             catalog: Catalog, now: datetime, max_age_days: int = 14) -> Decision:
    title_fold = match_text(offer.title)
    text = match_text(f"{offer.title} {offer.category or ''}")  # nunca la descripción
    active = [s for s in searches if not s.paused]
    notes: list[str] = []

    # Los portales de empleo de empresa solo listan ofertas abiertas: una fecha antigua no significa
    # que esté cerrada (programas de graduados que siguen abiertos meses), así que no se descartan por edad.
    if offer.posted_at is not None and not offer.source.startswith(LIVE_BOARDS):
        posted = offer.posted_at
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        if posted < now - timedelta(days=max_age_days):
            return Decision(matched=[], priority=None, reasons=[
                f"demasiado antigua: publicada hace {(now - posted).days} días "
                f"(máximo {max_age_days})"])

    # Exclusiones: solo el título; la empresa por nombre normalizado.
    excluded_by: str | None = None
    comp = norm_company(offer.company)
    for c in excl.companies:
        if comp and norm_company(c) == comp:
            excluded_by = f"empresa '{c}' excluida"
            break
    is_company = excluded_by is not None
    if not excluded_by:
        for w in excl.words:
            if syn.search(w, title_fold):
                excluded_by = f"excluida por '{w}' en el título"
                break
    if excluded_by:
        tipo_terms = [t for s in active for t in s.tipos if fold(t) != "cualquiera"]
        hit = _first_match(tipo_terms, title_fold, syn)
        if hit and not is_company:
            notes.append(f"{excluded_by}, pero el título también encaja con el tipo "
                         f"'{hit[0]}': caso ambiguo, se incluye")
        else:
            return Decision(matched=[], priority=None, reasons=[excluded_by])

    if not active:
        return Decision(matched=[], priority=None, reasons=["ninguna búsqueda activa"])

    modality = detect_modality(offer, syn)
    matched: list[str] = []
    reasons: list[str] = []
    fails: list[str] = []
    priorities: set[str] = set()
    for s in active:
        ok, why, uncertain = _eval_search(offer, s, text, modality, syn, catalog)
        if ok:
            matched.append(s.id)
            reasons.append(why)
            # Si solo encaja por no indicar el área, va al resumen diario: no se pierde, pero no interrumpe
            priorities.add("normal" if uncertain else s.prioridad)
        else:
            fails.append(why)
    if matched:
        priority = "alta" if "alta" in priorities else "normal"
        return Decision(matched=matched, priority=priority, reasons=notes + reasons)
    return Decision(matched=[], priority=None, reasons=notes + fails)
