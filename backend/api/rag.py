"""
RAG utilities: indexing a project directory into ChromaDB
and retrieving context for test generation.
"""

import hashlib
import re
from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document

CHROMA_PERSIST_DIR = Path(__file__).resolve().parent.parent / "chroma_store"

ALLOWED_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx", ".vue", ".html", ".css",
    ".py", ".json",
}

IGNORED_DIRS = {"node_modules", ".git", "__pycache__", "dist", "build", ".next"}


def _get_embeddings():
    return HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
    )


def get_vector_store(project_id: int) -> Chroma:
    return Chroma(
        collection_name=f"project_{project_id}",
        embedding_function=_get_embeddings(),
        persist_directory=str(CHROMA_PERSIST_DIR),
    )


def _file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _collect_source_files(directory: str) -> list[Path]:
    root = Path(directory)
    files = []
    for path in root.rglob("*"):
        if any(ignored in path.parts for ignored in IGNORED_DIRS):
            continue
        if path.is_file() and path.suffix in ALLOWED_EXTENSIONS:
            files.append(path)
    return files


def extract_selectors(directory: str) -> str:
    """
    Scan HTML and JS/TS files and return a structured project map injected
    directly into the LLM prompt. Covers: routes, element IDs with tag/type
    context, data-testid, visible button/link text, and JS UI messages.
    """
    root = Path(directory)
    ids: dict[str, str] = {}        # id_val -> human description
    data_testids: set[str] = set()
    html_routes: list[str] = []
    button_texts: set[str] = set()
    js_messages: set[str] = set()

    for path in root.rglob("*"):
        if any(ignored in path.parts for ignored in IGNORED_DIRS):
            continue
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if path.suffix == ".html":
            html_routes.append(path.relative_to(root).as_posix())

            # Elements with IDs that have inner text (buttons, spans, p, h*)
            for m in re.finditer(
                r'<(\w+)[^>]*\bid=["\']([^"\']+)["\'][^>]*>(.*?)</\1>',
                content, re.DOTALL | re.IGNORECASE,
            ):
                tag, id_val, inner = m.group(1).lower(), m.group(2), m.group(3)
                text = re.sub(r"<[^>]+>", "", inner).strip()
                desc = f"<{tag}>"
                if text:
                    desc += f" text={repr(text[:60])}"
                ids.setdefault(id_val, desc)

            # Inputs and self-closing buttons (may not have inner text)
            for m in re.finditer(
                r'<(input|button)[^>]*\bid=["\']([^"\']+)["\'][^>]*>',
                content, re.IGNORECASE,
            ):
                tag, id_val = m.group(1).lower(), m.group(2)
                attr_str = m.group(0)
                type_m = re.search(r'type=["\']([^"\']+)["\']', attr_str)
                ph_m = re.search(r'placeholder=["\']([^"\']+)["\']', attr_str)
                desc = f"<{tag}>"
                if type_m:
                    desc += f" type={type_m.group(1)}"
                if ph_m:
                    desc += f" placeholder={repr(ph_m.group(1)[:50])}"
                ids.setdefault(id_val, desc)

            data_testids.update(re.findall(r'data-testid=["\']([^"\']+)["\']', content))

            # Visible text of all buttons and links (for cy.contains fallback)
            for m in re.finditer(r'<button[^>]*>(.*?)</button>', content, re.DOTALL | re.IGNORECASE):
                text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if text:
                    button_texts.add(text)
            for m in re.finditer(r'<a[^>]*>(.*?)</a>', content, re.DOTALL | re.IGNORECASE):
                text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if text and len(text) < 60:
                    button_texts.add(text)

        if path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            # IDs set via setAttribute
            for id_val in re.findall(
                r'setAttribute\(["\']id["\'],\s*["\']([^"\']+)["\']', content
            ):
                ids.setdefault(id_val, "<element> (set via JS)")

            # UI messages assigned to textContent / innerText
            js_messages.update(re.findall(r'\.textContent\s*=\s*["\']([^"\']{4,})["\']', content))
            js_messages.update(re.findall(r'\.innerText\s*=\s*["\']([^"\']{4,})["\']', content))
            js_messages.update(re.findall(r'\.textContent\s*=\s*`([^`]{4,})`', content))

    lines = [
        "=== PROJECT MAP — use ONLY what is listed here, never invent selectors, routes, or text ===",
    ]

    if html_routes:
        lines.append("\nAvailable pages for cy.visit():")
        for route in sorted(html_routes):
            lines.append(f"  /{route}")

    if ids:
        lines.append("\nElement IDs — use as cy.get('#id'):")
        for id_val, desc in sorted(ids.items()):
            lines.append(f"  #{id_val}  {desc}")

    if data_testids:
        lines.append("\ndata-testid attributes — use as cy.get('[data-testid=\"x\"]'):")
        for item in sorted(data_testids):
            lines.append(f"  [data-testid=\"{item}\"]")

    if button_texts:
        lines.append("\nVisible button/link text — use cy.contains('exact text') only if no ID exists:")
        for text in sorted(button_texts):
            lines.append(f"  {repr(text)}")

    if js_messages:
        lines.append("\nUI messages set in JavaScript — use exact strings in assertions:")
        for msg in sorted(js_messages):
            lines.append(f"  {repr(msg)}")

    if not (ids or data_testids):
        lines.append("No IDs or data-testid found — use cy.contains() with the visible text listed above.")

    lines.append("\n=== END OF PROJECT MAP ===\n")
    return "\n".join(lines)


def index_project(project_id: int, directory: str) -> int:
    """
    Chunk and embed all source files in `directory` into the project's
    ChromaDB collection.  Returns the number of chunks indexed.
    """
    files = _collect_source_files(directory)
    if not files:
        return 0

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n", "\n", " ", ""],
    )

    documents: list[Document] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        chunks = splitter.split_text(content)
        for chunk in chunks:
            documents.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "source": str(path),
                        "file_hash": _file_hash(path),
                    },
                )
            )

    store = get_vector_store(project_id)
    store.add_documents(documents)
    return len(documents)
