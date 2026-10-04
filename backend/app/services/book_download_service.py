import io
import re
import logging
import asyncio
import urllib.parse
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
from app.services.metadata_extractor import extract_internal_book_metadata
from app.services.telegram_service import send_book_document
from app.services.series_formatter import format_book_full_description

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_SIZE_BYTES = 48 * 1024 * 1024  # 48 MB (Telegram Bot limit is 50MB)

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
    """Convierte 'Cervantes Saavedra, Miguel de' a 'Miguel de Cervantes Saavedra' y maneja listas."""
    if not raw_name:
        return "Desconocido"
    if isinstance(raw_name, list):
        raw_name = raw_name[0] if raw_name else "Desconocido"
    raw_name = str(raw_name).strip()
    parts = raw_name.split(",")
    if len(parts) == 2:
        return f"{parts[1].strip()} {parts[0].strip()}".strip()
    return raw_name


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
        "fl[]": ["identifier", "title", "creator", "year", "format", "downloads"],
        "sort[]": "downloads desc",
        "rows": str(limit + 4),
        "output": "json"
    }

    try:
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            resp = await client.get(ia_search_url, params=params)
            if resp.status_code != 200:
                return results

            data = resp.json()
            docs = data.get("response", {}).get("docs", [])
            if not docs:
                return results

            # Inspección concurrente de archivos en paralelo para no bloquear el bot
            async def _inspect_doc(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                identifier = doc.get("identifier")
                if not identifier:
                    return None

                title = doc.get("title") or identifier
                creator = clean_author_name(doc.get("creator") or "Desconocido")
                year = str(doc.get("year") or "").strip() or None

                try:
                    meta_url = f"https://archive.org/metadata/{identifier}"
                    meta_resp = await client.get(meta_url, timeout=3.5)
                    if meta_resp.status_code != 200:
                        return None

                    m_json = meta_resp.json()
                    meta_info = m_json.get("metadata", {})
                    # Descartar libros de préstamo cerrado / DRM
                    if (
                        meta_info.get("access-restricted-item") == "true"
                        or "printdisabled" in str(meta_info.get("collection", ""))
                        or "inlibrary" in str(meta_info.get("collection", ""))
                    ):
                        return None

                    files_data = m_json.get("files", [])
                    # Descartar archivos comprimidos masivos o compendios gigantescos
                    if len(files_data) > 80:
                        return None

                    epub_file = None
                    pdf_file = None

                    for f in files_data:
                        fname = f.get("name", "")
                        fmt = f.get("format", "")
                        fname_l = fname.lower()
                        if (
                            fname.startswith("_")
                            or fname_l.endswith((".xml", ".sqlite", ".torrent", "_chocr.html.gz", "_daisy.zip", "lcp.epub", "_encrypted.epub"))
                        ):
                            continue

                        try:
                            fsize = int(f.get("size", 0) or 0)
                        except (ValueError, TypeError):
                            fsize = 0

                        if fsize > MAX_DOWNLOAD_SIZE_BYTES or fsize < 10000:
                            continue

                        if fmt == "EPUB" or fname_l.endswith(".epub"):
                            if not epub_file or fsize > int(epub_file.get("size", 0) or 0):
                                epub_file = f
                        elif fmt in ["Text PDF", "Image Container PDF"] or fname_l.endswith(".pdf"):
                            if not pdf_file or fsize > int(pdf_file.get("size", 0) or 0):
                                pdf_file = f

                    chosen = epub_file or pdf_file
                    if chosen:
                        fname = chosen["name"]
                        fmt_clean = "epub" if (chosen.get("format") == "EPUB" or fname.lower().endswith(".epub")) else "pdf"
                        size_b = int(chosen.get("size", 0) or 0)
                        dl_url = f"https://archive.org/download/{identifier}/{urllib.parse.quote(fname, safe='/')}"

                        return {
                            "source": "Internet Archive",
                            "title": title,
                            "author": creator,
                            "year": year,
                            "format": fmt_clean,
                            "filename": fname,
                            "size_bytes": size_b,
                            "size_str": format_size(size_b) if size_b else "Descarga directa",
                            "download_url": dl_url,
                            "identifier": identifier
                        }
                except Exception:
                    return None
                return None

            tasks = [_inspect_doc(doc) for doc in docs[:limit + 3]]
            doc_results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in doc_results:
                if isinstance(r, dict) and r:
                    results.append(r)
                if len(results) >= limit:
                    break

    except Exception as e:
        logger.warning(f"Aviso buscando en Archive.org: {e}")

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
        async with httpx.AsyncClient(timeout=4.0, verify=False) as client:
            resp = await client.get(ol_url, params=params)
            if resp.status_code != 200:
                return results

            docs = resp.json().get("docs", [])

            async def _inspect_ol_doc(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                # Filtrar estrictamente solo libros de acceso público real (no DRM ni préstamo borrowable)
                ebook_access = d.get("ebook_access")
                is_public_scan = d.get("public_scan_b", False)
                if ebook_access != "public" and not is_public_scan:
                    return None

                ia_ids = d.get("ia", [])
                if not ia_ids:
                    return None

                best_ia = None
                for candidate_id in ia_ids:
                    if not candidate_id.endswith(("_daisy", "_chocr")):
                        best_ia = candidate_id
                        break

                if not best_ia:
                    return None

                title = d.get("title") or "Sin título"
                authors = d.get("author_name", [])
                author = clean_author_name(authors[0] if authors else "Desconocido")
                first_pub = str(d.get("first_publish_year") or "").strip() or None

                try:
                    meta_url = f"https://archive.org/metadata/{best_ia}"
                    meta_resp = await client.get(meta_url, timeout=3.0)
                    if meta_resp.status_code != 200:
                        return None

                    m_json = meta_resp.json()
                    meta_info = m_json.get("metadata", {})
                    if (
                        meta_info.get("access-restricted-item") == "true"
                        or "printdisabled" in str(meta_info.get("collection", ""))
                        or "inlibrary" in str(meta_info.get("collection", ""))
                    ):
                        return None

                    files_data = m_json.get("files", [])
                    chosen = None
                    for f in files_data:
                        fname = f.get("name", "")
                        fname_l = fname.lower()
                        fmt = f.get("format", "")
                        if fname_l.endswith(".epub") and not fname_l.endswith("lcp.epub"):
                            chosen = (f, "epub")
                            break
                        elif fmt in ["Text PDF", "Image Container PDF"] or fname_l.endswith(".pdf"):
                            if not chosen:
                                chosen = (f, "pdf")

                    if chosen:
                        f_obj, f_fmt = chosen
                        f_size = int(f_obj.get("size", 0) or 0)
                        if 10000 < f_size <= MAX_DOWNLOAD_SIZE_BYTES:
                            fname = f_obj["name"]
                            dl_url = f"https://archive.org/download/{best_ia}/{urllib.parse.quote(fname, safe='/')}"
                            return {
                                "source": "Open Library",
                                "title": title,
                                "author": author,
                                "year": first_pub,
                                "format": f_fmt,
                                "filename": fname,
                                "size_bytes": f_size,
                                "size_str": format_size(f_size),
                                "download_url": dl_url,
                                "identifier": f"ol_{best_ia}"
                            }
                except Exception:
                    return None
                return None

            tasks = [_inspect_ol_doc(d) for d in docs[:limit + 5]]
            doc_results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in doc_results:
                if isinstance(r, dict) and r:
                    results.append(r)
                if len(results) >= limit:
                    break

    except Exception as e:
        logger.warning(f"Aviso buscando en OpenLibrary: {e}")

    return results


async def search_project_gutenberg(query: str, limit: int = 2) -> List[Dict[str, Any]]:
    """Busca libros libres de dominio público en Project Gutenberg con alta velocidad y descarga garantizada."""
    results: List[Dict[str, Any]] = []
    clean_q = re.sub(r"[^\w\s]", " ", query).strip()
    if not clean_q:
        return results

    # 1. Búsqueda directa en gutenberg.org (muy rápida y siempre disponible)
    gutenberg_search_url = "https://www.gutenberg.org/ebooks/search/"
    params = {"query": clean_q, "submit_search": "Go!"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    try:
        from bs4 import BeautifulSoup
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True, headers=headers, verify=False) as client:
            resp = await client.get(gutenberg_search_url, params=params)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                book_items = soup.select("li.booklink")
                for item in book_items[:limit]:
                    a_link = item.select_one("a.link")
                    if not a_link or not a_link.get("href"):
                        continue
                    href = a_link["href"]
                    m_id = re.search(r"/ebooks/(\d+)", href)
                    if not m_id:
                        continue
                    ebook_id = m_id.group(1)

                    title_el = item.select_one(".title")
                    title = title_el.get_text(strip=True) if title_el else "Sin título"
                    title = re.sub(r"\s*\([A-Za-z]+\)\s*$", "", title).strip()

                    author_el = item.select_one(".subtitle")
                    author = clean_author_name(author_el.get_text(strip=True) if author_el else "Desconocido")

                    clean_fname = f"{re.sub(r'[^a-zA-Z0-9_\- ]', '', title)[:40].strip().replace(' ', '_')}.epub"
                    dl_url = f"https://www.gutenberg.org/ebooks/{ebook_id}.epub3.images"

                    results.append({
                        "source": "Project Gutenberg",
                        "title": title,
                        "author": author,
                        "year": None,
                        "format": "epub",
                        "filename": clean_fname,
                        "size_bytes": 1024 * 1024,
                        "size_str": "~1.5 MB",
                        "download_url": dl_url,
                        "identifier": f"gutenberg_{ebook_id}"
                    })
    except Exception as e:
        logger.debug(f"Aviso buscando directamente en Gutenberg: {e}")

    if results:
        return results

    # 2. Fallback a Gutendex
    gutendex_url = "https://gutendex.com/books/"
    params = {"search": clean_q}

    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True, verify=False) as client:
            resp = await client.get(gutendex_url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("results", [])

                for item in items[:limit]:
                    formats = item.get("formats", {})
                    epub_url = formats.get("application/epub+zip")
                    if not epub_url:
                        continue

                    authors_raw = item.get("authors", [])
                    author_name = "Desconocido"
                    if authors_raw:
                        author_name = clean_author_name(authors_raw[0].get("name", "Desconocido"))

                    title = item.get("title", "Sin título")
                    title = re.sub(r"\s+", " ", title).strip()
                    clean_fname = f"{re.sub(r'[^a-zA-Z0-9_\- ]', '', title)[:40].strip().replace(' ', '_')}.epub"

                    results.append({
                        "source": "Project Gutenberg",
                        "title": title,
                        "author": author_name,
                        "year": None,
                        "format": "epub",
                        "filename": clean_fname,
                        "size_bytes": 1024 * 1024,
                        "size_str": "~1.5 MB",
                        "download_url": epub_url,
                        "identifier": f"gutenberg_{item.get('id')}"
                    })

    except Exception as e:
        logger.debug(f"Aviso buscando en Gutendex fallback: {e}")

    return results


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

                    # Extraer año (columna 4 / índice 3)
                    year = None
                    if len(tds) > 3:
                        year_raw = tds[3].get_text(strip=True)
                        if year_raw:
                            y_match = re.search(r"\b(19\d\d|20\d\d)\b", year_raw)
                            year = y_match.group(1) if y_match else (year_raw if year_raw.isdigit() else None)

                    # Extraer tamaño (columna 7 / índice 6)
                    size_text = tds[6].get_text(strip=True) if len(tds) > 6 else ""
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


async def search_external_books(query: str, max_results: int = 5, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Busca libros en fuentes concurrentes (Internet Archive, Open Library, Gutenberg y LibGen)
    con límite de tiempo estricto e independiente por fuente para evitar que el bot se quede colgado.
    Preserva siempre los resultados parciales de las fuentes que respondan a tiempo.
    """
    effective_limit = limit if limit is not None else max_results

    async def _safe_search(coro, timeout_sec: float) -> List[Dict[str, Any]]:
        try:
            return await asyncio.wait_for(coro, timeout=timeout_sec)
        except Exception as e:
            logger.debug(f"Aviso en fuente de búsqueda externa ({timeout_sec}s): {e}")
            return []

    ia_task = _safe_search(search_internet_archive(query, limit=effective_limit), 6.0)
    ol_task = _safe_search(search_open_library(query, limit=3), 5.0)
    pg_task = _safe_search(search_project_gutenberg(query, limit=2), 3.0)
    lg_task = _safe_search(search_libgen(query, limit=effective_limit), 3.0)

    results_group = await asyncio.gather(ia_task, ol_task, pg_task, lg_task, return_exceptions=True)

    combined: List[Dict[str, Any]] = []
    for group in results_group:
        if isinstance(group, list):
            combined.extend(group)

    seen_keys = set()
    unique_results = []
    for item in combined:
        title_slug = normalize_genre_slug(item.get("title") or "")
        key = f"{title_slug}:{item.get('format', 'epub')}"
        if key not in seen_keys:
            seen_keys.add(key)
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

        filename = "libro_descargado.epub"
        cd = resp.headers.get("content-disposition", "")
        if "filename=" in cd:
            cd_match = re.search(r'filename=["\']?([^"\';]+)["\']?', cd)
            if cd_match:
                extracted = urllib.parse.unquote(cd_match.group(1).strip())
                if "." in extracted:
                    filename = extracted

        if filename == "libro_descargado.epub" and "/" in target_url:
            path_part = target_url.split("?")[0].rstrip("/")
            raw_fname = urllib.parse.unquote(path_part.split("/")[-1])
            if raw_fname and "." in raw_fname:
                filename = raw_fname

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
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "epub"

    internal_meta = extract_internal_book_metadata(file_bytes, ext)

    classification = await classify_book_with_gemini(
        filename=filename,
        caption=None,
        existing_topics=[t.genre for t in (await session.execute(select(Topic).where(Topic.telegram_link_id == link.id))).scalars().all()],
        internal_metadata=internal_meta
    )

    title = classification.get("title") or (original_meta.get("title") if original_meta else filename)
    author = classification.get("author") or (original_meta.get("author") if original_meta else "Desconocido")
    genre = classification.get("genre", "General")
    suggested_emoji = classification.get("emoji", "📖")
    pub_year = classification.get("publication_year") or (original_meta.get("year") if original_meta else "Desconocido")

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

    caption_text = format_book_full_description(
        book=classification,
        chat_books=existing_books,
        clean_chat_id=clean_chat_id,
        current_topic_name=genre,
        current_topic_emoji=suggested_emoji,
        for_caption=True
    )

    clean_file_obj = io.BytesIO(file_bytes)
    clean_file_obj.name = f"{re.sub(r'[^a-zA-Z0-9_\-. ]', '', title).strip()} - {re.sub(r'[^a-zA-Z0-9_\-. ]', '', author).strip()}.{ext}"

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
