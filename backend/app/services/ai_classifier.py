import logging
import json
import re
from typing import Optional, List, Dict, Any
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

def fallback_parse_filename(filename: str) -> Dict[str, str]:
    """Extracción heurística básica cuando la IA no está disponible."""
    name_no_ext = filename.rsplit(".", 1)[0]
    # Limpiar prefijos numéricos típicos (ej: "01 - ", "[01] ")
    clean_name = re.sub(r"^(\d+[\s\-_.]+|\[\d+\]\s*|\(\d+\)\s*)", "", name_no_ext).strip()

    parts = re.split(r"\s*[-–—]\s*", clean_name)
    if len(parts) >= 2:
        return {
            "title": parts[0].strip().replace("_", " ").title(),
            "author": parts[1].strip().replace("_", " ").title(),
            "genre": "General"
        }
    return {
        "title": clean_name.replace("_", " ").title(),
        "author": "Desconocido",
        "genre": "General"
    }

async def classify_book_with_gemini(
    filename: str,
    caption: Optional[str] = None,
    existing_topics: Optional[List[str]] = None
) -> Dict[str, str]:
    """
    Clasifica un libro y extrae metadata limpia (título, autor, género) usando Google Gemini.
    Tiene en cuenta los temas ya existentes en el grupo para no duplicar.
    """
    if not settings.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY no configurada. Usando parser heurístico.")
        return fallback_parse_filename(filename)

    topics_list = existing_topics or []
    topics_formatted = json.dumps(topics_list, ensure_ascii=False) if topics_list else "Ninguno aún"

    prompt = f"""
Eres el bibliotecario y clasificador experto de una biblioteca digital en Telegram.
Analiza este libro que acaba de ser subido:
- Nombre del archivo: "{filename}"
- Texto/Comentario del usuario: "{caption or 'Ninguno'}"

Lista de Temas (Topics) YA CREADOS en el grupo de Telegram:
{topics_formatted}

INSTRUCCIONES DE CLASIFICACIÓN:
1. Identifica el Título real del libro. Elimina numeraciones iniciales de saga (ej: "01 - ", "[Vol 1] "), extensiones o tags de escaneo.
2. Identifica el Autor real del libro. Si no se puede deducir del nombre, pon "Desconocido".
3. Determina el Género literario exacto:
   - PRIORIDAD MÁXIMA: Si el libro encaja o es afín a alguno de los "Temas YA CREADOS" en la lista, DEBES elegir EXACTAMENTE ese mismo nombre (respetando mayúsculas y espacios).
   - Si no encaja en ninguno de los existentes, propón un nombre de género canónico, elegante y corto (ej: "Dark Romance", "Ciencia Ficción", "Fantasía", "Thriller", "Autoayuda", "Terror").
   - NUNCA uses nombres genéricos vagos si puedes ser preciso (ej: prefiere "Dark Romance" o "Romance Histórico" si aplica).

Devuelve EXCLUSIVAMENTE un objeto JSON válido con este esquema:
{{
  "title": "Título limpio",
  "author": "Nombre del autor",
  "genre": "Género o Tema asignado"
}}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                candidate_text = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(candidate_text)
                logger.info(f"Gemini clasificó exitosamente: {parsed}")
                return {
                    "title": parsed.get("title", filename),
                    "author": parsed.get("author", "Desconocido"),
                    "genre": parsed.get("genre", "General")
                }
            else:
                logger.warning(f"Error en Gemini API ({response.status_code}): {response.text}")
    except Exception as e:
        logger.error(f"Excepción al consultar Gemini API: {e}")

    # Fallback si la IA falla
    return fallback_parse_filename(filename)
