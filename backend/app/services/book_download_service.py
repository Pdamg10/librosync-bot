import io
import re
import logging
import asyncio
import urllib.parse
import zipfile
from typing import List, Dict, Any, Optional, Tuple
import httpx
from telegram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.book import Book
from app.models.telegram_link import TelegramLink
from app.models.topic import Topic
from app.services.topic_resolver import resolve_or_create_topic, normalize_genre_slug
from app.services.ai_classifier import classify_book_with_gemini, get_genre_emoji
from app.services.metadata_extractor import extract_internal_book_metadata, is_generic_or_cryptic_filename
from app.services.telegram_service import send_book_document
from app.services.series_formatter import format_book_full_description

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_SIZE_BYTES = 48 * 1024 * 1024  # 48 MB (Telegram Bot limit is 50MB)

SUPPORTED_BOOK_FORMATS = {"epub", "pdf", "mobi", "azw3", "cbr", "cbz"}
_PLACEHOLDER_METADATA = {
    "", "desconocido", "desconocida", "unknown", "sin titulo", "sin título",
    "none", "null", "n/a", "no disponible",
}


def _normalized_extension(filename: str) -> str:
    """Devuelve la extensión real de un nombre de archivo, sin parámetros de URL."""
    clean = urllib.parse.unquote((filename or "").split("?", 1)[0]).strip()
    clean = clean.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in clean:
        return ""
    return clean.rsplit(".", 1)[-1].lower()


def detect_book_format(
    content_bytes: bytes,
    filename: str = "",
    expected_format: Optional[str] = None
) -> str:
    """
    Detecta el formato real del archivo por su firma binaria en lugar de confiar
    ciegamente en la URL. Algunos repositorios entregan nombres como
    '2000.epub3.images' aunque el contenido sea un EPUB válido.
    """
    head = (content_bytes or b"")[:1024].lstrip()

    if head.startswith(b"%PDF"):
        return "pdf"

    if head.startswith(b"PK\x03\x04"):
        # Un ZIP puede ser EPUB o CBZ. Comprobamos el mimetype/estructura EPUB
        # y, si no es concluyente, usamos el nombre o el formato esperado.
        try:
            with zipfile.ZipFile(io.BytesIO(content_bytes)) as zf:
                names = set(zf.namelist())
                if "mimetype" in names:
                    mime = zf.read("mimetype")[:80].lower()
                    if b"epub" in mime:
                        return "epub"
                if "META-INF/container.xml" in names:
                    return "epub"
        except Exception:
            pass

        for value in (filename, expected_format or ""):
            ext = _normalized_extension(value) if "." in (value or "") else (value or "").lower()
            if ext in {"cbz", "cbr"}:
                return ext
        # La mayoría de los ZIP descargados de repositorios de libros son EPUB,
        # incluso cuando la URL los etiqueta erróneamente como PDF.
        return "epub"

    ext = _normalized_extension(filename)
    if ext in SUPPORTED_BOOK_FORMATS:
        return ext

    expected = (expected_format or "").lower().lstrip(".")
    if expected in SUPPORTED_BOOK_FORMATS:
        return expected

    return ""


def normalize_download_filename(filename: str, detected_format: str = "epub") -> str:
    """Limpia nombres de descarga como '2000.epub3.images' -> '2000.epub'."""
    clean = urllib.parse.unquote((filename or "").split("?", 1)[0]).strip()
    clean = clean.replace("\\", "/").rsplit("/", 1)[-1]

    if not clean:
        return f"libro_descargado.{detected_format or 'epub'}"

    detected = (detected_format or "").lower().lstrip(".")
    lower = clean.lower()
    for suffix in (".epub3.images", ".epub.images", ".epub.noimages", ".epub3"):
        if lower.endswith(suffix):
            clean = clean[: -len(suffix)].rstrip(" ._-") or "libro_descargado"
            return f"{clean}.{detected or 'epub'}"

    ext = _normalized_extension(clean)
    if ext in SUPPORTED_BOOK_FORMATS:
        if detected and ext != detected:
            return f"{clean[: -(len(ext) + 1)]}.{detected}"
        return clean

    # Quitar sufijos técnicos habituales antes de añadir la extensión correcta.
    clean = re.sub(
        r"(?:\.(?:images|noimages|epub\d*|pdf\d*|bin|dat|tmp|download|html?|php))+$",
        "",
        clean,
        flags=re.IGNORECASE,
    ).rstrip(" ._-")
    if not clean:
        clean = "libro_descargado"
    return f"{clean}.{detected_format or 'epub'}"


def build_book_filename(title: str, author: str, file_format: str) -> str:
    """Construye un nombre seguro y de longitud limitada para enviarlo a Telegram."""
    def _sanitize(value: str, limit: int, fallback: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9À-ÿ_\-. ]", "", str(value or "")).strip(" ._-")
        clean = re.sub(r"\s+", " ", clean)
        return (clean[:limit].rstrip(" ._-") or fallback)

    safe_title = _sanitize(title, 90, "Libro")
    safe_author = _sanitize(author, 60, "Desconocido")
    return f"{safe_title} - {safe_author}.{file_format or 'epub'}"


def _is_placeholder_metadata(value: Any) -> bool:
    return not isinstance(value, str) or value.strip().lower() in _PLACEHOLDER_METADATA


def _clean_meta_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _looks_like_generic_title(title: str, file_format: str = "epub") -> bool:
    """Detecta títulos que en realidad son el nombre críptico del archivo."""
    if _is_placeholder_metadata(title):
        return True
    candidate = title if "." in title else f"{title}.{file_format}"
    return is_generic_or_cryptic_filename(candidate)

LIBGEN_MIRRORS = [
    "https://libgen.is",
    "http://libgen.is",
    "https://libgen.rs",
    "https://libgen.st",
    "https://libgen.li",
    "https://libgen.vg",
]
LIBGEN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

SPANISH_STOP_WORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    "a", "al", "en", "y", "e", "o", "u", "por", "para", "con", "sin", "sobre",
    "que", "se", "su", "sus", "libro", "saga"
}


def build_search_terms(query: str) -> Tuple[str, str]:
    """Genera términos de búsqueda limpios sin palabras vacías para motores booleanos."""
    clean_q = re.sub(r"[^\w\s]", " ", query).strip()
    words = clean_q.split()
    filtered = [w for w in words if w.lower() not in SPANISH_STOP_WORDS and len(w) > 1]
    if not filtered:
        filtered = words
    boolean_terms = " AND ".join(filtered)
    raw_query = " ".join(filtered)
    return boolean_terms, raw_query


def parse_libgen_size(size_str: str) -> int:
    """Convierte cadenas de tamaño como '12 MB', '450 kB', '1.2 GB' a bytes enteros."""
    if not size_str:
        return 0
    size_str = size_str.strip()
    match = re.match(r"^([\d\.]+)\s*([a-zA-Z]+)$", size_str)
    if not match:
        return 0
    try:
        val = float(match.group(1))
        unit = match.group(2).lower()
        if "g" in unit:
            return int(val * 1024 * 1024 * 1024)
        if "m" in unit:
            return int(val * 1024 * 1024)
        if "k" in unit:
            return int(val * 1024)
        return int(val)
    except (ValueError, TypeError):
        return 0


def format_size(size_bytes: int) -> str:
    """Convierte bytes a formato legible (KB o MB)."""
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def clean_author_name(raw_name: Any) -> str:
    """Limpia autores: 'Cervantes Saavedra, Miguel de, 1547-1616' -> 'Miguel de Cervantes Saavedra'."""
    if not raw_name:
        return "Desconocido"
    if isinstance(raw_name, (list, tuple)):
        raw_name = raw_name[0] if raw_name else "Desconocido"

    text = re.sub(r"\s+", " ", str(raw_name)).strip()
    # Quitar aclaraciones y fechas de nacimiento/fallecimiento.
    text = re.sub(r"\s*\([^)]*\)", "", text).strip()
    text = re.sub(r"[,\s]*\b\d{3,4}\s*[-–—]\s*\d{0,4}\b\s*$", "", text).strip(" ,;")

    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) == 2:
        text = f"{parts[1]} {parts[0]}".strip()

    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;")
    return text or "Desconocido"


_LANGUAGE_ALIASES: Dict[str, set] = {
    "Español": {"es", "esp", "spa", "spanish", "español", "espanol", "castellano", "castilian"},
    "Inglés": {"en", "eng", "english", "inglés", "ingles"},
    "Francés": {"fr", "fre", "fra", "french", "francés", "frances"},
    "Alemán": {"de", "ger", "deu", "german", "alemán", "aleman"},
    "Italiano": {"it", "ita", "italian", "italiano"},
    "Portugués": {"pt", "por", "portuguese", "portugués", "portugues"},
    "Rumano": {"ro", "ron", "rum", "romanian", "rumano"},
    "Esperanto": {"eo", "epo", "esperanto"},
    "Húngaro": {"hu", "hun", "hungarian", "húngaro", "hungaro"},
    "Ruso": {"ru", "rus", "russian", "ruso"},
    "Japonés": {"ja", "jpn", "japanese", "japonés", "japones"},
    "Chino": {"zh", "zho", "chi", "chinese", "chino"},
    "Árabe": {"ar", "ara", "arabic", "árabe", "arabe"},
    "Latín": {"la", "lat", "latin", "latín"},
    "Neerlandés": {"nl", "nld", "dut", "dutch", "neerlandés", "neerlandes"},
    "Catalán": {"ca", "cat", "catalan", "catalán"},
    "Griego": {"el", "ell", "gre", "greek", "griego"},
    "Polaco": {"pl", "pol", "polish", "polaco"},
    "Sueco": {"sv", "swe", "swedish", "sueco"},
    "Danés": {"da", "dan", "danish", "danés", "danes"},
    "Finés": {"fi", "fin", "finnish", "finés", "fines"},
    "Noruego": {"no", "nor", "norwegian", "noruego"},
    "Checo": {"cs", "ces", "cze", "czech", "checo"},
    "Hebreo": {"he", "heb", "hebrew", "hebreo"},
}


def _known_language_label(raw_value: Any) -> Optional[str]:
    """Devuelve la etiqueta canónica solo si el valor parece un idioma conocido."""
    token = re.split(r"[;,/|()\[\]]", str(raw_value or "").strip().lower())[0].strip()
    if not token:
        return None
    base = token.split("-")[0].strip()
    for label, codes in _LANGUAGE_ALIASES.items():
        if token in codes or base in codes:
            return label
    return None


def normalize_language(raw_language: Any) -> Optional[str]:
    """Normaliza códigos y nombres de idioma de las distintas fuentes."""
    if isinstance(raw_language, (list, tuple)):
        raw_language = raw_language[0] if raw_language else ""
    if isinstance(raw_language, dict):
        raw_language = raw_language.get("key") or raw_language.get("name") or ""
    value = str(raw_language or "").strip()
    if not value:
        return None

    known = _known_language_label(value)
    if known:
        return known
    return value.title()[:40]


def extract_title_language(raw_title: Any) -> Tuple[str, Optional[str]]:
    """
    Separa el idioma cuando el título de la fuente lo incluye entre paréntesis,
    por ejemplo: 'Don Quijote (Spanish)' -> ('Don Quijote', 'Español').

    Solo se elimina el paréntesis si contiene un idioma reconocido; así no se
    mutilan títulos como 'El Quijote (Edición ilustrada)'.
    """
    title = str(raw_title or "").strip()
    match = re.search(r"\s*[\(\[]([^\(\)\[\]]+)[\)\]]\s*$", title)
    if match:
        language = _known_language_label(match.group(1))
        if language:
            cleaned = title[: match.start()].strip(" -–—:,")
            if cleaned:
                return cleaned, language
    return title, None


async def _fetch_archive_files(
    client: httpx.AsyncClient, identifier: str
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Obtiene las variantes EPUB/PDF de un item de Internet Archive.

    El endpoint /metadata/{id} suele ser lento y limitar peticiones concurrentes.
    El listado del directorio de descarga es mucho más rápido y ya incluye los
    nombres y tamaños reales de los archivos.
    """
    best: Dict[str, Optional[Dict[str, Any]]] = {"epub": None, "pdf": None}

    def _consider(name: str, size: int, expected_format: str = "") -> None:
        clean_name = urllib.parse.unquote(str(name or "")).split("?", 1)[0]
        low = clean_name.lower()
        if not clean_name or low.startswith("_") or "/" in clean_name:
            return
        if low.endswith(("lcp.epub", "_encrypted.epub", "_chocr.html.gz", "_daisy.zip")):
            return

        fmt = ""
        if low.endswith(".epub") or expected_format.upper() == "EPUB":
            fmt = "epub"
        elif low.endswith(".pdf") or expected_format in ("Text PDF", "Image Container PDF"):
            fmt = "pdf"
        if not fmt:
            return

        if size and (size > MAX_DOWNLOAD_SIZE_BYTES or size < 10000):
            return

        current = best.get(fmt)
        if not current or size > int(current.get("size", 0) or 0):
            best[fmt] = {"name": clean_name, "size": size, "format": fmt}

    # 1. Listado HTML del directorio (rápido y con tamaños).
    try:
        from bs4 import BeautifulSoup
        resp = await client.get(f"https://archive.org/download/{identifier}/", timeout=5.0)
        if resp.status_code == 200 and "directory-listing-table" in resp.text:
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.select("table.directory-listing-table tr"):
                link = row.find("a", href=True)
                if not link:
                    continue
                tds = row.find_all("td")
                size_text = tds[2].get_text(strip=True) if len(tds) >= 3 else ""
                _consider(link["href"], parse_libgen_size(size_text))
            if any(best.values()):
                return best
    except Exception as e:
        logger.debug(f"Listado de Internet Archive falló para {identifier}: {e}")

    # 2. Respaldo: listado JSON de archivos del item.
    try:
        resp = await client.get(f"https://archive.org/metadata/{identifier}/files", timeout=3.5)
        if resp.status_code == 200:
            for f in resp.json().get("result", []):
                try:
                    size = int(f.get("size", 0) or 0)
                except (ValueError, TypeError):
                    size = 0
                _consider(f.get("name", ""), size, f.get("format", ""))
    except Exception as e:
        logger.debug(f"Metadatos de archivos fallaron para {identifier}: {e}")

    return best


async def search_internet_archive(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Busca libros en Internet Archive con descarga directa en EPUB o PDF en paralelo y de alta velocidad."""
    results: List[Dict[str, Any]] = []
    boolean_terms, _ = build_search_terms(query)
    if not boolean_terms:
        return results

    ia_search_url = "https://archive.org/advancedsearch.php"
    # Filtrar explícitamente colecciones con préstamo digital restringido (printdisabled / inlibrary)
    q_filter = f'mediatype:(texts) AND ({boolean_terms}) AND -collection:(printdisabled) AND -collection:(inlibrary)'

    params = {
        "q": q_filter,
        "fl[]": [
            "identifier", "title", "creator", "year", "language",
            "format", "downloads", "collection", "access-restricted-item",
        ],
        "sort[]": "downloads desc",
        "rows": str(limit + 4),
        "output": "json"
    }

    try:
        async with httpx.AsyncClient(timeout=7.0, verify=False) as client:
            resp = await client.get(ia_search_url, params=params)
            if resp.status_code != 200:
                return results

            data = resp.json()
            docs = data.get("response", {}).get("docs", [])
            logger.debug(f"Internet Archive devolvió {len(docs)} documentos para '{query}'")
            if not docs:
                return results

            # Priorizar coincidencias exactas de título antes que popularidad.
            query_slug = normalize_genre_slug(query)
            query_tokens = [
                normalize_genre_slug(token)
                for token in re.findall(r"\w+", query)
                if len(token) > 1
            ]
            query_tokens = [token for token in query_tokens if token]

            def _relevance(doc: Dict[str, Any]) -> Tuple[int, int]:
                raw_title = doc.get("title") or ""
                if isinstance(raw_title, (list, tuple)):
                    raw_title = raw_title[0] if raw_title else ""
                title_slug = normalize_genre_slug(str(raw_title))
                if query_slug and title_slug == query_slug:
                    rank = 0
                elif query_slug and query_slug in title_slug:
                    rank = 1
                else:
                    missing = sum(
                        1 for token in query_tokens if token not in title_slug
                    )
                    rank = 2 + missing
                try:
                    downloads = int(doc.get("downloads") or 0)
                except (TypeError, ValueError):
                    downloads = 0
                return rank, -downloads

            docs.sort(key=_relevance)

            # Inspección concurrente de archivos en paralelo para no bloquear el bot
            async def _inspect_doc(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
                identifier = doc.get("identifier")
                if not identifier:
                    return []

                raw_title = doc.get("title") or identifier
                if isinstance(raw_title, (list, tuple)):
                    raw_title = raw_title[0] if raw_title else identifier
                title = str(raw_title).strip() or identifier
                creator = clean_author_name(doc.get("creator") or "Desconocido")
                year = str(doc.get("year") or "").strip() or None
                language = normalize_language(doc.get("language"))

                # Descartar libros de préstamo cerrado / DRM.
                if str(doc.get("access-restricted-item") or "").lower() in ("true", "1", "yes"):
                    return []
                collections = str(doc.get("collection") or "").lower()
                if "printdisabled" in collections or "inlibrary" in collections:
                    return []

                try:
                    best_files = await _fetch_archive_files(client, identifier)
                    variants: List[Dict[str, Any]] = []
                    for fmt_clean in ("epub", "pdf"):
                        chosen = best_files.get(fmt_clean)
                        if not chosen:
                            continue
                        fname = chosen["name"]
                        size_b = int(chosen.get("size", 0) or 0)
                        dl_url = (
                            f"https://archive.org/download/{identifier}/"
                            f"{urllib.parse.quote(fname, safe='/')}"
                        )
                        variants.append({
                            "source": "Internet Archive",
                            "title": title,
                            "author": creator,
                            "year": year,
                            "language": language,
                            "format": fmt_clean,
                            "filename": fname,
                            "size_bytes": size_b,
                            "size_str": format_size(size_b) if size_b else "Descarga directa",
                            "download_url": dl_url,
                            "identifier": identifier
                        })
                    return variants
                except Exception as e:
                    logger.debug(
                        f"No se pudo inspeccionar el item de Internet Archive "
                        f"{identifier}: {type(e).__name__}: {e}"
                    )
                    return []

            tasks = [_inspect_doc(doc) for doc in docs[: limit + 4]]
            doc_results = await asyncio.gather(*tasks, return_exceptions=True)
            for doc_variants in doc_results:
                if isinstance(doc_variants, list):
                    for r in doc_variants:
                        if r:
                            results.append(r)
                        if len(results) >= limit:
                            break
                if len(results) >= limit:
                    break

    except Exception as e:
        logger.warning(f"Aviso buscando en Archive.org ({type(e).__name__}): {e!r}")

    return results


async def search_open_library(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Busca en Open Library de Internet Archive títulos libres de acceso público (sin DRM / préstamo cerrado)."""
    results: List[Dict[str, Any]] = []
    _, raw_terms = build_search_terms(query)
    if not raw_terms:
        return results

    ol_url = "https://openlibrary.org/search.json"
    params = {"q": raw_terms, "limit": str(limit + 5)}

    try:
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            resp = await client.get(ol_url, params=params)
            if resp.status_code != 200:
                return results

            docs = resp.json().get("docs", [])

            async def _inspect_ol_doc(d: Dict[str, Any]) -> List[Dict[str, Any]]:
                # Filtrar estrictamente solo libros de acceso público real (no DRM ni préstamo borrowable)
                ebook_access = d.get("ebook_access")
                is_public_scan = d.get("public_scan_b", False)
                if ebook_access != "public" and not is_public_scan:
                    return []

                ia_ids = d.get("ia", [])
                if not ia_ids:
                    return []

                candidate_ids = [
                    candidate for candidate in ia_ids
                    if not candidate.endswith(("_daisy", "_chocr"))
                ]
                if not candidate_ids:
                    candidate_ids = list(ia_ids)

                title = d.get("title") or "Sin título"
                authors = d.get("author_name", [])
                author = clean_author_name(authors[0] if authors else "Desconocido")
                first_pub = str(d.get("first_publish_year") or "").strip() or None
                language = normalize_language(d.get("language"))

                try:
                    best_ia = ""
                    best_files: Dict[str, Optional[Dict[str, Any]]] = {}
                    for candidate_id in candidate_ids[:3]:
                        files = await _fetch_archive_files(client, candidate_id)
                        if any(files.values()):
                            best_ia = candidate_id
                            best_files = files
                            break
                    if not best_ia:
                        return []

                    variants: List[Dict[str, Any]] = []
                    for f_fmt in ("epub", "pdf"):
                        f_obj = best_files.get(f_fmt)
                        if not f_obj:
                            continue
                        f_size = int(f_obj.get("size", 0) or 0)
                        fname = f_obj["name"]
                        dl_url = f"https://archive.org/download/{best_ia}/{urllib.parse.quote(fname, safe='/')}"
                        variants.append({
                            "source": "Open Library",
                            "title": title,
                            "author": author,
                            "year": first_pub,
                            "language": language,
                            "format": f_fmt,
                            "filename": fname,
                            "size_bytes": f_size,
                            "size_str": format_size(f_size) if f_size else "Descarga directa",
                            "download_url": dl_url,
                            "identifier": f"ol_{best_ia}"
                        })
                    return variants
                except Exception:
                    return []

            tasks = [_inspect_ol_doc(d) for d in docs[: limit + 6]]
            doc_results = await asyncio.gather(*tasks, return_exceptions=True)
            for doc_variants in doc_results:
                if isinstance(doc_variants, list):
                    for r in doc_variants:
                        if r:
                            results.append(r)
                        if len(results) >= limit:
                            break
                if len(results) >= limit:
                    break

    except Exception as e:
        logger.warning(f"Aviso buscando en OpenLibrary ({type(e).__name__}): {e!r}")

    return results


async def _search_gutenberg_direct(query: str, limit: int) -> List[Dict[str, Any]]:
    """Busca directamente en la web de Project Gutenberg."""
    results: List[Dict[str, Any]] = []
    gutenberg_search_url = "https://www.gutenberg.org/ebooks/search/"
    params = {"query": query, "submit_search": "Go!"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    try:
        from bs4 import BeautifulSoup
        async with httpx.AsyncClient(timeout=4.5, follow_redirects=True, headers=headers, verify=False) as client:
            resp = await client.get(gutenberg_search_url, params=params)
            if resp.status_code != 200:
                return results

            soup = BeautifulSoup(resp.text, "html.parser")
            book_items = soup.select("li.booklink")
            for item in book_items[: limit + 3]:
                a_link = item.select_one("a.link")
                if not a_link or not a_link.get("href"):
                    continue
                href = a_link["href"]
                m_id = re.search(r"/ebooks/(\d+)", href)
                if not m_id:
                    continue
                ebook_id = m_id.group(1)

                title_el = item.select_one(".title")
                raw_title = title_el.get_text(strip=True) if title_el else "Sin título"
                title, language = extract_title_language(raw_title)

                author_el = item.select_one(".subtitle")
                author = clean_author_name(author_el.get_text(strip=True) if author_el else "Desconocido")

                clean_fname = f"{re.sub(r'[^a-zA-Z0-9_\- ]', '', title)[:40].strip().replace(' ', '_')}.epub"
                dl_url = f"https://www.gutenberg.org/ebooks/{ebook_id}.epub3.images"

                results.append({
                    "source": "Project Gutenberg",
                    "title": title,
                    "author": author,
                    "year": None,
                    "language": language,
                    "format": "epub",
                    "filename": clean_fname,
                    "size_bytes": 1024 * 1024,
                    "size_str": "~1.5 MB",
                    "download_url": dl_url,
                    "identifier": f"gutenberg_{ebook_id}"
                })
                if len(results) >= limit:
                    break
    except Exception as e:
        logger.debug(f"Aviso buscando directamente en Gutenberg: {e}")

    return results


async def _search_gutendex(query: str, limit: int) -> List[Dict[str, Any]]:
    """Consulta Gutendex para obtener idioma y formatos alternativos."""
    results: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=3.5, follow_redirects=True, verify=False) as client:
            resp = await client.get("https://gutendex.com/books/", params={"search": query})
            if resp.status_code != 200:
                return results

            items = resp.json().get("results", [])
            for item in items[: limit + 3]:
                formats = item.get("formats", {})
                epub_url = formats.get("application/epub+zip")
                pdf_url = formats.get("application/pdf")
                if not epub_url and not pdf_url:
                    continue

                authors_raw = item.get("authors", [])
                author_name = "Desconocido"
                if authors_raw:
                    author_name = clean_author_name(authors_raw[0].get("name", "Desconocido"))

                raw_title = re.sub(r"\s+", " ", item.get("title", "Sin título")).strip()
                title, language = extract_title_language(raw_title)
                languages = item.get("languages") or []
                language = normalize_language(languages[0]) if languages else language

                for fmt, dl_url in (("epub", epub_url), ("pdf", pdf_url)):
                    if not dl_url:
                        continue
                    clean_fname = (
                        f"{re.sub(r'[^a-zA-Z0-9_\- ]', '', title)[:40].strip().replace(' ', '_')}.{fmt}"
                    )
                    results.append({
                        "source": "Project Gutenberg",
                        "title": title,
                        "author": author_name,
                        "year": None,
                        "language": language,
                        "format": fmt,
                        "filename": clean_fname,
                        "size_bytes": 1024 * 1024,
                        "size_str": "~1.5 MB",
                        "download_url": dl_url,
                        "identifier": f"gutenberg_{item.get('id')}"
                    })
    except Exception as e:
        logger.debug(f"Aviso buscando en Gutendex: {e}")

    return results


async def search_project_gutenberg(query: str, limit: int = 2) -> List[Dict[str, Any]]:
    """Busca en Project Gutenberg combinando su web y Gutendex (idioma y formatos)."""
    clean_q = re.sub(r"[^\w\s]", " ", query).strip()
    if not clean_q:
        return []

    direct_result, gutendex_result = await asyncio.gather(
        _search_gutenberg_direct(clean_q, limit),
        _search_gutendex(clean_q, limit),
        return_exceptions=True,
    )
    direct = direct_result if isinstance(direct_result, list) else []
    gutendex = gutendex_result if isinstance(gutendex_result, list) else []

    gutendex_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for item in gutendex:
        gid = str(item.get("identifier") or "").replace("gutenberg_", "")
        gutendex_by_id.setdefault(gid, []).append(item)

    merged: List[Dict[str, Any]] = []
    seen: set = set()

    for item in direct:
        identifier = item.get("identifier") or ""
        gid = identifier.replace("gutenberg_", "")
        related = gutendex_by_id.get(gid, [])

        if not item.get("language"):
            item["language"] = next((r.get("language") for r in related if r.get("language")), None)

        fmt = item.get("format") or "epub"
        seen.add((identifier, fmt))
        merged.append(item)

        # Gutendex puede ofrecer PDF cuando la web no lo muestra en el resultado.
        for alt in related:
            alt_fmt = alt.get("format")
            if alt_fmt and alt_fmt != fmt and (identifier, alt_fmt) not in seen:
                alt_copy = dict(alt)
                alt_copy["title"] = item.get("title") or alt_copy.get("title")
                alt_copy["author"] = item.get("author") or alt_copy.get("author")
                alt_copy["year"] = item.get("year") or alt_copy.get("year")
                seen.add((identifier, alt_fmt))
                merged.append(alt_copy)

    for item in gutendex:
        key = (item.get("identifier"), item.get("format"))
        if key not in seen:
            seen.add(key)
            merged.append(item)

    return merged[:limit]


def detect_language_from_text(value: str) -> Optional[str]:
    """Detecta un idioma dentro de una celda de tabla (p. ej. 'English [en]')."""
    return _known_language_label(value)


async def search_libgen(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Busca libros en Library Genesis con fail-fast y evasión de bloqueos."""
    results: List[Dict[str, Any]] = []
    clean_q = re.sub(r"[^\w\s]", " ", query).strip()
    if not clean_q:
        return results

    from bs4 import BeautifulSoup
    params = {
        "req": clean_q,
        "columns[]": ["t", "a"],
        "objects[]": ["f"],
        "topics[]": ["l", "f"],
        "res": "25",
        "filesuns": "all",
    }

    async def _query_mirror(mirror: str) -> List[Dict[str, Any]]:
        m_results: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=2.5, headers=LIBGEN_HEADERS, follow_redirects=True, verify=False) as client:
                resp = await client.get(f"{mirror}/index.php", params=params)
                if resp.status_code != 200:
                    return m_results

                if "welcome to nginx" in resp.text.lower() or "502 bad gateway" in resp.text.lower():
                    return m_results

                soup = BeautifulSoup(resp.text, "html.parser")
                table = soup.find("table", {"id": "tablelibgen"}) or soup.find("table", {"class": "c"})
                if not table:
                    return m_results

                rows = table.find_all("tr")
                for row in rows[1:]:
                    tds = row.find_all("td")
                    if len(tds) < 8:
                        continue

                    fmt = None
                    for td in tds:
                        txt = td.get_text(strip=True).lower()
                        if txt in ["epub", "pdf"]:
                            fmt = txt
                            break
                    if not fmt:
                        continue

                    ads_a = row.find("a", href=lambda h: h and ("ads.php" in h or "get.php" in h or "library.lol" in h))
                    if not ads_a:
                        continue

                    title_a = row.find("a", href=lambda h: h and "edition.php" in h) or row.find("a")
                    if title_a:
                        for itag in title_a.find_all("i"):
                            itag.decompose()
                        title = re.sub(r"\s+", " ", title_a.get_text(strip=True)).strip()
                    else:
                        title = "Libro"

                    author = clean_author_name(tds[1].get_text(strip=True) if len(tds) > 1 else "Desconocido")

                    # LibGen cambia el orden de columnas entre espejos. Detectamos
                    # año, idioma y tamaño por su contenido en lugar de por posición.
                    year = None
                    language = None
                    size_text = ""
                    for td in tds[3:]:
                        txt = td.get_text(" ", strip=True)
                        if not txt:
                            continue
                        if not language:
                            language = detect_language_from_text(txt)
                        if not year and len(txt) <= 12:
                            y_match = re.fullmatch(r"(?:c\.?\s*)?((?:19|20)\d{2})", txt, re.IGNORECASE)
                            if y_match:
                                year = y_match.group(1)
                        if not size_text and re.fullmatch(
                            r"\d+(?:[.,]\d+)?\s*(?:B|kB|KB|MB|GB)", txt, re.IGNORECASE
                        ):
                            size_text = txt

                    size_bytes = parse_libgen_size(size_text) if size_text else 2 * 1024 * 1024
                    if size_bytes > MAX_DOWNLOAD_SIZE_BYTES:
                        continue
                    size_str = size_text or format_size(size_bytes)

                    ads_href = ads_a["href"]
                    ads_url = urllib.parse.urljoin(mirror, ads_href)

                    # Obtener hash MD5
                    md5_match = re.search(r"md5=([a-fA-F0-9]{32})", ads_href)
                    md5_id = md5_match.group(1) if md5_match else f"{abs(hash(title))}"

                    clean_fname = f"{re.sub(r'[^a-zA-Z0-9_\- ]', '', title)[:45].strip().replace(' ', '_')}.{fmt}"

                    m_results.append({
                        "source": "Library Genesis",
                        "title": title,
                        "author": author,
                        "year": year,
                        "language": language,
                        "format": fmt,
                        "filename": clean_fname,
                        "size_bytes": size_bytes,
                        "size_str": size_str,
                        "download_url": ads_url,
                        "identifier": f"libgen_{md5_id}",
                        "is_libgen": True
                    })
                    if len(m_results) >= limit:
                        break
        except Exception:
            pass
        return m_results

    active_mirrors = ["https://libgen.is", "https://libgen.li"]
    tasks = [_query_mirror(m) for m in active_mirrors]
    mirror_res = await asyncio.gather(*tasks, return_exceptions=True)
    for r in mirror_res:
        if isinstance(r, list) and r:
            results.extend(r)
            break

    return results


async def search_external_books(query: str, max_results: int = 10, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Busca libros en fuentes concurrentes (Internet Archive, Open Library, Gutenberg y LibGen)
    con límite de tiempo estricto e independiente por fuente para evitar que el bot se quede colgado.

    - Reparte los resultados entre fuentes (round-robin) para que una sola no acapare la lista.
    - Conserva EPUB y PDF de una misma obra como variantes independientes.
    - Deduplica por título + autor + formato: así se muestran el mismo título con
      distintos autores y el mismo autor con distintos libros.
    """
    effective_limit = max(1, limit if limit is not None else max_results)
    source_limit = max(3, min(effective_limit, 10))

    async def _safe_search(coro, timeout_sec: float) -> List[Dict[str, Any]]:
        try:
            return await asyncio.wait_for(coro, timeout=timeout_sec)
        except Exception as e:
            logger.debug(f"Aviso en fuente de búsqueda externa ({timeout_sec}s): {e}")
            return []

    results_group = await asyncio.gather(
        _safe_search(search_internet_archive(query, limit=source_limit), 12.5),
        _safe_search(search_open_library(query, limit=min(source_limit, 5)), 6.5),
        _safe_search(search_project_gutenberg(query, limit=min(source_limit, 5)), 6.0),
        _safe_search(search_libgen(query, limit=source_limit), 3.0),
        return_exceptions=True,
    )

    source_order = ["Internet Archive", "Project Gutenberg", "Open Library", "Library Genesis"]
    grouped: Dict[str, List[Dict[str, Any]]] = {name: [] for name in source_order}
    for group in results_group:
        if not isinstance(group, list):
            continue
        for item in group:
            source = item.get("source") or "Otra fuente"
            grouped.setdefault(source, []).append(item)

    # Round-robin: una variante de cada fuente por vuelta.
    interleaved: List[Dict[str, Any]] = []
    max_len = max((len(items) for items in grouped.values()), default=0)
    for position in range(max_len):
        for source in source_order:
            items = grouped.get(source, [])
            if position < len(items):
                interleaved.append(items[position])
        for source, items in grouped.items():
            if source in source_order:
                continue
            if position < len(items):
                interleaved.append(items[position])

    seen_keys = set()
    seen_urls = set()
    unique_results: List[Dict[str, Any]] = []
    for item in interleaved:
        title_slug = normalize_genre_slug(item.get("title") or "")
        author_slug = normalize_genre_slug(item.get("author") or "")
        fmt = str(item.get("format") or "epub").lower().lstrip(".")

        if title_slug:
            key = (title_slug, author_slug, fmt)
        else:
            key = ("url", item.get("download_url") or "")

        url_key = str(item.get("download_url") or "").split("?", 1)[0]
        if key in seen_keys or (url_key and url_key in seen_urls):
            continue

        seen_keys.add(key)
        if url_key:
            seen_urls.add(url_key)
        unique_results.append(item)
        if len(unique_results) >= effective_limit:
            break

    return unique_results


# Alias de compatibilidad para evitar ImportError
search_books_online = search_external_books


async def download_book_bytes(download_url: str) -> Tuple[bytes, str]:
    """
    Descarga el archivo binario del libro asegurando que no exceda el límite de Telegram.
    Soporta descarga directa (Archive.org, Gutenberg) y resolución en 2 pasos de LibGen (ads.php -> get.php).
    Devuelve los bytes y el nombre de archivo limpio.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=headers, verify=False) as client:
        target_url = download_url
        req_headers = dict(headers)

        # Si es un enlace de LibGen que requiere resolver el botón GET desde ads.php
        if "ads.php" in download_url:
            base_url = download_url.split("/ads.php")[0]
            req_headers["Referer"] = f"{base_url}/index.php"
            ads_resp = await client.get(download_url, headers=req_headers)
            if ads_resp.status_code != 200:
                raise RuntimeError(f"No se pudo acceder a la página de descarga de LibGen ({ads_resp.status_code})")

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(ads_resp.text, "html.parser")
            get_link = soup.find("a", string=lambda s: s and s.strip().upper() == "GET")
            get_href = None
            if get_link and get_link.get("href"):
                get_href = get_link["href"]
            else:
                m = re.search(r"href=[\"\x27](get\.php\?md5=[^\"\x27]+)[\"\x27]", ads_resp.text)
                if m:
                    get_href = m.group(1)

            if not get_href:
                raise RuntimeError("No se encontró el enlace de descarga directa en LibGen.")

            target_url = urllib.parse.urljoin(download_url, get_href)
            req_headers["Referer"] = download_url

        resp = await client.get(target_url, headers=req_headers)
        if resp.status_code == 403:
            raise RuntimeError("El archivo en el repositorio de origen requiere préstamo digital o acceso restringido por derechos de autor. Selecciona otra opción de la lista o sube tu archivo directamente.")
        if resp.status_code != 200:
            raise RuntimeError(f"El servidor de origen respondió con código {resp.status_code}")

        content_bytes = resp.content
        if len(content_bytes) < 20:
            raise ValueError("El archivo descargado está vacío o corrupto.")

        # Comprobar que no sea una página HTML de error disfrazada de EPUB/PDF
        first_bytes = content_bytes[:200].lstrip().lower()
        if first_bytes.startswith((b"<!doctype", b"<html", b"<?xml", b"<head")):
            raise ValueError("El servidor devolvió una página HTML en lugar del archivo binario del libro.")

        if len(content_bytes) > MAX_DOWNLOAD_SIZE_BYTES:
            raise ValueError(f"El archivo pesa {len(content_bytes) / (1024*1024):.1f} MB, excediendo el límite de 48 MB permitido.")

        filename = ""
        cd = resp.headers.get("content-disposition", "")
        if "filename=" in cd:
            cd_match = re.search(r'filename=["\']?([^"\';]+)["\']?', cd)
            if cd_match:
                extracted = urllib.parse.unquote(cd_match.group(1).strip())
                if "." in extracted:
                    filename = extracted

        if not filename and "/" in target_url:
            path_part = target_url.split("?")[0].rstrip("/")
            raw_fname = urllib.parse.unquote(path_part.split("/")[-1])
            if raw_fname and "." in raw_fname:
                filename = raw_fname

        detected_format = detect_book_format(content_bytes, filename)
        filename = normalize_download_filename(filename, detected_format or "epub")

        return content_bytes, filename


async def ingest_downloaded_book(
    bot: Bot,
    session: AsyncSession,
    link: TelegramLink,
    chat_id: int,
    file_bytes: bytes,
    filename: str,
    original_meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Procesa un libro descargado externamente y lo integra en la biblioteca de LibroSync:
    1. Inspecciona metadatos internos (EPUB Dublin Core o PDF).
    2. Clasifica y normaliza con Gemini AI (título, autor, género, año de publicación).
    3. Resuelve o crea el Topic correspondiente en Telegram.
    4. Envía el archivo vía Telegram Bot API al Topic.
    5. Guarda el registro en la base de datos.
    """
    ext = detect_book_format(file_bytes, filename) or (
        filename.rsplit(".", 1)[-1].lower() if "." in filename else "epub"
    )
    filename = normalize_download_filename(filename, ext)
    original = original_meta or {}

    internal_meta = extract_internal_book_metadata(file_bytes, ext)

    classification = await classify_book_with_gemini(
        filename=filename,
        caption=None,
        existing_topics=[t.genre for t in (await session.execute(select(Topic).where(Topic.telegram_link_id == link.id))).scalars().all()],
        internal_metadata=internal_meta
    )

    # La IA puede devolver "Desconocido" o el nombre numérico del archivo.
    # En ese caso preferimos el título/autor que ya traía el resultado de búsqueda.
    classified_title = _clean_meta_value(classification.get("title"))
    original_title = _clean_meta_value(original.get("title"))
    if (
        _looks_like_generic_title(classified_title, ext)
        and original_title
        and not _looks_like_generic_title(original_title, ext)
    ):
        title = original_title
    elif not _is_placeholder_metadata(classified_title):
        title = classified_title
    elif original_title:
        title = original_title
    else:
        title = filename.rsplit(".", 1)[0] or "Sin título"

    classified_author = _clean_meta_value(classification.get("author"))
    original_author = _clean_meta_value(original.get("author"))
    if not _is_placeholder_metadata(classified_author):
        author = classified_author
    elif original_author:
        author = original_author
    else:
        author = "Desconocido"

    classified_year = _clean_meta_value(classification.get("publication_year"))
    original_year = _clean_meta_value(original.get("year"))
    pub_year = (
        classified_year if not _is_placeholder_metadata(classified_year)
        else (original_year or "Desconocido")
    )

    classified_genre = _clean_meta_value(classification.get("genre"))
    genre = classified_genre if not _is_placeholder_metadata(classified_genre) else "General"
    suggested_emoji = classification.get("emoji") or get_genre_emoji(genre)
    if not isinstance(suggested_emoji, str) or not suggested_emoji.strip():
        suggested_emoji = get_genre_emoji(genre)

    title_slug = normalize_genre_slug(title)
    stmt_books = select(Book).where(Book.telegram_link_id == link.id)
    b_res = await session.execute(stmt_books)
    existing_books = b_res.scalars().all()

    matching_book = next((b for b in existing_books if normalize_genre_slug(b.title) == title_slug and b.file_format.lower() == ext), None)
    clean_chat_id = str(chat_id).replace("-100", "").replace("-", "")

    if matching_book and matching_book.telegram_message_id:
        dest_link = f"https://t.me/c/{clean_chat_id}/{matching_book.telegram_message_id}"
        return {
            "status": "duplicate",
            "title": matching_book.title,
            "author": matching_book.author,
            "genre": matching_book.genre,
            "publication_year": matching_book.publication_year or pub_year,
            "dest_link": dest_link,
            "file_format": ext
        }

    topic_id = None
    if link.forum_enabled:
        topic_id = await resolve_or_create_topic(
            session=session,
            bot=bot,
            telegram_link=link,
            genre=genre,
            suggested_emoji=suggested_emoji
        )

    series_name = classification.get("series_name")
    series_type = classification.get("series_type") or ("Saga" if series_name else "Autoconclusivo")
    series_order = classification.get("series_order")
    series_total = classification.get("series_total")
    has_sequel = classification.get("has_sequel")
    previous_book = classification.get("previous_book")
    next_book = classification.get("next_book")

    caption_meta = dict(classification)
    caption_meta.update({
        "title": title,
        "author": author,
        "genre": genre,
        "publication_year": pub_year,
        "emoji": suggested_emoji,
    })

    caption_text = format_book_full_description(
        book=caption_meta,
        chat_books=existing_books,
        clean_chat_id=clean_chat_id,
        current_topic_name=genre,
        current_topic_emoji=suggested_emoji,
        for_caption=True
    )

    clean_file_obj = io.BytesIO(file_bytes)
    clean_file_obj.name = build_book_filename(title, author, ext)

    sent_msg = await send_book_document(
        bot=bot,
        chat_id=chat_id,
        document=clean_file_obj,
        filename=clean_file_obj.name,
        caption=caption_text,
        topic_id=topic_id
    )

    doc_info = getattr(sent_msg, "document", None)
    new_book = Book(
        user_id=link.user_id,
        title=title,
        author=author,
        genre=genre,
        source="download",
        telegram_link_id=link.id,
        telegram_message_id=sent_msg.message_id,
        telegram_topic_id=topic_id,
        telegram_file_id=getattr(doc_info, "file_id", None),
        file_unique_id=getattr(doc_info, "file_unique_id", None),
        file_format=ext,
        publication_year=pub_year,
        series_name=series_name,
        series_type=series_type,
        series_order=series_order,
        series_total=series_total,
        has_sequel=has_sequel,
        previous_book=previous_book,
        next_book=next_book,
        reading_progress=0.0
    )
    session.add(new_book)
    await session.commit()
    await session.refresh(new_book)

    dest_link = f"https://t.me/c/{clean_chat_id}/{sent_msg.message_id}"
    return {
        "status": "success",
        "book_id": new_book.id,
        "title": title,
        "author": author,
        "genre": genre,
        "publication_year": pub_year,
        "emoji": suggested_emoji,
        "file_format": ext,
        "dest_link": dest_link,
        "target_message_id": sent_msg.message_id,
        "assigned_topic_id": topic_id,
        "series_name": series_name,
        "series_type": series_type,
        "series_order": series_order,
        "series_total": series_total,
        "has_sequel": has_sequel,
        "previous_book": previous_book,
        "next_book": next_book
    }
