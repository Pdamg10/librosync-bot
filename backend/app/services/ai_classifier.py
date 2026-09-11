import logging
import json
import re
import asyncio
from typing import Optional, List, Dict, Any
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GENRE_EMOJIS: Dict[str, str] = {
    "darkromance": "🖤",
    "romance": "💖",
    "fantasia": "🧙",
    "cienciaficcion": "🚀",
    "scifi": "🚀",
    "thriller": "🔪",
    "suspensopsicologico": "🔪",
    "thrillerysuspensopsicologico": "🔪",
    "terror": "👻",
    "horror": "💀",
    "misterio": "🕵️",
    "novelanegra": "🔍",
    "policial": "🚓",
    "autoayuda": "🌱",
    "desarrollopersonal": "🌱",
    "autoayudaydesarrollopersonal": "🌱",
    "manga": "🏯",
    "manhwa": "🏯",
    "manhua": "🏯",
    "mangamanhwamanhua": "🏯",
    "dystopia": "🌪️",
    "distopia": "🌪️",
    "historia": "📜",
    "novelahistorica": "🏛️",
    "poesia": "🪶",
    "filosofia": "🏛️",
    "aventura": "🗺️",
    "general": "📚",
    "erotica": "🔥",
    "novela": "📖",
    "comedia": "🎭",
    "drama": "🎭",
    "juvenil": "🎒",
    "youngadult": "🎒",
    "biografia": "👤",
}

def get_genre_emoji(genre: str, suggested_emoji: Optional[str] = None) -> str:
    """Devuelve un emoji apropiado para el género."""
    if suggested_emoji and 1 <= len(suggested_emoji.strip()) <= 4:
        return suggested_emoji.strip()
    
    # Normalizar slug básico
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', genre).encode('ASCII', 'ignore').decode('utf-8')
    slug = re.sub(r'[^a-zA-Z0-9]', '', nfkd).lower()

    if slug in GENRE_EMOJIS:
        return GENRE_EMOJIS[slug]
    for key, emo in GENRE_EMOJIS.items():
        if key in slug or slug in key:
            return emo
    return "📖"

def fallback_parse_filename(
    filename: str,
    existing_topics: Optional[List[str]] = None,
    current_topic_hint: Optional[str] = None,
    internal_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """Extracción heurística avanzada cuando la IA no está disponible o por rate-limit."""
    if internal_metadata and internal_metadata.get("internal_title"):
        title = internal_metadata["internal_title"].strip().title()
        author = (internal_metadata.get("internal_author") or "Desconocido").strip().title()
        genre = internal_metadata.get("internal_genre") or current_topic_hint or "General"
        return {
            "title": title,
            "author": author,
            "genre": genre,
            "emoji": get_genre_emoji(genre)
        }

    name_no_ext = filename.rsplit(".", 1)[0]
    # Limpiar prefijos numéricos típicos (ej: "01 - ", "[01] ")
    clean_name = re.sub(r"^(\d+[\s\-_.]+|\[\d+\]\s*|\(\d+\)\s*)", "", name_no_ext).strip()

    title = clean_name.replace("_", " ").title()
    author = "Desconocido"

    # 1. Separación por delimitadores explícitos: " - ", " – ", " — ", " by ", " por "
    parts = re.split(r"\s*(?:[-–—]|(?:\s+by\s+)|\s+por\s+)\s*", clean_name, flags=re.IGNORECASE)
    if len(parts) >= 2:
        title = parts[0].strip().replace("_", " ").title()
        author = parts[1].strip().replace("_", " ").title()
    else:
        # 2. Heurística posicional si no hay guiones (ej: "La Tregua Mario Benedetti")
        words = clean_name.split()
        if len(words) >= 4:
            title = " ".join(words[:-2]).strip().replace("_", " ").title()
            author = " ".join(words[-2:]).strip().replace("_", " ").title()
        elif len(words) == 3:
            title = " ".join(words[:2]).strip().replace("_", " ").title()
            author = words[2].strip().replace("_", " ").title()

    # Helper local para comparar texto normalizado
    import unicodedata
    def _slug(s: str) -> str:
        nfkd = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
        return re.sub(r'[^a-zA-Z0-9]', '', nfkd).lower()

    file_slug = _slug(name_no_ext)
    genre = None

    # Detectar género por palabras clave
    if existing_topics:
        GENRE_KEYWORDS = {
            "Dark Romance": ["darkromance", "dark", "lujuria", "mafia", "pecado", "cautiva", "moran"],
            "Romance": ["romance", "amor", "corazon", "enamorar", "novios", "boda", "pasion", "beso"],
            "Fantasía": ["fantasia", "fantasy", "magia", "dragon", "hechicero", "reino", "hada", "elfo", "potter", "mago", "magico", "hechizo"],
            "Ciencia Ficción": ["cienciaficcion", "scifi", "espacio", "galaxia", "robot", "alien", "marte"],
            "Thriller Y Suspenso Psicológico": ["thriller", "suspenso", "psicologico", "crimen", "misterio", "asesino"],
            "Novela Negra": ["novelanegra", "detective", "policial", "investigacion", "noir"],
            "Autoayuda Y Desarrollo Personal": ["autoayuda", "habitos", "ansiedad", "mente", "superacion", "finanzas", "exito"],
            "Dystopia": ["dystopia", "distopia", "apocalipsis", "tributo", "juegos", "rebelion"],
            "Manga/Manhwa/Manhua": ["manga", "manhwa", "manhua", "capitulo", "tomo", "vol"]
        }

        # 1. Comprobar si alguna palabra clave coincide con los temas ya creados en Telegram
        for ex_t in existing_topics:
            for canon_genre, keywords in GENRE_KEYWORDS.items():
                if _slug(ex_t) == _slug(canon_genre) or _slug(canon_genre) in _slug(ex_t):
                    for kw in keywords:
                        if kw in file_slug:
                            genre = ex_t
                            break
                if genre:
                    break
            if genre:
                break

        # 1.1 Si no hubo match por tema existente, buscar en todas las palabras clave y mapear al más similar
        if not genre:
            for canon_genre, keywords in GENRE_KEYWORDS.items():
                found_kw = False
                for kw in keywords:
                    if kw in file_slug:
                        target_kw_slug = _slug(canon_genre)
                        found_kw = True
                        break
                if not found_kw:
                    continue
                # Si encontró un género canónico, ver si existe un tema parecido en el grupo
                for ex_t in existing_topics:
                    if target_kw_slug in _slug(ex_t) or _slug(ex_t) in target_kw_slug:
                        genre = ex_t
                        break
                if genre:
                    break

        # 2. Comprobar si el nombre literal de algún topic existente coincide con el archivo
        if not genre:
            for ex_t in existing_topics:
                ex_slug = _slug(ex_t)
                if ex_slug and (ex_slug in file_slug or file_slug in ex_slug):
                    genre = ex_t
                    break

    # 3. Si no coincidió con ninguna palabra clave, usar current_topic_hint si existe o General
    if not genre:
        genre = current_topic_hint or "General"

    publication_year = "Desconocido"
    if internal_metadata and internal_metadata.get("internal_date"):
        m_y = re.search(r"\b(1[89]\d{2}|20\d{2})\b", str(internal_metadata["internal_date"]))
        if m_y:
            publication_year = m_y.group(1)
    if publication_year == "Desconocido":
        m_fn = re.search(r"\b(1[89]\d{2}|20\d{2})\b", filename)
        if m_fn:
            publication_year = m_fn.group(1)

    KNOWN_YEARS = {
        "cien anos de soledad": "1967",
        "el gran gatsby": "1925",
        "la tregua": "1960",
        "posdata te amo": "2004",
        "el principito": "1943",
        "1984": "1949",
        "dune": "1965",
        "harry potter": "1997",
    }
    slug_check = _slug(title)
    for k_title, yr in KNOWN_YEARS.items():
        if _slug(k_title) in slug_check or slug_check in _slug(k_title):
            publication_year = yr
            break

    # Heurística para detección de sagas/series por numeración en el título o archivo
    is_series = False
    series_name = None
    series_type = "Autoconclusivo"
    series_order = None
    series_total = None
    has_sequel = False
    previous_book = None
    next_book = None

    m_series = re.search(r"^(.*?)(?:\s*(?:#|vol\.?|volumen|tomo|libro|parte)?\s*(\d+|I|II|III|IV|V|VI|VII))\b", title, re.IGNORECASE)
    if m_series and len(m_series.group(1).strip()) > 2:
        potential_sname = m_series.group(1).strip().rstrip(".:-").strip()
        num_raw = m_series.group(2).upper()
        roman_map = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}
        order_num = roman_map.get(num_raw) or (int(num_raw) if num_raw.isdigit() else None)
        if order_num:
            is_series = True
            series_name = potential_sname
            series_type = "Saga" if order_num > 3 else "Trilogía"
            series_order = order_num
            has_sequel = True
            if order_num > 1:
                previous_book = f"{potential_sname} {order_num - 1}"
            next_book = f"{potential_sname} {order_num + 1}"

    return {
        "title": title,
        "author": author,
        "genre": genre,
        "publication_year": publication_year,
        "emoji": get_genre_emoji(genre),
        "is_series": is_series,
        "series_name": series_name,
        "series_type": series_type,
        "series_order": series_order,
        "series_total": series_total,
        "has_sequel": has_sequel,
        "previous_book": previous_book,
        "next_book": next_book
    }

async def classify_book_with_gemini(
    filename: str,
    caption: Optional[str] = None,
    existing_topics: Optional[List[str]] = None,
    current_topic_hint: Optional[str] = None,
    internal_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Clasifica un libro y extrae metadata limpia (título, autor, género, año de publicación original,
    y datos de saga/trilogía, libros predecesores, continuaciones y entregas) usando Google Gemini.
    Tiene en cuenta los temas ya existentes en el grupo para no duplicar.
    Detecta activamente autores tanto en el nombre del archivo como por cultura literaria.
    Si el nombre es genérico (ej: 'Capitulo 1.pdf'), utiliza los metadatos internos y portada.
    Implementa una cascada multi-modelo para evitar cuellos de botella por cuotas (429/503).
    """
    if not settings.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY no configurada. Usando parser heurístico.")
        return fallback_parse_filename(
            filename,
            existing_topics=existing_topics,
            current_topic_hint=current_topic_hint,
            internal_metadata=internal_metadata
        )

    topics_list = existing_topics or []
    topics_formatted = json.dumps(topics_list, ensure_ascii=False) if topics_list else "Ninguno aún"
    hint_str = f"\n- Ubicación donde fue encontrado el mensaje: Tema '{current_topic_hint}'." if current_topic_hint else ""

    internal_block = ""
    if internal_metadata:
        parts = []
        if internal_metadata.get("internal_title"):
            parts.append(f"- Título en metadatos internos del archivo: \"{internal_metadata['internal_title']}\"")
        if internal_metadata.get("internal_author"):
            parts.append(f"- Autor en metadatos internos del archivo: \"{internal_metadata['internal_author']}\"")
        if internal_metadata.get("internal_date"):
            parts.append(f"- Fecha/Año en metadatos internos del archivo: \"{internal_metadata['internal_date']}\"")
        if internal_metadata.get("text_snippet"):
            parts.append(f"- Texto extraído de las primeras páginas (portada/créditos):\n\"\"\"\n{internal_metadata['text_snippet']}\n\"\"\"")
        if parts:
            internal_block = "\nINFORMACIÓN EXTRAÍDA DEL INTERIOR DEL ARCHIVO (METADATOS / PORTADA):\n" + "\n".join(parts) + "\n"

    prompt = f"""
Eres el bibliotecario y clasificador experto de una biblioteca digital en Telegram.
Analiza este libro que acaba de ser subido:
- Nombre del archivo: "{filename}"
- Texto/Comentario del usuario: "{caption or 'Ninguno'}"{hint_str}
{internal_block}
Lista de Temas (Topics) YA CREADOS en el grupo de Telegram:
{topics_formatted}

INSTRUCCIONES DE CLASIFICACIÓN Y EXTRACCIÓN:
1. Identifica el TÍTULO real del libro:
   - Limpia numeraciones iniciales de saga (ej: "01 - ", "[Vol 1] "), extensiones o tags de escaneo.
   - Si el archivo tiene un nombre genérico (ej: "Capitulo 1.pdf", "12345.epub", "scan.pdf") o contiene solo números y letras, DEBES utilizar la 'INFORMACIÓN EXTRAÍDA DEL INTERIOR DEL ARCHIVO' (título interno o portada) para identificar el título real de la obra.
   - Si el archivo contiene el nombre del autor mezclado con el título (ej: "La Tregua Mario Benedetti" o "El Gran Gatsby Francis Scott Fitzgerald"), SEPARA limpiamente el título del autor. El título es solo el nombre de la obra.
2. Identifica el AUTOR real del libro:
   - Sé muy exhaustivo. Si el nombre del autor aparece en el archivo o en el texto interno, extráelo limpiamente.
   - Si reconoces la obra literaria (clásica o contemporánea), asigna el autor correspondiente según tu conocimiento cultural de la obra.
   - NUNCA pongas "Desconocido" si el autor es deducible del texto o si es una obra conocida.
3. Determina el Género literario exacto del libro de forma OBJETIVA:
   - ATENCIÓN - DETECCIÓN DE TEMA ERRÓNEO: Los usuarios con frecuencia suben libros en el tema equivocado (por ejemplo, suben un libro de 'Fantasía' o 'Thriller' en el tema de 'Romance'). NO te limites ni asumas que el tema donde fue encontrado es el correcto.
   - Si el libro pertenece a otro de los 'Temas YA CREADOS' en la lista (por ejemplo, es Fantasía y existe el tema Fantasía), DEBES elegir EXACTAMENTE ese nombre para que el bot pueda reubicarlo automáticamente.
   - Si no encaja en ningún tema existente, propón un nombre de género canónico, elegante y conciso (ej: "Dark Romance", "Ciencia Ficción", "Fantasía", "Thriller", "Autoayuda", "Terror") para que el bot cree un nuevo tema para el libro.
   - NUNCA uses nombres genéricos vagos si puedes ser preciso.
4. Identifica el AÑO DE SALIDA / PUBLICACIÓN original del libro:
   - Importante: Buscamos el año en que la obra o novela fue publicada por primera vez (ej: "1967", "1925", "2004", "2023").
   - Si la obra es una publicación conocida, usa el año histórico de su primera edición.
   - Si aparece en los metadatos internos o en los créditos/copyright de la portada, extráelo.
   - Si no se puede determinar de ninguna manera, devuelve "Desconocido".
5. Elige un Emoji representativo del género (ej: 🖤 para Dark Romance, 🚀 para Ciencia Ficción, 🧙 para Fantasía, 🔪 para Thriller, 💖 para Romance, 📚 para General).
6. Determina si el libro pertenece a una SAGA, TRILOGÍA, BILOGÍA, TETRALOGÍA o SERIE literaria:
   - "is_series": true si es parte de una saga o serie, false si es una obra autoconclusiva/independiente.
   - "series_name": Nombre comúnmente conocido de la saga o serie (ej: "Los Royals", "Bad Ash", "Perfectly Imperfect", "Harry Potter", "Los Juegos del Hambre", "Made Men"). Si es autoconclusivo, devuelve null.
   - "series_type": "Saga" | "Trilogía" | "Bilogía" | "Tetralogía" | "Serie" | "Autoconclusivo".
   - "series_order": Número entero del orden de este libro en la saga (ej: 1 para el primer libro, 2 para el segundo, etc.). Si es autoconclusivo o libro complementario sin orden fijo, devuelve null o el número correspondiente.
   - "series_total": Número total de libros que componen la serie si se conoce (ej: 3 para una trilogía, 7 para Harry Potter). Si no se conoce o está abierta, devuelve null.
   - "has_sequel": true si este libro tiene una continuación o entrega siguiente en la serie. false si es el último libro de la serie o si es autoconclusivo.
   - "previous_book": Título del libro inmediatamente anterior en la saga/serie (ej: "Harry Potter y la piedra filosofal"). Si es el primer libro o es autoconclusivo, devuelve null.
   - "next_book": Título del libro inmediatamente siguiente / continuación en la saga/serie (ej: "Harry Potter y el prisionero de Azkaban"). Si es el último libro o es autoconclusivo, devuelve null.

Devuelve EXCLUSIVAMENTE un objeto JSON válido con este esquema:
{{
  "title": "Título limpio",
  "author": "Nombre del autor",
  "genre": "Género o Tema asignado",
  "publication_year": "Año de publicación original (ej: '1967' o 'Desconocido')",
  "emoji": "Emoji único representativo",
  "is_series": true,
  "series_name": "Nombre de la saga o null",
  "series_type": "Saga | Trilogía | Bilogía | Tetralogía | Serie | Autoconclusivo",
  "series_order": 1,
  "series_total": 3,
  "has_sequel": true,
  "previous_book": "Título libro anterior o null",
  "next_book": "Título libro siguiente o null"
}}
"""

    # Cadena de modelos de respaldo para garantizar alta disponibilidad
    models_to_try = [
        settings.GEMINI_MODEL,
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash"
    ]
    seen_models = set()
    model_chain = [m for m in models_to_try if not (m in seen_models or seen_models.add(m))]

    for model in model_chain:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1
            }
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    candidate_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(candidate_text)
                    genre = parsed.get("genre", current_topic_hint or "General")
                    emoji = get_genre_emoji(genre, parsed.get("emoji"))
                    author = parsed.get("author", "Desconocido")
                    pub_yr = parsed.get("publication_year") or "Desconocido"
                    if pub_yr == "Desconocido" and internal_metadata and internal_metadata.get("internal_date"):
                        pub_yr = internal_metadata["internal_date"]

                    is_ser = bool(parsed.get("is_series", False))
                    s_name = parsed.get("series_name") if is_ser else None
                    s_type = parsed.get("series_type") or ("Saga" if is_ser else "Autoconclusivo")
                    s_order = parsed.get("series_order")
                    s_total = parsed.get("series_total")
                    has_seq = bool(parsed.get("has_sequel", False))
                    prev_b = parsed.get("previous_book")
                    next_b = parsed.get("next_book")

                    logger.info(f"Gemini ({model}) clasificó exitosamente: {parsed}")
                    return {
                        "title": parsed.get("title", filename),
                        "author": author if author and author.strip() else "Desconocido",
                        "genre": genre,
                        "publication_year": str(pub_yr).strip(),
                        "emoji": emoji,
                        "is_series": is_ser,
                        "series_name": s_name,
                        "series_type": s_type,
                        "series_order": s_order,
                        "series_total": s_total,
                        "has_sequel": has_seq,
                        "previous_book": prev_b,
                        "next_book": next_b
                    }
                elif response.status_code in (429, 503):
                    logger.warning(f"Modelo {model} ocupado/limitado ({response.status_code}). Probando siguiente modelo de la cadena...")
                    continue
                else:
                    logger.warning(f"Error en Gemini {model} ({response.status_code}): {response.text}")
                    continue
        except Exception as e:
            logger.warning(f"Excepción al consultar modelo {model}: {e}. Probando siguiente modelo...")
            continue

    # Fallback si todos los modelos de IA fallan
    logger.warning("Todos los modelos de Gemini fallaron o agotaron cuota. Usando parser heurístico de respaldo.")
    return fallback_parse_filename(
        filename=filename,
        existing_topics=existing_topics,
        current_topic_hint=current_topic_hint,
        internal_metadata=internal_metadata
    )
