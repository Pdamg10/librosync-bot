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

    parts = re.split(r"\s*[-–—]\s*", clean_name)
    title = clean_name.replace("_", " ").title()
    author = "Desconocido"
    if len(parts) >= 2:
        title = parts[0].strip().replace("_", " ").title()
        author = parts[1].strip().replace("_", " ").title()

    # Si se conoce el tema actual donde ya estaba el mensaje, mantenerlo
    if current_topic_hint:
        genre = current_topic_hint
        return {
            "title": title,
            "author": author,
            "genre": genre,
            "emoji": get_genre_emoji(genre)
        }

    # Helper local para comparar texto normalizado
    import unicodedata
    def _slug(s: str) -> str:
        nfkd = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
        return re.sub(r'[^a-zA-Z0-9]', '', nfkd).lower()

    file_slug = _slug(filename)
    genre = "General"

    if existing_topics:
        # 1. Comprobar si el nombre de algún topic existente coincide con el archivo
        for ex_t in existing_topics:
            ex_slug = _slug(ex_t)
            if ex_slug and (ex_slug in file_slug or file_slug in ex_slug):
                genre = ex_t
                break

        # 2. Si sigue en General, comprobar palabras clave temáticas comunes
        if genre == "General":
            genre_keywords = {
                "dark romance": ["dark", "lujuria", "mafia", "adeline", "pecado", "sombras", "enemiesto"],
                "romance": ["amor", "love", "romance", "corazon", "pasion", "beso", "boda"],
                "fantasia": ["fantasy", "fantasia", "magia", "dragon", "reino", "hada", "viento", "corte"],
                "ciencia ficcion": ["scifi", "ciencia", "ficcion", "espacio", "galaxy", "futuro", "robot"],
                "thriller": ["misterio", "asesin", "crimen", "detective", "sangre", "muerte", "suspens"],
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
                    if genre != "General":
                        break

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
    Maneja reintentos con backoff para evitar saturación de cuota HTTP 429.
    """
    if not settings.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY no configurada. Usando parser heurístico.")
        return fallback_parse_filename(filename, existing_topics=existing_topics, current_topic_hint=current_topic_hint)

    topics_list = existing_topics or []
    topics_formatted = json.dumps(topics_list, ensure_ascii=False) if topics_list else "Ninguno aún"
    hint_str = f"\n- Contexto actual: Este archivo se encuentra actualmente dentro del tema '{current_topic_hint}'." if current_topic_hint else ""

    prompt = f"""
Eres el bibliotecario y clasificador experto de una biblioteca digital en Telegram.
Analiza este libro que acaba de ser subido:
- Nombre del archivo: "{filename}"
- Texto/Comentario del usuario: "{caption or 'Ninguno'}"{hint_str}

Lista de Temas (Topics) YA CREADOS en el grupo de Telegram:
{topics_formatted}

INSTRUCCIONES DE CLASIFICACIÓN:
1. Identifica el Título real del libro. Elimina numeraciones iniciales de saga (ej: "01 - ", "[Vol 1] "), extensiones o tags de escaneo.
2. Identifica el Autor real del libro. Si no se puede deducir del nombre, pon "Desconocido".
3. Determina el Género literario exacto:
   - PRIORIDAD MÁXIMA: Si el libro encaja o es afín a alguno de los "Temas YA CREADOS" en la lista, DEBES elegir EXACTAMENTE ese mismo nombre (respetando mayúsculas y espacios).
   - Si no encaja en ninguno de los existentes, propón un nombre de género canónico, elegante y corto (ej: "Dark Romance", "Ciencia Ficción", "Fantasía", "Thriller", "Autoayuda", "Terror").
   - NUNCA uses nombres genéricos vagos si puedes ser preciso (ej: prefiere "Dark Romance" o "Romance Histórico" si aplica).
4. Elige un Emoji representativo del género (ej: 🖤 para Dark Romance, 🚀 para Ciencia Ficción, 🧙 para Fantasía, 🔪 para Thriller, 💖 para Romance, 📚 para General).

Devuelve EXCLUSIVAMENTE un objeto JSON válido con este esquema:
{{
  "title": "Título limpio",
  "author": "Nombre del autor",
  "genre": "Género o Tema asignado",
  "emoji": "Emoji único representativo"
}}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "thinkingConfig": {
                "thinkingBudget": 512
            }
        }
    }

    max_retries = 2
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    candidate_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(candidate_text)
                    genre = parsed.get("genre", current_topic_hint or "General")
                    emoji = get_genre_emoji(genre, parsed.get("emoji"))
                    logger.info(f"Gemini clasificó exitosamente: {parsed}")
                    return {
                        "title": parsed.get("title", filename),
                        "author": parsed.get("author", "Desconocido"),
                        "genre": genre,
                        "emoji": emoji
                    }
                elif response.status_code == 429 and attempt < max_retries - 1:
                    logger.warning(f"Rate limit 429 en Gemini API. Esperando 2.5s antes de reintentar (intento {attempt + 1}/{max_retries})...")
                    await asyncio.sleep(2.5)
                    continue
                else:
                    logger.warning(f"Error en Gemini API ({response.status_code}): {response.text}")
                    break
        except Exception as e:
            logger.error(f"Excepción al consultar Gemini API: {e}")
            break

    # Fallback si la IA falla
    return fallback_parse_filename(
        filename=filename,
        existing_topics=existing_topics,
        current_topic_hint=current_topic_hint
    )
