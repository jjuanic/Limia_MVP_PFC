"""
tests_benchmark_metrics.py
benchmark para validar las metricas de la seccion 14.4.2 del informe.

sin mocks: chromadb y embeddings reales. ollama es opcional.

uso (desde backend/):
  python tests_benchmark_metrics.py
  python tests_benchmark_metrics.py --skip-llm
"""

import os
import re
import sys
import json
import time
import shutil
import logging
import warnings
import tempfile
import unittest
import urllib.request
from pathlib import Path

# silenciar todo antes de cualquier import de terceros
warnings.simplefilter("ignore")
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
logging.getLogger("chromadb").setLevel(logging.CRITICAL)
logging.getLogger("langchain").setLevel(logging.CRITICAL)

import django
django.setup()

import api.rag as rag_module
from api.rag import index_project, extract_selectors
from langchain_chroma import Chroma

# parchar telemetria de chromadb para que no imprima nada al stderr
try:
    from chromadb.telemetry.product import posthog as _posthog  # type: ignore[import]
    _posthog.Posthog.capture = lambda *_: None
except Exception:
    pass

# flag global: omite la suite de ollama si se pasa --skip-llm
SKIP_LLM = "--skip-llm" in sys.argv


def _ollama_available() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434", timeout=2)
        return True
    except Exception:
        return False


def _detect_model() -> str | None:
    """consulta /api/tags y devuelve el modelo preferido o el primero disponible."""
    preferred = "deepseek-coder:6.7b"
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as resp:
            data = json.loads(resp.read())
        available = [m["name"] for m in data.get("models", [])]
        if preferred in available:
            return preferred
        return available[0] if available else None
    except Exception:
        return None


OLLAMA_AVAILABLE = not SKIP_LLM and _ollama_available()
OLLAMA_MODEL = _detect_model() if OLLAMA_AVAILABLE else None


# ─── html/js de referencia de la taskapp ─────────────────────────────────────

TASKAPP_FILES = {
    "login.html": (
        '<!DOCTYPE html><html><body>'
        '<input id="email" type="email" placeholder="Email">'
        '<input id="password" type="password" placeholder="Password">'
        '<button id="login-btn">Log In</button>'
        '<span id="login-error"></span>'
        '</body></html>'
    ),
    "register.html": (
        '<!DOCTYPE html><html><body>'
        '<input id="name" type="text" placeholder="Full name">'
        '<input id="email" type="email" placeholder="Email">'
        '<input id="password" type="password" placeholder="Password">'
        '<button id="register-btn">Register</button>'
        '<span id="register-error"></span>'
        '</body></html>'
    ),
    "index.html": (
        '<!DOCTYPE html><html><body>'
        '<input id="task-input" type="text" placeholder="New task...">'
        '<button id="add-task-btn">Add Task</button>'
        '<ul id="task-list"></ul>'
        '<button id="logout-btn">Logout</button>'
        '<span id="success-msg"></span>'
        '</body></html>'
    ),
    "app.js": "\n".join([
        "document.getElementById('login-btn').addEventListener('click', () => {",
        "  const email = document.getElementById('email').value;",
        "  const password = document.getElementById('password').value;",
        "  if (email && password) { window.location.href = 'index.html'; }",
        "  else { document.getElementById('login-error').textContent = 'Invalid credentials'; }",
        "});",
        "document.getElementById('add-task-btn').addEventListener('click', () => {",
        "  const input = document.getElementById('task-input').value;",
        "  if (input) { document.getElementById('success-msg').textContent = 'Task added successfully'; }",
        "});",
    ]),
}

# lista blanca de ids reales para detectar alucinaciones
REAL_IDS = {
    "email", "password", "login-btn", "login-error",
    "name", "register-btn", "register-error",
    "task-input", "add-task-btn", "task-list", "logout-btn", "success-msg",
}

# 10 consultas y los ids que deben aparecer en los chunks recuperados
QUERIES = [
    ("test user login with valid email and password",     ["email", "password", "login-btn"]),
    ("verify login shows error with invalid credentials", ["login-error"]),
    ("test register a new user with name email password", ["name", "email", "register-btn"]),
    ("verify register form validation error message",     ["register-error"]),
    ("test adding a new task to the list",                ["task-input", "add-task-btn"]),
    ("verify success message after adding a task",        ["success-msg"]),
    ("test logout button on the main page",               ["logout-btn"]),
    ("verify task list is visible after login",           ["task-list"]),
    ("test that login redirects to index page",           ["login-btn", "email"]),
    ("test submit registration and navigate to login",    ["register-btn"]),
]


# ─── helpers compartidos ──────────────────────────────────────────────────────

def _analyze_hallucinations(cypress_code: str) -> dict:
    """extrae cy.get('#id') y calcula cuantos no existen en la lista blanca."""
    used_ids = set(re.findall(r"cy\.get\(['\"]#([\w-]+)['\"]", cypress_code))
    hallucinated = used_ids - REAL_IDS
    rate = (len(hallucinated) / len(used_ids) * 100) if used_ids else 0.0
    return {"used_ids": used_ids, "hallucinated": hallucinated, "rate": round(rate, 1)}


def _setup_taskapp(project_id: int):
    """crea directorios temporales, escribe la taskapp e indexa en chroma."""
    tmp_dir = tempfile.mkdtemp(prefix="limia_benchmark_")
    app_dir = Path(tmp_dir) / "taskapp"
    chroma_dir = Path(tmp_dir) / "chroma"
    app_dir.mkdir()
    chroma_dir.mkdir()

    for filename, content in TASKAPP_FILES.items():
        (app_dir / filename).write_text(content, encoding="utf-8")

    # redirigir chroma a dir temporal para no contaminar datos reales
    original = rag_module.CHROMA_PERSIST_DIR
    rag_module.CHROMA_PERSIST_DIR = chroma_dir
    try:
        chunk_count = index_project(project_id, str(app_dir))
    finally:
        rag_module.CHROMA_PERSIST_DIR = original

    store = Chroma(
        collection_name=f"project_{project_id}",
        embedding_function=rag_module._get_embeddings(),
        persist_directory=str(chroma_dir),
    )
    return tmp_dir, app_dir, store, chunk_count


# =============================================================================
# suite 1 — rag hit rate (chromadb y embeddings reales, sin mocks)
# =============================================================================

class TestRAGHitRate(unittest.TestCase):

    PROJECT_ID = 9001

    @classmethod
    def setUpClass(cls):
        warnings.simplefilter("ignore")
        cls._tmp_dir, cls._app_dir, cls._store, cls._chunk_count = _setup_taskapp(
            cls.PROJECT_ID
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp_dir, ignore_errors=True)

    def test_indexing_produces_chunks(self):
        self.assertGreater(self._chunk_count, 0)
        print(f"  Chunks indexados:          {self._chunk_count}")

    def test_semantic_retrieval_10_queries(self):
        hits = 0
        failures = []

        for instruction, expected_ids in QUERIES:
            docs = self._store.similarity_search(instruction, k=4)
            content = " ".join(d.page_content for d in docs)

            missing_ids = [
                id_ for id_ in expected_ids
                if f'id="{id_}"' not in content and f"id='{id_}'" not in content
            ]

            with self.subTest(instruction=instruction):
                self.assertListEqual(
                    missing_ids, [],
                    f"ids no encontrados en chunks: {missing_ids}",
                )

            if not missing_ids:
                hits += 1
            else:
                failures.append((instruction, missing_ids))

        rate = hits / len(QUERIES) * 100
        print(f"  Recuperacion semantica:    {hits}/{len(QUERIES)} consultas correctas ({rate:.0f}%)")
        for instruction, missing in failures:
            print(f"    Sin contexto: '{instruction[:50]}' — faltan {missing}")


# =============================================================================
# suite 2 — hallucination rate
# =============================================================================

class TestHallucinationRate(unittest.TestCase):

    def test_clean_code_gives_0_percent(self):
        cypress = (
            "cy.visit('/login.html')\n"
            "cy.get('#email').type('a@b.com')\n"
            "cy.get('#password').type('pass')\n"
            "cy.get('#login-btn').click()\n"
        )
        result = _analyze_hallucinations(cypress)
        self.assertEqual(result["rate"], 0.0)
        # tasa de falsos positivos: ids reales marcados incorrectamente como falsos
        print(f"  Tasa de falsos positivos en scripts reales:  {result['rate']:.0f}%")

    def test_detects_invented_ids(self):
        known_fake_ids = {"email-input", "pass-field"}
        cypress_with_errors = (
            "cy.get('#email-input').type('a@b.com')\n"   # id inventado
            "cy.get('#pass-field').type('pass')\n"        # id inventado
            "cy.get('#login-btn').click()\n"              # id real
        )
        result = _analyze_hallucinations(cypress_with_errors)
        self.assertIn("email-input", result["hallucinated"])
        self.assertIn("pass-field", result["hallucinated"])
        self.assertNotIn("login-btn", result["hallucinated"])

        # precision = cuantos ids falsos conocidos fueron detectados
        detected = known_fake_ids & result["hallucinated"]
        precision = len(detected) / len(known_fake_ids) * 100
        print(f"  Precision de deteccion de IDs falsos:        {precision:.0f}%")

    def test_5_typical_scripts_below_5_percent(self):
        scripts = [
            "cy.get('#email').type('a@b.com')\ncy.get('#password').type('p')\ncy.get('#login-btn').click()",
            "cy.get('#name').type('x')\ncy.get('#email').type('a@b.com')\ncy.get('#register-btn').click()",
            "cy.get('#task-input').type('task')\ncy.get('#add-task-btn').click()\ncy.get('#success-msg').should('be.visible')",
            "cy.get('#login-btn').click()\ncy.get('#login-error').should('be.visible')",
            "cy.get('#task-list').should('be.visible')\ncy.get('#logout-btn').click()",
        ]

        total_ids = 0
        total_hallucinated = 0
        for script in scripts:
            result = _analyze_hallucinations(script)
            total_ids += len(result["used_ids"])
            total_hallucinated += len(result["hallucinated"])

        global_rate = (total_hallucinated / total_ids * 100) if total_ids else 0.0
        print(f"  Tasa de falsos positivos (5 scripts tipicos): {global_rate:.0f}%")
        self.assertLess(global_rate, 5.0, "la tasa supera el umbral del 5%")


# =============================================================================
# suite 3 — latency benchmark (requiere ollama corriendo)
# =============================================================================

@unittest.skipUnless(
    OLLAMA_AVAILABLE and OLLAMA_MODEL,
    "Ollama no disponible o sin modelos instalados",
)
class TestLatencyBenchmark(unittest.TestCase):

    PROJECT_ID = 9002

    @classmethod
    def setUpClass(cls):
        warnings.simplefilter("ignore")
        cls._tmp_dir, cls._app_dir, cls._store, _ = _setup_taskapp(cls.PROJECT_ID)
        cls._selectors = extract_selectors(str(cls._app_dir))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp_dir, ignore_errors=True)

    def test_ttft_and_total_time(self):
        import requests

        instruction = "test user login with valid email and password"

        # paso 1: recuperacion semantica (tiempo propio del rag)
        t_retrieval_start = time.perf_counter()
        docs = self._store.similarity_search(instruction, k=4)
        t_retrieval = time.perf_counter() - t_retrieval_start

        # construir el prompt completo igual que el sistema en produccion
        context = "\n\n".join(d.page_content for d in docs)
        full_prompt = (
            f"{self._selectors}\n"
            f"Source code context:\n{context}\n"
            f"REQUIREMENT: {instruction}"
        )

        # paso 2: streaming directo a ollama — mide ttft y tiempo de generacion
        t_llm_start = time.perf_counter()
        t_first_token = None
        full_response = ""

        with requests.post(
            "http://localhost:11434/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": full_prompt},
            stream=True,
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                token = data.get("response", "")
                if t_first_token is None and token.strip():
                    t_first_token = time.perf_counter()
                full_response += token
                if data.get("done"):
                    break

        t_llm_total = time.perf_counter() - t_llm_start
        ttft = (t_first_token - t_llm_start) if t_first_token else None
        t_pipeline_total = t_retrieval + t_llm_total

        print(f"  Recuperacion RAG:          {t_retrieval:.3f}s")
        if ttft:
            print(f"  TTFT:                      {ttft:.3f}s  (referencia: ~2.23s)")
        else:
            print("  TTFT:                      no capturado")
        print(f"  Tiempo generacion LLM:     {t_llm_total:.3f}s")
        print(f"  Tiempo total pipeline:     {t_pipeline_total:.3f}s  (referencia: ~40.85s)")

        self.assertLess(t_pipeline_total, 180.0, "el pipeline tardo mas de 180s")
        if ttft:
            self.assertGreater(ttft, 0.0)


# =============================================================================
# runner personalizado — output limpio en espanol
# =============================================================================

class _QuietResult(unittest.TestResult):
    """recolecta resultados sin imprimir nombres tecnicos de los tests."""

    def addError(self, test, err):
        super().addError(test, err)
        exc_type, exc_val, _ = err
        print(f"  ERROR: {exc_type.__name__}: {exc_val}")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        _, exc_val, _ = err
        print(f"  FALLO: {exc_val}")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        print(f"  Omitido: {reason}")


_SECTION_HEADERS = {
    "TestHallucinationRate": "Alucinaciones",
    "TestRAGHitRate":        "Motor RAG",
    "TestLatencyBenchmark":  "Latencia",
}


if __name__ == "__main__":
    sys.argv = [a for a in sys.argv if a != "--skip-llm"]
    warnings.simplefilter("ignore")

    print()
    print("=" * 60)
    print("  LIMIA — Benchmark de Metricas RAG  (Seccion 14.4.2)")
    modelo_str = OLLAMA_MODEL or "ninguno (Ollama no disponible)"
    print(f"  Modelo: {modelo_str}")
    print("=" * 60)

    # cargar y ordenar suites para que el header aparezca antes de sus tests
    loader = unittest.TestLoader()
    suite_order = [TestHallucinationRate, TestRAGHitRate, TestLatencyBenchmark]
    result = _QuietResult()
    t_total_start = time.perf_counter()

    for test_class in suite_order:
        header = _SECTION_HEADERS[test_class.__name__]
        print(f"\n  [{header}]")
        suite = loader.loadTestsFromTestCase(test_class)
        suite.run(result)

    t_elapsed = time.perf_counter() - t_total_start

    # resumen final
    total = result.testsRun
    failed = len(result.errors) + len(result.failures)
    skipped = len(result.skipped)

    print()
    print("=" * 60)
    if failed:
        print(f"  {total} pruebas en {t_elapsed:.1f}s — {failed} FALLARON")
    else:
        extra = f"  ({skipped} omitidas)" if skipped else ""
        print(f"  {total} pruebas en {t_elapsed:.1f}s — TODAS PASARON{extra}")
    print("=" * 60)
    print()

    sys.exit(1 if failed else 0)
