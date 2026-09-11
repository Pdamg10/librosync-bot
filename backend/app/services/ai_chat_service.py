import logging
import json
import asyncio
import httpx
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.book import Book
from app.models.reading import ReadingState, BuddyRead
from app.models.telegram_link import TelegramLink

logger = logging.getLogger(__name__)

GEMINI_CHAT_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
]

async def chat_with_griffin_ai(
    session: AsyncSession,
    message: str,
    user_id: int = 1,
    telegram_link_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Genera una respuesta inteligente y personalizada de Griffin IA usando Google Gemini,
    con acceso directo y en tiempo real a la base de datos de libros, estantes, progreso de lectura,
    sagas y lecturas conjuntas de la comunidad.
    """
    clean_msg = message.strip()
    lower_msg = clean_msg.lower()

    # 1. Obtener contexto de estantes del usuario (ReadingState)
    stmt_states = (
        select(ReadingState)
        .options(selectinload(ReadingState.book))
        .where(or_(ReadingState.user_id == user_id, ReadingState.user_id == 2))
    )
    states = (await session.execute(stmt_states)).scalars().all()

    reading_list = [s for s in states if s.status == "reading" and s.book]
    finished_list = [s for s in states if s.status == "finished" and s.book]
    to_read_list = [s for s in states if s.status == "to_read" and s.book]
    favorites_list = [s for s in states if s.is_favorite and s.book]

    reading_context_lines = []
    for r in reading_list:
        reading_context_lines.append(
            f"• '{r.book.title}' de {r.book.author or 'Desconocido'} ({r.book.genre or 'General'}) - Avance: {round(r.progress_percent)}%"
        )

    # 2. Obtener libros recientes y catálogo del grupo
    book_conditions = []
    if telegram_link_id:
        book_conditions.append(Book.telegram_link_id == telegram_link_id)
    
    stmt_recent = (
        select(Book)
        .where(*book_conditions)
        .order_by(Book.uploaded_at.desc())
        .limit(25)
    )
    recent_books = (await session.execute(stmt_recent)).scalars().all()

    # Total de libros en biblioteca
    stmt_total = select(func.count(Book.id))
    if telegram_link_id:
        stmt_total = stmt_total.where(Book.telegram_link_id == telegram_link_id)
    total_books_count = (await session.execute(stmt_total)).scalar_one() or len(recent_books)

    # 3. Lecturas conjuntas activas
    stmt_br = select(BuddyRead).where(BuddyRead.status == "active").options(selectinload(BuddyRead.book))
    active_buddy_reads = (await session.execute(stmt_br)).scalars().all()

    buddy_context_lines = []
    for br in active_buddy_reads:
        if br.book:
            buddy_context_lines.append(f"• '{br.title or br.book.title}' ({br.book.author or 'Desconocido'})")

    # 4. Formatear muestras del catálogo para la IA
    catalog_sample_lines = []
    for b in recent_books[:18]:
        saga_info = f" (Saga: {b.series_name} #{b.series_order})" if b.series_name else ""
        catalog_sample_lines.append(
            f"- ID {b.id}: \"{b.title}\" por {b.author or 'Desconocido'} | Género: {b.genre or 'General'}{saga_info}"
        )

    # Formular Prompt contextual
    prompt = f"""
Eres Griffin, el bibliotecario inteligente, culto, cordial y entusiasta de la biblioteca digital "Anaquel / LibroSync" (conectada a Telegram y la app móvil).
Tienes acceso a la base de datos viva de libros y lecturas del usuario.

INFORMACIÓN VIVA DE LA BASE DE DATOS:
- Total de libros en la biblioteca comunitaria: {total_books_count} ejemplares.
- Libros que el usuario está leyendo actualmente ({len(reading_list)}):
{chr(10).join(reading_context_lines) if reading_context_lines else "• Ningún libro en curso actualmente."}
- Libros ya terminados por el usuario: {len(finished_list)} libro(s).
- Libros en lista de pendientes / por leer: {len(to_read_list)} libro(s).
- Libros favoritos del usuario: {len(favorites_list)} libro(s).
- Lecturas conjuntas comunitarias activas en el Club ({len(active_buddy_reads)}):
{chr(10).join(buddy_context_lines) if buddy_context_lines else "• No hay lecturas conjuntas activas en este momento."}

ÚLTIMAS NOVEDADES Y EJEMPLARES DESTACADOS EN EL ARCHIVO:
{chr(10).join(catalog_sample_lines)}

CONSULTA DEL USUARIO:
"{clean_msg}"

INSTRUCCIONES PARA TU RESPUESTA:
1. Responde SIEMPRE de forma natural, cálida y erudita en español, como el leal bibliotecario Griffin.
2. Si el usuario pregunta por "Mi progreso", "Mi avance" o qué está leyendo:
   - Detalla con precisión sus libros en curso y el porcentaje exacto de avance de cada uno.
   - Si no tiene libros en curso, anímalo afectuosamente a empezar alguno de las novedades.
   - Celebra si tiene libros ya completados.
3. Si el usuario pide "Recomiéndame", sugerencias de un género o autor:
   - Recomienda 2 o 3 títulos REALES de los disponibles en el catálogo de arriba.
   - Da una breve y seductora reseña de por qué vale la pena leerlos.
4. Si el usuario pide "Ver novedades" o "¿Qué hay de nuevo?":
   - Menciona los últimos títulos agregados a la biblioteca con su autor y género.
5. Si pregunta por el Club o lecturas conjuntas:
   - Cuéntale las sesiones activas del club de lectura.
6. Tu respuesta debe ser un objeto JSON con este formato EXACTO:
{{
  "reply": "Texto de tu respuesta formateado con emojis elegantes, saltos de línea y negritas.",
  "recommended_book_ids": [id1, id2]
}}
(En recommended_book_ids incluye los IDs numéricos de los libros del catálogo que recomendaste o mencionaste, máximo 3. Si no aplica, array vacío []).
"""

    reply_text = ""
    recommended_ids = []

    # Consultar Gemini si la API key está presente
    if settings.GEMINI_API_KEY:
        for model in GEMINI_CHAT_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.3
                }
            }
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
                        parsed = json.loads(raw_json)
                        reply_text = parsed.get("reply", "").strip()
                        recommended_ids = parsed.get("recommended_book_ids", [])
                        if reply_text:
                            logger.info(f"Griffin AI ({model}) respondió exitosamente.")
                            break
                    elif resp.status_code in (429, 503):
                        logger.warning(f"Modelo {model} ocupado/limitado ({resp.status_code}). Probando siguiente...")
                        continue
            except Exception as e:
                logger.warning(f"Error consultando modelo {model} para chat: {e}")
                continue

    # Fallback inteligente local basado en la BD si la IA estuviese inaccesible
    if not reply_text:
        if any(w in lower_msg for w in ["progreso", "avance", "leyendo", "estoy"]):
            if reading_list:
                details = "\n".join([f"• <b>{r.book.title}</b>: {round(r.progress_percent)}% completado" for r in reading_list])
                reply_text = f"📊 <b>Tu progreso de lectura actual:</b>\n\n{details}\n\n🏆 Has completado {len(finished_list)} libro(s) y tienes {len(to_read_list)} pendiente(s). ¡Sigue así!"
                recommended_ids = [r.book.id for r in reading_list[:3]]
            else:
                reply_text = "📖 Actualmente no tienes ningún libro en curso en tu estantería. ¡Puedes explorar el catálogo general o unirte a una lectura conjunta del club para comenzar!"
                recommended_ids = [b.id for b in recent_books[:2]]
        elif any(w in lower_msg for w in ["novedad", "nuevo", "reciente", "agregado"]):
            sample_titles = "\n".join([f"• <b>{b.title}</b> — <i>{b.author or 'Desconocido'}</i> ({b.genre or 'General'})" for b in recent_books[:4]])
            reply_text = f"✨ <b>Novedades recientes en la biblioteca ({total_books_count} libros en total):</b>\n\n{sample_titles}\n\n¿Deseas comenzar la lectura de alguno?"
            recommended_ids = [b.id for b in recent_books[:3]]
        elif any(w in lower_msg for w in ["recomiend", "sugier", "popular", "que leo"]):
            sample_picks = recent_books[:3]
            details = "\n".join([f"• <b>{b.title}</b> ({b.genre or 'General'}) de {b.author or 'Desconocido'}" for b in sample_picks])
            reply_text = f"🦉 <b>Recomendaciones destacadas para ti:</b>\n\n{details}\n\nSon títulos excelentes con gran acogida en nuestra comunidad."
            recommended_ids = [b.id for b in sample_picks]
        else:
            reply_text = f"👋 ¡Hola! Soy Griffin, tu bibliotecario. Nuestra biblioteca cuenta actualmente con <b>{total_books_count} libros</b> organizados por estantes. Puedes preguntarme por tu progreso de lectura, pedirme recomendaciones de cualquier género o consultar las novedades del club."
            recommended_ids = [b.id for b in recent_books[:2]]

    # Cargar objetos completos de Book para los IDs recomendados
    recommended_books = []
    if recommended_ids:
        clean_ids = [int(x) for x in recommended_ids if str(x).isdigit()]
        if clean_ids:
            stmt_recs = select(Book).where(Book.id.in_(clean_ids))
            recommended_books = (await session.execute(stmt_recs)).scalars().all()

    return {
        "reply": reply_text,
        "recommended_books": recommended_books
    }
