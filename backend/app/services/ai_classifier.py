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
    current_topic_hint: Optional[str] = None
) -> Dict[str, str]:
    """Extracción heurística avanzada cuando la IA no está disponible o por rate-limit."""
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

    file_slug = _slug(filename)
    genre = None

    if existing_topics:
        # 1. Palabras clave temáticas prioritarias para detectar si pertenece a otro género
        genre_keywords = {
            "dark romance": ["dark", "lujuria", "mafia", "adeline", "pecado", "sombras", "enemiesto"],
            "romance": ["amor", "love", "romance", "corazon", "pasion", "beso", "boda"],
            "fantasia": ["fantasy", "fantasia", "magia", "dragon", "reino", "hada", "viento", "corte", "potter", "anillos"],
            "ciencia ficcion": ["scifi", "ciencia", "ficcion", "espacio", "galaxy", "futuro", "robot"],
            "thriller": ["misterio", "asesin", "crimen", "detective", "sangre", "muerte", "suspens", "thriller"],
            "manga": ["manga", "manhwa", "manhua", "capitulo", "volumen"],
            "dystopia": ["distopia", "dystopia", "apocalip", "caos", "juegos del hambre"],
            "autoayuda": ["habitos", "autoayuda", "mente", "superacion", "exito", "finanzas"]
        }
        for kw_genre, kws in genre_keywords.items():
            if any(kw in file_slug for kw in kws):
                target_kw_slug = _slug(kw_genre)
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

    return {
        "title": title,
        "author": author,
        "genre": genre,
        "emoji": get_genre_emoji(genre)
    }

async def classify_book_with_gemini(
    filename: str,
    caption: Optional[str] = None,
    existing_topics: Optional[List[str]] = None,
    current_topic_hint: Optional[str] = None
) -> Dict[str, str]:
    """
    Clasifica un libro y extrae metadata limpia (título, autor, género) usando Google Gemini.
    Tiene en cuenta los temas ya existentes en el grupo para no duplicar.
    Detecta activamente autores tanto en el nombre del archivo como por cultura literaria.
    Implementa una cascada multi-modelo para evitar cuellos de botella por cuotas (429/503).
    """
    if not settings.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY no configurada. Usando parser heurístico.")
        return fallback_parse_filename(filename, existing_topics=existing_topics, current_topic_hint=current_topic_hint)

    topics_list = existing_topics or []
    topics_formatted = json.dumps(topics_list, ensure_ascii=False) if topics_list else "Ninguno aún"
    hint_str = f"\n- Ubicación donde fue encontrado el mensaje: Tema '{current_topic_hint}'." if current_topic_hint else ""

    prompt = f"""
Eres el bibliotecario y clasificador experto de una biblioteca digital en Telegram.
Analiza este libro que acaba de ser subido:
- Nombre del archivo: "{filename}"
- Texto/Comentario del usuario: "{caption or 'Ninguno'}"{hint_str}

Lista de Temas (Topics) YA CREADOS en el grupo de Telegram:
{topics_formatted}

INSTRUCCIONES DE CLASIFICACIÓN Y EXTRACCIÓN:
1. Identifica el TÍTULO real del libro:
   - Limpia numeraciones iniciales de saga (ej: "01 - ", "[Vol 1] "), extensiones o tags de escaneo.
   - Si el archivo contiene el nombre del autor mezclado con el título (ej: "La Tregua Mario Benedetti" o "El Gran Gatsby Francis Scott Fitzgerald"), SEPARA limpiamente el título del autor. El título es solo el nombre de la obra.
2. Identifica el AUTOR real del libro:
   - Sé muy exhaustivo. Si el nombre del autor aparece en el archivo (al final, al inicio, con o sin guión, ej: "Mario Benedetti", "Francis Scott Fitzgerald", "Eva Winners"), extráelo limpiamente.
   - Si reconoces la obra literaria (clásica o contemporánea), asigna el autor correspondiente según tu conocimiento cultural de la obra.
   - NUNCA pongas "Desconocido" si el autor es deducible del texto o si es una obra conocida.
3. Determina el Género literario exacto del libro de forma OBJETIVA:
   - ATENCIÓN - DETECCIÓN DE TEMA ERRÓNEO: Los usuarios con frecuencia suben libros en el tema equivocado (por ejemplo, suben un libro de 'Fantasía' o 'Thriller' en el tema de 'Romance'). NO te limites ni asumas que el tema donde fue encontrado es el correcto.
   - Si el libro pertenece a otro de los 'Temas YA CREADOS' en la lista (por ejemplo, es Fantasía y existe el tema Fantasía), DEBES elegir EXACTAMENTE ese nombre para que el bot pueda reubicarlo automáticamente.
   - Si no encaja en ningún tema existente, propón un nombre de género canónico, elegante y conciso (ej: "Dark Romance", "Ciencia Ficción", "Fantasía", "Thriller", "Autoayuda", "Terror") para que el bot cree un nuevo tema para el libro.
   - NUNCA uses nombres genéricos vagos si puedes ser preciso.
4. Elige un Emoji representativo del género (ej: 🖤 para Dark Romance, 🚀 para Ciencia Ficción, 🧙 para Fantasía, 🔪 para Thriller, 💖 para Romance, 📚 para General).

Devuelve EXCLUSIVAMENTE un objeto JSON válido con este esquema:
{{
  "title": "Título limpio",
  "author": "Nombre del autor",
  "genre": "Género o Tema asignado",
  "emoji": "Emoji único representativo"
}}
"""

    # Cadena de modelos de respaldo para garantizar alta disponibilidad
    models_to_try = [
        settings.GEMINI_MODEL,
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash"
    ]
    # Eliminar duplicados manteniendo orden
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
                    logger.info(f"Gemini ({model}) clasificó exitosamente: {parsed}")
                    return {
                        "title": parsed.get("title", filename),
                        "author": author if author and author.strip() else "Desconocido",
                        "genre": genre,
                        "emoji": emoji
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
        current_topic_hint=current_topic_hint
    )
