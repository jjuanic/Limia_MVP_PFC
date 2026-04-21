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
    Scan HTML and JS files for real IDs, data-testid, and dynamic class assignments.
    Returns a plain-text summary injected directly into the LLM prompt so the model
    doesn't have to infer selectors from code chunks.
    """
    root = Path(directory)
    ids: set[str] = set()
    data_testids: set[str] = set()
    js_classes: set[str] = set()

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
            ids.update(re.findall(r'\bid=["\']([^"\']+)["\']', content))
            data_testids.update(re.findall(r'data-testid=["\']([^"\']+)["\']', content))

        if path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            # btn classes added via JS: element.classList.add('foo') or className = 'foo'
            js_classes.update(re.findall(r'classList\.add\(["\']([^"\']+)["\']', content))
            js_classes.update(re.findall(r'\.className\s*=\s*["\']([^"\']+)["\']', content))
            # setAttribute('id', 'foo')
            ids.update(re.findall(r'setAttribute\(["\']id["\'],\s*["\']([^"\']+)["\']', content))

    lines = ["=== SELECTORS EXTRACTED FROM PROJECT SOURCE (use these, do not invent others) ==="]
    if ids:
        lines.append("\nElement IDs (use as #id in Cypress):")
        for item in sorted(ids):
            lines.append(f"  #{item}")
    if data_testids:
        lines.append("\ndata-testid attributes:")
        for item in sorted(data_testids):
            lines.append(f"  [data-testid={item}]")
    if js_classes:
        lines.append("\nCSS classes assigned dynamically in JS (use as .classname):")
        for item in sorted(js_classes):
            lines.append(f"  .{item}")
    if not (ids or data_testids or js_classes):
        lines.append("No IDs or data-testid attributes found — use cy.contains() with visible text.")
    lines.append("=== END OF SELECTORS ===\n")
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
