"""
tests_unit_logic.py
tests unitarios para api/rag.py — logica central del proyecto limia.

como correrlos (desde la carpeta backend/):
  python manage.py test tests_unit_logic          (django test runner)
  python -m pytest tests_unit_logic.py -v         (si tenes pytest instalado)
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# arrancamos django antes de importar cualquier cosa del proyecto
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
import django
django.setup()

# funciones que vamos a testear
from api.rag import (
    _collect_source_files,
    extract_selectors,
    index_project,
)


# ─────────────────────────────────────────────────────────────────────────────
# helper para clasificar intent
#
# ojo: classify_intent() no existe como funcion propia en api/rag.py.
# la logica esta metida dentro de views.py::generate_test() usando TEST_WORDS.
# la copiamos aca para poder testearla sola. si algun dia se extrae a una
# funcion aparte, estos tests siguen funcionando igual.
# ─────────────────────────────────────────────────────────────────────────────
_TEST_WORDS = {
    "visit", "click", "type", "fill", "check", "verify", "test",
    "register", "login", "navigate", "assert", "submit", "enter",
    "select", "open", "form", "button", "field", "redirect", "page",
    "sign", "user", "password", "email", "input", "appear", "show",
}


def _classify_intent(instruction: str) -> bool:
    # devuelve true si el mensaje parece un comando de test, false si es charla
    return any(w in instruction.lower().split() for w in _TEST_WORDS)


# =============================================================================
# suite 1 — extract_selectors
#
# la funcion escanea archivos html/js y devuelve un string con el mapa del
# proyecto (no un diccionario). los tests verifican el contenido del string.
# =============================================================================

class TestExtractSelectors(unittest.TestCase):

    def test_detecta_id_de_input_con_tipo(self):
        """#email tiene que aparecer en el mapa con su tipo (email)."""
        html = '<input id="email" type="email" placeholder="Enter email">'
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "login.html").write_text(html, encoding="utf-8")
            result = extract_selectors(tmpdir)

        self.assertIn("#email", result)
        self.assertIn("type=email", result)

    def test_detecta_id_de_boton_con_texto(self):
        """#login-btn tiene que aparecer junto al texto visible 'Log In'."""
        html = '<button id="login-btn">Log In</button>'
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "login.html").write_text(html, encoding="utf-8")
            result = extract_selectors(tmpdir)

        self.assertIn("#login-btn", result)
        self.assertIn("Log In", result)

    def test_detecta_todos_los_ids_del_login(self):
        """pagina de login completa: #email, #password y #login-btn tienen que aparecer."""
        html = """
        <html><body>
          <input id="email" type="email" placeholder="Email">
          <input id="password" type="password" placeholder="Password">
          <button id="login-btn">Log In</button>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "login.html").write_text(html, encoding="utf-8")
            result = extract_selectors(tmpdir)

        for selector in ("#email", "#password", "#login-btn"):
            self.assertIn(selector, result, msg=f"falta el selector: {selector}")

    def test_detecta_todos_los_ids_del_register(self):
        """pagina de registro: #name, #email, #password y #register-btn tienen que aparecer."""
        html = """
        <input id="name" type="text" placeholder="Full name">
        <input id="email" type="email">
        <input id="password" type="password">
        <button id="register-btn">Register</button>
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "register.html").write_text(html, encoding="utf-8")
            result = extract_selectors(tmpdir)

        for selector in ("#name", "#email", "#password", "#register-btn"):
            self.assertIn(selector, result, msg=f"falta el selector: {selector}")

    def test_el_nombre_del_html_aparece_en_paginas_disponibles(self):
        """index.html tiene que aparecer listado bajo 'Available pages'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "index.html").write_text("<h1>Home</h1>", encoding="utf-8")
            result = extract_selectors(tmpdir)

        self.assertIn("Available pages", result)
        self.assertIn("index.html", result)

    def test_detecta_atributo_data_testid(self):
        """los data-testid tienen que quedar capturados en el mapa."""
        html = '<button data-testid="submit-btn">Submit</button>'
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "page.html").write_text(html, encoding="utf-8")
            result = extract_selectors(tmpdir)

        self.assertIn('data-testid="submit-btn"', result)

    def test_directorio_vacio_no_rompe_nada(self):
        """si no hay archivos, tiene que devolver el header del mapa sin explotar."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = extract_selectors(tmpdir)

        self.assertIn("PROJECT MAP", result)
        self.assertIn("END OF PROJECT MAP", result)
        # sin html no hay seccion de ids
        self.assertNotIn("Element IDs", result)

    def test_html_malformado_no_lanza_excepcion(self):
        """html roto (tags sin cerrar, comillas faltantes) no tiene que tirar error."""
        broken_html = "<div><input type=text id='x'><p>parrafo sin cerrar"
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "broken.html").write_text(broken_html, encoding="utf-8")
            try:
                result = extract_selectors(tmpdir)
            except Exception as exc:
                self.fail(f"extract_selectors exploto con html roto: {exc!r}")

        self.assertIsInstance(result, str)


# =============================================================================
# suite 2 — classify_intent
#
# testea la logica de deteccion de intent que esta en views.py::generate_test().
# usa el helper _classify_intent() definido arriba.
# =============================================================================

class TestClassifyIntent(unittest.TestCase):

    # casos positivos (tiene que devolver true)

    def test_detecta_la_palabra_test(self):
        """caso a: frase con 'test' tiene que ser clasificada como instruccion de test."""
        instruction = "I want to test the register flow in test_project"
        self.assertTrue(
            _classify_intent(instruction),
            "la instruccion tiene 'test', tiene que devolver true",
        )

    def test_detecta_la_palabra_login(self):
        """'login' es una palabra clave de test, tiene que devolver true."""
        self.assertTrue(_classify_intent("Please login with valid credentials"))

    def test_detecta_la_palabra_click(self):
        """'click' es una palabra clave de test, tiene que devolver true."""
        self.assertTrue(_classify_intent("Click the submit button and verify redirect"))

    def test_detecta_la_palabra_register(self):
        """'register' es una palabra clave de test, tiene que devolver true."""
        self.assertTrue(_classify_intent("Register a new user with valid data"))

    # casos negativos (tiene que devolver false)

    def test_mensaje_de_saludo_devuelve_false(self):
        """caso b: un saludo o pregunta no tiene que ser clasificado como test."""
        instruction = "Hello, how does this work?"
        self.assertFalse(
            _classify_intent(instruction),
            "es un mensaje de chat, tiene que devolver false",
        )

    def test_string_vacio_devuelve_false(self):
        """un string vacio no tiene palabras clave, tiene que devolver false."""
        self.assertFalse(_classify_intent(""))

    def test_palabra_parcial_no_hace_match(self):
        """
        'testing' como palabra completa no matchea con 'test'.
        el algoritmo compara palabras enteras, no subcadenas.
        """
        self.assertFalse(_classify_intent("I am just testing something unrelated"))

    # edge cases

    def test_la_comparacion_ignora_mayusculas(self):
        """una palabra en mayusculas (TEST) tiene que matchear igual."""
        self.assertTrue(_classify_intent("TEST the registration page"))

    def test_varias_palabras_clave_juntas(self):
        """una frase con muchas palabras clave igual tiene que devolver true."""
        self.assertTrue(
            _classify_intent("verify the login form and submit with valid email")
        )


# =============================================================================
# suite 3 — _collect_source_files
#
# helper interno que recolecta archivos del filesystem para index_project.
# =============================================================================

class TestCollectSourceFiles(unittest.TestCase):

    def test_encuentra_html_y_js(self):
        """tiene que recolectar html y js, pero ignorar .md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<h1>Hi</h1>", encoding="utf-8")
            (root / "app.js").write_text("console.log('hi')", encoding="utf-8")
            (root / "readme.md").write_text("# docs", encoding="utf-8")  # este no

            files = _collect_source_files(tmpdir)
            names = {f.name for f in files}

        self.assertIn("index.html", names)
        self.assertIn("app.js", names)
        self.assertNotIn("readme.md", names)

    def test_ignora_node_modules(self):
        """los archivos dentro de node_modules tienen que quedar afuera."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nm = root / "node_modules"
            nm.mkdir()
            (nm / "vendor.js").write_text("// vendor", encoding="utf-8")  # este no
            (root / "main.js").write_text("// proyecto", encoding="utf-8")

            files = _collect_source_files(tmpdir)
            names = {f.name for f in files}

        self.assertNotIn("vendor.js", names)
        self.assertIn("main.js", names)

    def test_directorio_vacio_devuelve_lista_vacia(self):
        """si no hay archivos tiene que devolver [] sin explotar."""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = _collect_source_files(tmpdir)

        self.assertEqual(files, [])

    def test_encuentra_archivos_en_subcarpetas(self):
        """tiene que bajar a subcarpetas y traer los archivos de ahi tambien."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / "js"
            subdir.mkdir()
            (subdir / "auth.js").write_text("// auth", encoding="utf-8")

            files = _collect_source_files(tmpdir)
            names = {f.name for f in files}

        self.assertIn("auth.js", names)


# =============================================================================
# suite 4 — index_project / chunker
#
# testea la configuracion del splitter (chunk_size=800, chunk_overlap=100)
# y la funcion index_project().
# chromadb y los embeddings de huggingface estan mockeados para que los
# tests sean rapidos y no necesiten modelos descargados.
# =============================================================================

class TestChunker(unittest.TestCase):

    # tests del splitter solo (sin mock)

    def test_ningun_chunk_supera_800_caracteres(self):
        """cada chunk que produce el splitter tiene que tener maximo 800 chars."""
        from langchain.text_splitter import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=100,
            separators=["\n\n", "\n", " ", ""],
        )
        content = "const x = 1;\n" * 90  # ~1260 chars, obliga a hacer mas de un chunk
        chunks = splitter.split_text(content)

        self.assertGreater(len(chunks), 1, "contenido de mas de 800 chars tiene que partirse")
        for chunk in chunks:
            self.assertLessEqual(
                len(chunk), 800,
                f"chunk de {len(chunk)} chars supera el limite de 800",
            )

    def test_el_overlap_conecta_chunks_consecutivos(self):
        """el final del chunk[0] tiene que aparecer en el chunk[1]."""
        from langchain.text_splitter import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=100,
            separators=["\n\n", "\n", " ", ""],
        )
        content = "word " * 300  # 1500 chars, produce al menos 2 chunks
        chunks = splitter.split_text(content)

        self.assertGreater(len(chunks), 1)
        # los ultimos 50 chars del chunk[0] tienen que aparecer en el chunk[1]
        tail = chunks[0][-50:]
        self.assertIn(
            tail, chunks[1],
            "el overlap no funciona: el final del chunk[0] no aparece en el chunk[1]",
        )

    # tests de index_project (con vector store mockeado)

    @patch("api.rag.get_vector_store")
    def test_index_project_devuelve_cantidad_de_chunks(self, mock_get_store):
        """index_project tiene que devolver cuantos chunks creo en total."""
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        with tempfile.TemporaryDirectory() as tmpdir:
            # archivo de ~1260 chars, se va a partir en mas de un chunk
            content = "const x = 1;\n" * 90
            (Path(tmpdir) / "app.js").write_text(content, encoding="utf-8")

            count = index_project(project_id=1, directory=tmpdir)

        self.assertGreater(count, 0)
        mock_store.add_documents.assert_called_once()

    @patch("api.rag.get_vector_store")
    def test_los_documentos_guardados_respetan_el_limite(self, mock_get_store):
        """cada documento que se manda al vector store tiene que tener max 800 chars."""
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        with tempfile.TemporaryDirectory() as tmpdir:
            content = "const x = 1;\n" * 90
            (Path(tmpdir) / "app.js").write_text(content, encoding="utf-8")
            index_project(project_id=1, directory=tmpdir)

        documents = mock_store.add_documents.call_args[0][0]
        for doc in documents:
            self.assertLessEqual(
                len(doc.page_content), 800,
                f"documento con {len(doc.page_content)} chars supera el limite de 800",
            )

    @patch("api.rag.get_vector_store")
    def test_los_documentos_tienen_metadata_obligatoria(self, mock_get_store):
        """cada documento tiene que tener 'source' y 'file_hash' en su metadata."""
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "login.html").write_text("<html></html>", encoding="utf-8")
            index_project(project_id=42, directory=tmpdir)

        documents = mock_store.add_documents.call_args[0][0]
        for doc in documents:
            self.assertIn("source", doc.metadata, "falta 'source' en la metadata")
            self.assertIn("file_hash", doc.metadata, "falta 'file_hash' en la metadata")

    @patch("api.rag.get_vector_store")
    def test_directorio_vacio_devuelve_cero_y_no_llama_al_store(self, mock_get_store):
        """si no hay archivos tiene que devolver 0 y no tocar el vector store."""
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        with tempfile.TemporaryDirectory() as tmpdir:
            count = index_project(project_id=1, directory=tmpdir)

        self.assertEqual(count, 0)
        mock_store.add_documents.assert_not_called()

    @patch("api.rag.get_vector_store")
    def test_node_modules_no_se_indexan(self, mock_get_store):
        """los archivos de node_modules no tienen que indexarse."""
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nm = root / "node_modules"
            nm.mkdir()
            (nm / "vendor.js").write_text("x" * 900, encoding="utf-8")  # si se indexara, generaria chunks

            count = index_project(project_id=1, directory=tmpdir)

        self.assertEqual(count, 0, "node_modules no tiene que indexarse")
        mock_store.add_documents.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
