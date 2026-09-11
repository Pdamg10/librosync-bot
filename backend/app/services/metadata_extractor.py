import io
import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional
import pypdf

logger = logging.getLogger(__name__)

def is_generic_or_cryptic_filename(filename: str) -> bool:
    """Detecta si el nombre del archivo es ambiguo, genérico, o puro número/hash."""
    name_no_ext = filename.rsplit(".", 1)[0].strip().lower()
    if len(name_no_ext) <= 3:
        return True

    generic_patterns = [
        r"^cap[ií]tulo[\s_\-]*\d*",
        r"^chapter[\s_\-]*\d*",
        r"^scan[\s_\-]*\d*",
        r"^doc[\s_\-]*\d*",
        r"^documento[\s_\-]*\d*",
        r"^libro[\s_\-]*\d*",
        r"^book[\s_\-]*\d*",
        r"^archivo[\s_\-]*\d*",
        r"^file[\s_\-]*\d*",
        r"^img[\s_\-]*\d*",
        r"^parte?[\s_\-]*\d*",
        r"^vol(umen)?[\s_\-]*\d*",
        r"^descarga[\s_\-]*\d*",
        r"^download[\s_\-]*\d*",
        r"^[0-9\-_.]+$",
        r"^[a-f0-9]{8,}$",
        r"^sin[\s_\-]*(t[ií]tulo|nombre)",
        r"^untitled",
    ]
    for pat in generic_patterns:
        if re.search(pat, name_no_ext):
            return True

    if re.search(r"\d{6,}", name_no_ext):
        return True

    return False


def extract_internal_book_metadata(file_bytes: bytes, file_format: str) -> Dict[str, Any]:
    """
    Inspecciona los metadatos internos del archivo y el texto de las primeras páginas
    para rescatar el título y autor cuando el nombre de archivo es genérico (ej: 'Capitulo 1.pdf').
    """
    result: Dict[str, Any] = {
        "internal_title": None,
        "internal_author": None,
        "internal_genre": None,
        "internal_date": None,
        "text_snippet": None
    }
    fmt = (file_format or "").lower().replace(".", "")

    if fmt == "epub":
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                # 1. Localizar el archivo de metadatos OPF
                if "META-INF/container.xml" in zf.namelist():
                    container_xml = zf.read("META-INF/container.xml")
                    tree = ET.fromstring(container_xml)
                    rootfile = tree.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
                    if rootfile is not None and "full-path" in rootfile.attrib:
                        opf_path = rootfile.attrib["full-path"]
                        opf_xml = zf.read(opf_path)
                        opf_tree = ET.fromstring(opf_xml)

                        title_el = opf_tree.find(".//{http://purl.org/dc/elements/1.1/}title")
                        creator_el = opf_tree.find(".//{http://purl.org/dc/elements/1.1/}creator")
                        subject_el = opf_tree.find(".//{http://purl.org/dc/elements/1.1/}subject")
                        desc_el = opf_tree.find(".//{http://purl.org/dc/elements/1.1/}description")
                        date_el = opf_tree.find(".//{http://purl.org/dc/elements/1.1/}date")

                        if title_el is not None and title_el.text:
                            result["internal_title"] = title_el.text.strip()
                        if creator_el is not None and creator_el.text:
                            result["internal_author"] = creator_el.text.strip()
                        if subject_el is not None and subject_el.text:
                            result["internal_genre"] = subject_el.text.strip()
                        if desc_el is not None and desc_el.text:
                            result["text_snippet"] = desc_el.text.strip()[:600]
                        if date_el is not None and date_el.text:
                            m_yr = re.search(r"\b(1[89]\d{2}|20\d{2})\b", date_el.text)
                            result["internal_date"] = m_yr.group(1) if m_yr else date_el.text.strip()[:10]

                # 2. Si no hubo descripción, buscar las primeras páginas de texto HTML/XHTML
                if not result.get("text_snippet"):
                    html_files = [n for n in zf.namelist() if n.endswith((".html", ".xhtml", ".htm")) and not n.startswith("__")]
                    html_files.sort()
                    for hf in html_files[:2]:
                        try:
                            raw_html = zf.read(hf).decode("utf-8", errors="ignore")
                            # Remover etiquetas HTML
                            clean_text = re.sub(r"<[^>]+>", " ", raw_html)
                            clean_text = re.sub(r"\s+", " ", clean_text).strip()
                            if len(clean_text) > 40:
                                result["text_snippet"] = clean_text[:600]
                                break
                        except Exception:
                            continue
        except Exception as e:
            logger.warning(f"Error extrayendo metadatos EPUB: {e}")

    elif fmt == "pdf":
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            meta = reader.metadata
            if meta:
                if getattr(meta, "title", None) and str(meta.title).strip():
                    result["internal_title"] = str(meta.title).strip()
                if getattr(meta, "author", None) and str(meta.author).strip():
                    result["internal_author"] = str(meta.author).strip()
                if getattr(meta, "subject", None) and str(meta.subject).strip():
                    result["internal_genre"] = str(meta.subject).strip()
                for d_attr in ["creation_date", "modification_date"]:
                    val = getattr(meta, d_attr, None)
                    if val:
                        m_d = re.search(r"\b(1[89]\d{2}|20\d{2})\b", str(val))
                        if m_d:
                            result["internal_date"] = m_d.group(1)
                            break

            # Extraer texto de las primeras 3 páginas (portada, créditos, dedicatoria)
            snippet_parts = []
            for p in reader.pages[:3]:
                try:
                    txt = p.extract_text() or ""
                    clean = re.sub(r"\s+", " ", txt).strip()
                    if clean:
                        snippet_parts.append(clean)
                except Exception:
                    continue

            if snippet_parts:
                full_text = " --- ".join(snippet_parts)
                result["text_snippet"] = full_text[:800]
                if not result.get("internal_date"):
                    m_c = re.search(
                        r"(?:©|copyright|\(c\)|primera\s+edici[oó]n|publicad[oa]\s+en|año\s+de\s+publicaci[oó]n)\s*[:.]?\s*(?:de\s*)?(1[89]\d{2}|20\d{2})\b",
                        full_text,
                        re.IGNORECASE
                    )
                    if m_c:
                        result["internal_date"] = m_c.group(1)

        except Exception as e:
            logger.warning(f"Error extrayendo metadatos PDF: {e}")

    return result
