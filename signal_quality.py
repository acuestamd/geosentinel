"""Conservative, inspectable text triage for open-source health signals.

This is a rule-based screening aid, not a validated epidemiological classifier.
It deliberately abstains when a document cannot be tied to one event and place.
No output is a probability or independent confirmation of the source's claim.
"""

import html
import re
import unicodedata
from datetime import datetime, timezone


RULE_VERSION = "1.0"


def _norm(text):
    return "".join(c for c in unicodedata.normalize("NFKD", str(text or ""))
                   if not unicodedata.combining(c)).lower()


def _pattern(term):
    return r"(?<!\w)" + re.escape(_norm(term)) + r"(?!\w)"


def _clean(text):
    text = html.unescape(str(text or ""))
    text = re.sub(r"<[^>]*>", " ", text)
    # Broken display URLs may contain spaces inserted by HTML spans. Once a
    # scheme is detached from its address, the remainder of that line is not
    # reliable prose evidence. This intentionally loses some text to abstain.
    text = re.sub(r"https?://\s+[^\n]*", " ", text, flags=re.I)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text, flags=re.I)
    # A publisher's domain, handle or attribution is not an event location.
    text = re.sub(r"(?<!\w)[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|news|co\.uk|fr|de|es|uk|us|ca|au)(?:/\S*)?", " ", text, flags=re.I)
    text = re.sub(r"(?<!\w)@[\w.@-]+", " ", text)
    text = re.sub(r"#\s*(?=\w)", "", text)
    text = re.sub(r"\bU\.S\.(?:A\.)?", "United States", text, flags=re.I)
    text = re.sub(r"\bUS\b", "United States", text)
    text = re.sub(r"\bU\.K\.", "United Kingdom", text, flags=re.I)
    text = re.sub(r"\bEE\.\s*UU\.", "Estados Unidos", text, flags=re.I)
    text = re.sub(r"^(?:France\s*24|The Guardian|Reuters|BBC(?: News)?|AP(?: News)?|CNN|Al Jazeera)\s*[:|—–-]\s*", "", text, flags=re.I)
    return re.sub(r"[ \t]+", " ", text).strip()


_ALIASES = {
    "bird flu": "avian flu", "avian influenza": "avian flu",
    "gripe aviar": "avian flu", "grippe aviaire": "avian flu",
    "monkeypox": "mpox", "viruela simica": "mpox",
    "tb": "tuberculosis", "lassa": "lassa fever", "hanta": "hantavirus",
    "whooping cough": "pertussis", "tos ferina": "pertussis", "coqueluche": "pertussis",
    "diarrhoea": "diarrhea", "diarrea": "diarrhea", "diarrhee": "diarrhea",
    "covid-19": "covid", "sars-cov-2": "covid", "sars cov 2": "covid",
    "colera": "cholera", "cholera": "cholera",
    "sarampion": "measles", "rougeole": "measles",
    "paludismo": "malaria", "paludisme": "malaria",
    "fiebre amarilla": "yellow fever", "fievre jaune": "yellow fever",
    "fiebre de lassa": "lassa fever", "fievre de lassa": "lassa fever",
    "fiebre": "fever", "fievre": "fever",
    "enfermedad desconocida": "mystery illness", "maladie inconnue": "mystery illness",
    "crimean congo": "crimean-congo", "crimee-congo": "crimean-congo",
    "cchf": "crimean-congo",
    "crimea-congo": "crimean-congo", "fiebre hemorragica de crimea-congo": "crimean-congo",
    "sudan ebolavirus": "sudan virus", "ebolavirus sudan": "sudan virus",
}


def _disease_mentions(text):
    # Lazy imports avoid a scanner -> signal_quality -> scanner import cycle.
    from scanner_v2 import DISEASES
    terms = {name: _ALIASES.get(name, name) for name in DISEASES}
    terms.update(_ALIASES)
    found = []
    for term, canonical in terms.items():
        for match in re.finditer(_pattern(term), text):
            found.append((match.start(), match.end(), canonical, match.group()))
    # Long names own their embedded words: "yellow fever" is not also "fever".
    selected = []
    for item in sorted(found, key=lambda x: (-(x[1] - x[0]), x[0])):
        if not any(item[0] < other[1] and other[0] < item[1] for other in selected):
            selected.append(item)
    return sorted(selected)


def _disease_info(name):
    from scanner_v2 import DISEASES
    if not name:
        return None
    info = DISEASES.get(name, {"cat": "unknown", "sev": 4, "emoji": "🌡️"})
    return {"name": name, "cat": info["cat"], "sev": info["sev"], "emoji": info["emoji"]}


def _entry(keys, name, country, iso, lat, lng, region):
    return {"keys": keys, "name": name, "country": country, "iso": iso,
            "lat": lat, "lng": lng, "region": region}


_EXTRA_GEO = [
    _entry(["united states", "united states of america", "usa", "estados unidos", "eeuu", "etats-unis", "etats unis"], "United States", "United States", "US", 39.83, -98.58, "North America"),
    _entry(["new york", "nyc"], "New York", "United States", "US", 40.71, -74.01, "North America"),
    _entry(["los angeles"], "Los Angeles", "United States", "US", 34.05, -118.24, "North America"),
    _entry(["chicago"], "Chicago", "United States", "US", 41.88, -87.63, "North America"),
    _entry(["san francisco"], "San Francisco", "United States", "US", 37.77, -122.42, "North America"),
    _entry(["houston"], "Houston", "United States", "US", 29.76, -95.37, "North America"),
    _entry(["dallas"], "Dallas", "United States", "US", 32.78, -96.80, "North America"),
    _entry(["texas"], "Texas", "United States", "US", 31.97, -99.90, "North America"),
    _entry(["florida"], "Florida", "United States", "US", 27.66, -81.52, "North America"),
    _entry(["california"], "California", "United States", "US", 36.78, -119.42, "North America"),
    _entry(["canada"], "Canada", "Canada", "CA", 56.13, -106.35, "North America"),
    _entry(["guinea-bissau", "guinea bissau", "guinee-bissau"], "Guinea-Bissau", "Guinea-Bissau", "GW", 11.80, -15.18, "West Africa"),
    _entry(["equatorial guinea", "guinea ecuatorial", "guinee equatoriale"], "Equatorial Guinea", "Equatorial Guinea", "GQ", 1.65, 10.27, "Central Africa"),
    _entry(["papua new guinea", "papouasie-nouvelle-guinee"], "Papua New Guinea", "Papua New Guinea", "PG", -6.31, 143.96, "Oceania"),
    _entry(["republic of the congo", "congo-brazzaville"], "Republic of the Congo", "Republic of the Congo", "CG", -0.23, 15.83, "Central Africa"),
]

_GEO_ALIASES = {
    "ES": ["espana", "espagne"], "FR": ["francia"], "DE": ["alemania", "allemagne"],
    "GB": ["reino unido", "royaume-uni"], "CD": ["rdc", "republique democratique du congo", "republica democratica del congo"],
    "SD": ["soudan"], "SS": ["soudan du sud", "sudan del sur"],
    "UG": ["ouganda"], "TH": ["tailandia", "thailande"], "BR": ["brasil", "bresil"],
    "MX": ["mexique"], "PE": ["perou"], "CI": ["cote d’ivoire"],
}


def _public_location(entry):
    return {key: entry[key] for key in ("lat", "lng", "name", "country", "iso", "region")}


def _geo_mentions(text, disease_mentions):
    from scanner_v2 import GEO_DB
    entries = [dict(entry) for entry in GEO_DB] + _EXTRA_GEO
    hits = []
    for entry in entries:
        keys = list(entry["keys"])
        if entry["iso"] == "CD" and entry["name"] == "DRC":
            keys = ["democratic republic of the congo", "democratic republic of congo", "dr congo", "drc", "congo-kinshasa"]
        if entry["name"] == entry["country"] or entry["name"] in ("DRC", "UK"):
            keys.extend(_GEO_ALIASES.get(entry["iso"], []))
        # "democratic republic" alone is not a unique country; "car" is an
        # ordinary noun. Keep the unambiguous long names from the same rows.
        keys = [key for key in keys if key not in ("democratic republic", "car", "rio", "korea")]
        for key in keys:
            for match in re.finditer(_pattern(key), text):
                if any(match.start() < d[1] and d[0] < match.end() for d in disease_mentions):
                    continue
                hits.append((match.start(), match.end(), entry))
    chosen = []
    for hit in sorted(hits, key=lambda x: (-(x[1] - x[0]), x[0])):
        if not any(hit[0] < old[1] and old[0] < hit[1] for old in chosen):
            chosen.append(hit)
    return sorted(chosen, key=lambda x: x[0])


_ACTIVE = re.compile(
    r"\b(?:outbreaks?|clusters?|cases?|infections?|infected|patients?|diagnosed|hospitali[sz]ed|"
    r"tested positive|detected|confirmed|deaths?|fatalities|epidemic|sick|illness|vomiting|diarrhea|"
    r"brote[s]?|casos?|infectados?|fallecidos?|muertes?|epidemia|hospitalizados?|"
    r"foyers?|cas|infectes?|deces|epidemie|malades?|hospitalises?)\b")
_CONTEXT = re.compile(
    r"\b(?:vaccin\w*|immuni[sz]\w*|research|study|studies|trial|trials|laboratory study|"
    r"funding|funded|donat\w*|pledge\w*|grant|grants|training|workshop|conference|"
    r"summit|awareness|prevention|prevent|preparedness|simulation|exercise|risk assessment|"
    r"travel advice|travel warning|travel advisory|vaccine|could|might|hypothetical|if you|seek medical|"
    r"should|must increase|engagement|doit augmenter|devrait|deberia|"
    r"vacun\w*|ensayo|investigacion|prevencion|simulacro|preparacion|"
    r"recherche|etude|prevention|formation|exercice|sensibilisation)\b")
_HARD_CONTEXT = re.compile(
    r"\b(?:simulat\w*|hypothetical|scenario|scenarios|models?|modeling|modelling|"
    r"phylogenetic|lessons learned|retrospective|historical|history of|"
    r"simulacro|simulacion|hipotetico|retrospectiv\w*)\b")
_RESOLVED = re.compile(
    r"\b(?:outbreak (?:is |was |has been )?(?:over|ended|closed)|"
    r"end of (?:the )?(?:\w+ )?outbreak|(?:declares?|declared|declaration of) (?:the )?end|"
    r"(?:outbreak|epidemic) (?:declared )?over|eliminated|eradicated|"
    r"(?:outbreak|epidemic).{0,70}\b(?:has ended|is over|declared over)|"
    r"(?:certified|declared) (?:\w+[- ]?)*free|brote (?:terminado|finalizado)|"
    r"fin (?:del|de la) brote|fin de (?:l['’])?epidemie|epidemie terminee)\b")
_NEGATED = re.compile(
    r"\b(?:no evidence of|ruled out|rules out|tested negative|tests negative|false (?:reports?|claims?)|"
    r"not (?:an? )?(?:\w+ )?outbreak|sin casos|ningun caso|aucun cas|pas de cas|"
    r"no se (?:han |ha )?(?:confirmado|reportado|registrado) casos|descartad[oa]s?|ecarte[es]?)\b|"
    r"\b(?:no|zero|0)\s+(?:(?:new|confirmed|verified|suspected|reported|additional|human|locally acquired)\s+)*"
    r"(?:disease\s+)?(?:cases?|infections?|outbreaks?)\b|"
    r"\bno disease\b(?!\s+(?:deaths?|fatalities|mortality))")
_CURRENT_ZERO = re.compile(
    r"\b(?:last|past|latest|current|most recent)\s+(?:\d+[\s-]+)?(?:days?|weeks?|months?|reporting period)"
    r"(?:\s+(?:window|period))?\s*[:,-]?\s*(?:(?:shows?|records?|reports?)\s+)?"
    r"(?:0|zero|no)\s+(?:(?:new|verified|confirmed|reported)\s+)*cases?\b|"
    r"\b(?:0|zero|no)\s+(?:(?:new|verified|confirmed|reported)\s+)*cases?"
    r"\s+(?:in|during|over)\s+(?:the\s+)?(?:last|past|current)\s+(?:\d+\s+)?(?:days?|weeks?|months?)\b")


def _traveler(text):
    # Travel advice, outbreak declarations and the word "traveler" alone do
    # not establish that a person became ill in connection with travel.
    illness = re.search(r"\b(?:sick|ill|fever|infected|diagnosed|hospitali[sz]ed|tested positive|"
                        r"vomiting|diarrhea|enfermo|fiebre|diagnosticado|malade|fievre|infecte)\b", text)
    if not illness:
        return False
    if re.search(r"\b(?:travel advice|travel warning|travel advisory|should|could|might|"
                 r"if you|in case|seek medical|prevent|vaccinat)\b", text):
        return False
    return bool(re.search(
        r"\b(?:returned|returning|came back|got back|back from|arrived from|"
        r"after (?:my |our |a |the )?(?:trip|travel|vacation|holiday|visit)|"
        r"travell?ers?|tourists?|passengers?|regres[eo]|volvi|tras (?:un |el )?viaje|"
        r"voyageurs?|touristes?|retour de)\b", text))


def _clauses(text):
    # Do not split a thousands separator. A comma introducing a new disease
    # or a contrast can separate two different assertions about outbreaks.
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    parts = re.split(r"[;\n]+|[.!?](?:\s+|$)|\s+(?:but|however|whereas|pero|mais)\s+", text)
    out = []
    for part in parts:
        comma_parts = re.split(r",\s*", part)
        if len(comma_parts) > 1 and sum(bool(_disease_mentions(_norm(p))) for p in comma_parts) > 1:
            out.extend(comma_parts)
        else:
            out.append(part)
    return [part.strip(" ,:-–—") for part in out if part.strip(" ,:-–—")]


def _canonical_names(mentions):
    names = list(dict.fromkeys(mention[2] for mention in mentions))
    subtypes = [name for name in names if re.fullmatch(r"h\d+n\d+", name)]
    if subtypes and "avian flu" in names:
        names.remove("avian flu")
    if "sudan virus" in names and "ebola" in names:
        names.remove("ebola")
    # A symptom accompanying a named infection is not a second event.
    if len(names) > 1:
        names = [name for name in names if name not in ("fever", "diarrhea")]
    return names


def _status(text, source, reference_year):
    if _RESOLVED.search(text):
        return "resolved", "explicit_end_of_event"
    disease_masked = text
    for start, end, _name, _term in reversed(_disease_mentions(text)):
        disease_masked = disease_masked[:start] + "disease" + disease_masked[end:]
    if _NEGATED.search(disease_masked):
        # "100 cases, no new cases" still describes an event; do not infer
        # ongoing transmission. Mixed timing requires a person's review.
        return "negated", "explicit_negation"
    if _HARD_CONTEXT.search(text):
        return "context", "historical_research_or_simulation"
    years = [int(year) for year in re.findall(r"\b((?:19|20)\d{2})\b", text)]
    # Explicitly retrospective years do not become current because an article
    # was reposted today. Current words prevent treating comparisons as old.
    if years and max(years) < reference_year and not re.search(
            r"\b(?:now|currently|today|ongoing|this year|new (?:disease )?cases|latest|continues?)\b", disease_masked):
        return "context", "historical_year_reference"
    active = _ACTIVE.search(text)
    context = _CONTEXT.search(text)
    if context:
        # Response articles can still name a concrete current event. Merely
        # saying "outbreak preparedness" or "vaccine trial" does not qualify.
        explicit = re.search(r"\b(?:ongoing|new|confirmed|reports?|reported|declares?|declared|"
                             r"detected|surge|rising|spreading)\b.{0,70}\b(?:outbreak|cases?|infections?)\b|"
                             r"\b\d+\s+(?:new |confirmed |suspected )?(?:cases?|infections?|casos?|cas)\b", text)
        if not explicit:
            return "context", "background_prevention_or_research"
    if active or _traveler(text):
        return "active", "explicit_event_language"
    if source == "who":
        return "uncertain", "official_outbreak_notice_without_event_detail"
    return "uncertain", "no_explicit_current_event"


def _choose_location(hits, text):
    if not hits:
        return None, "location_not_resolved"
    # Exclude countries named solely as publisher/funder or as a prevention
    # comparison. Event place cues take priority over incidental mentions.
    event_hits = []
    eligible_hits = []
    for hit in hits:
        before = text[max(0, hit[0] - 45):hit[0]]
        after = text[hit[1]:hit[1] + 50]
        incidental = bool(re.search(r"\b(?:funded by|funding from|donation from|donated by|"
                                    r"supported by|based in|published in|publisher in)\s*$", before))
        incidental |= bool(re.match(r"\s+(?:funds?|donates?|pledges?|"
                                    r"(?:funded|donated|pledged)(?!\s+by)|"
                                    r"researchers|scientists|charity|university|newspaper|news agency|"
                                    r"centers for disease control|centres for disease control|"
                                    r"doit augmenter|should increase|must increase)\b", after))
        if incidental:
            continue
        eligible_hits.append(hit)
        if re.search(r"\b(?:in|at|from|en|au|aux|a|de|du|and|or|y|et)\s+(?:the\s+)?$", before) or re.search(r"[-–—:]\s*$", before):
            event_hits.append(hit)
    chosen = event_hits or eligible_hits
    if not chosen:
        return None, "only_incidental_locations"
    isos = {hit[2]["iso"] for hit in chosen}
    if len(isos) > 1:
        return None, "multiple_event_countries"
    entries = {hit[2]["name"]: hit[2] for hit in chosen}
    country_entries = [entry for entry in entries.values()
                       if entry["name"] == entry["country"] or entry["name"] in ("DRC", "UK", "CAR")]
    cities = [entry for entry in entries.values() if entry not in country_entries]
    if len(cities) == 1:
        return _public_location(cities[0]), "event_location_match"
    if len(cities) > 1:
        # Do not pin an aggregate to an arbitrary city.
        if country_entries:
            return _public_location(country_entries[0]), "country_level_multiple_places"
        return None, "multiple_event_places"
    return _public_location(next(iter(entries.values()))), "event_location_match"


def geocode_text(text):
    """Resolve a text's place conservatively without requiring an event claim."""
    clean = _norm(_clean(text))
    return _choose_location(_geo_mentions(clean, _disease_mentions(clean)), clean)[0]


def analyze_text(text, source, published="", *, title=""):
    """Return a review candidate or an explicit conservative abstention.

    ``active`` means event language was found, not that an outbreak is true.
    ``review`` requires an attributable disease and location. Multiple distinct
    events, unresolved geography and purely contextual material stay ``context``.
    Supported Spanish/French terms are a small explicit dictionary, not general
    multilingual understanding. ``published`` is retained as evidence only;
    freshness and independent source corroboration belong to the caller.
    """
    source = str(source or "").lower()
    year_match = re.match(r"((?:19|20)\d{2})", str(published or ""))
    reference_year = int(year_match[1]) if year_match else datetime.now(timezone.utc).year
    clean = _clean(text)
    clean_title = _clean(title)
    # A non-empty title remains a useful boundary. Duplicated titles do not
    # count as corroboration, and context in the body cannot overwrite it.
    if clean_title and clean.startswith(clean_title):
        clean = clean[len(clean_title):].strip()
    pieces = [(part, True) for part in _clauses(clean_title)] if clean_title else []
    pieces.extend((part, False) for part in _clauses(clean))
    records = []
    candidates = []
    for excerpt, from_title in pieces:
        norm = _norm(excerpt)
        mentions = _disease_mentions(norm)
        if not mentions:
            continue
        names = _canonical_names(mentions)
        hits = _geo_mentions(norm, mentions)
        for hit in hits:
            loc = _public_location(hit[2])
            if loc not in candidates:
                candidates.append(loc)
        status, status_reason = _status(norm, source, reference_year)
        location, location_reason = _choose_location(hits, norm)
        records.append({"excerpt": excerpt, "names": names, "status": status,
                        "location": location, "traveler": _traveler(norm) and status in ("active", "uncertain"),
                        "reasons": [status_reason, location_reason], "title": from_title})

    evidence = {"method": "deterministic_text_triage", "rule_version": RULE_VERSION,
                "source": source, "published": published or "", "selected_excerpt": "",
                "event_text": "",
                "disease_mentions": list(dict.fromkeys(name for record in records for name in record["names"])),
                "assertions": [{"excerpt": r["excerpt"], "diseases": r["names"],
                                "event_status": r["status"], "location_iso": r["location"]["iso"] if r["location"] else None}
                               for r in records],
                "limitations": ["Rule-based screening; no independent verification or calibrated probability.",
                                "Limited English, Spanish and French patterns; human review required."]}
    result = {"disease": None, "location": None, "event_status": "uncertain",
              "triage": "context", "is_traveler": False, "reasons": [],
              "evidence": evidence, "location_candidates": candidates}
    if not records:
        result["event_status"] = "context"
        result["location"] = geocode_text(clean_title or clean)
        result["location_candidates"] = [result["location"]] if result["location"] else []
        result["reasons"] = ["no_recognized_disease"]
        return result

    # An explicit negative or closure headline takes precedence over background
    # descriptions of earlier cases in the body of the same article.
    title_context = [r for r in records if r["title"] and r["status"] in ("resolved", "negated", "context")]
    active = [r for r in records if r["status"] == "active"]
    if title_context and not any(r["title"] and r["status"] == "active" for r in records):
        pool = title_context
    elif active:
        pool = active
    else:
        pool = [r for r in records if r["title"]] or records

    # Distinct event pairs in a roundup are not safely reducible to one map pin.
    pairs = {(tuple(r["names"]), r["location"]["iso"] if r["location"] else None) for r in pool}
    if len(pairs) > 1:
        result["reasons"] = ["multiple_distinct_event_assertions"]
        result["event_status"] = "uncertain"
        return result
    record = next((r for r in pool if r["title"]), pool[0])
    result.update(event_status=record["status"], location=record["location"],
                  is_traveler=record["traveler"], reasons=list(record["reasons"]))
    evidence["selected_excerpt"] = record["excerpt"]
    evidence["event_text"] = record["excerpt"]
    if len(record["names"]) != 1:
        result["event_status"] = "uncertain"
        result["reasons"].append("multiple_diseases_without_unique_event")
        return result
    result["disease"] = _disease_info(record["names"][0])
    if any(reason in result["reasons"] for reason in ("multiple_event_countries", "multiple_event_places")):
        result["event_status"] = "uncertain"
    if not result["location"] and re.search(r"\bcongo\b", _norm(record["excerpt"])) and not any(
            "congo" in mention[2] for mention in _disease_mentions(_norm(record["excerpt"]))):
        result["event_status"] = "uncertain"
        result["reasons"].append("ambiguous_congo_name")
    zero_clauses = [part for part, _is_title in pieces if _CURRENT_ZERO.search(_norm(part))]
    all_names = {name for item in records for name in item["names"]}
    all_countries = {item["location"]["iso"] for item in records if item["location"]}
    if zero_clauses and len(all_names) == 1 and len(all_countries) <= 1:
        result["event_status"] = "negated"
        result["is_traveler"] = False
        result["reasons"].append("explicit_zero_current_reporting_window")
        evidence["current_window_excerpt"] = zero_clauses[0]
    if result["location"] and (record["status"] == "active" or
                               (record["status"] == "uncertain" and source == "who")):
        if result["event_status"] in ("active", "uncertain"):
            result["triage"] = "review"
    return result
