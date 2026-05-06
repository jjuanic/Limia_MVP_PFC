"""
tests_integration_api.py
pruebas de integracion para los endpoints de la api de limia.
validan que views, modelos y el motor rag interactuen correctamente.

como correrlos (desde la carpeta backend/):
  python manage.py test tests_integration_api          (django test runner)
  python -m pytest tests_integration_api.py -v         (si tenes pytest instalado)
"""

import json
import os
from unittest.mock import MagicMock, patch

# arrancar django antes de importar nada del proyecto
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
import django
django.setup()

from rest_framework.test import APITestCase
from api.models import Project, TestRequest


# ─── datos de prueba reutilizables ────────────────────────────────────────────

# script cypress falso que devuelve el llm mockeado
FAKE_CYPRESS_CODE = """describe('Login flow', () => {
  it('should login successfully', () => {
    cy.visit('/login.html')
    cy.get('#email').type('test@example.com')
    cy.get('#password').type('password123')
    cy.get('#login-btn').click()
    cy.url().should('include', 'index.html')
  })
})"""

# mapa de proyecto falso que devuelve extract_selectors mockeado
FAKE_SELECTORS = """=== PROJECT MAP ===
Available pages: login.html, register.html, index.html
Element IDs: #email (input, type=email), #password (input, type=password), #login-btn (button, text="Log In")
=== END OF PROJECT MAP ==="""


# =============================================================================
# suite 1 — sync_project (POST /api/projects/:id/sync/)
#
# verifica que el endpoint indexe el proyecto y actualice last_synced_at.
# index_project esta mockeado — no toca chromadb ni el filesystem real.
# =============================================================================

class SyncProjectIntegrationTest(APITestCase):

    def setUp(self):
        # creamos el proyecto en la db de prueba antes de cada test
        self.project = Project.objects.create(
            name="test_project",
            directory_path="/fake/test_project",
        )
        self.url = f"/api/projects/{self.project.id}/sync/"

    @patch("api.views.index_project", return_value=12)
    def test_sync_returns_200(self, mock_index):
        """el sync de un proyecto existente tiene que responder 200."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)

    @patch("api.views.index_project", return_value=12)
    def test_sync_actualiza_last_synced_at_en_db(self, mock_index):
        """despues del sync, last_synced_at del proyecto tiene que estar seteado."""
        self.assertIsNone(self.project.last_synced_at)

        self.client.post(self.url)

        # recargamos desde la db para verificar el cambio real
        self.project.refresh_from_db()
        self.assertIsNotNone(self.project.last_synced_at)

    @patch("api.views.index_project", return_value=12)
    def test_sync_devuelve_cantidad_de_chunks(self, mock_index):
        """la respuesta json tiene que incluir cuantos chunks se indexaron."""
        response = self.client.post(self.url)
        data = response.json()

        self.assertIn("chunks_indexed", data)
        self.assertEqual(data["chunks_indexed"], 12)

    @patch("api.views.index_project", return_value=5)
    def test_sync_llama_a_index_project_con_los_argumentos_correctos(self, mock_index):
        """index_project tiene que recibir el id y el path del proyecto."""
        self.client.post(self.url)
        mock_index.assert_called_once_with(self.project.id, self.project.directory_path)


# =============================================================================
# suite 2 — generate_test (POST /api/projects/:id/generate/)
#
# simula el flujo completo de generacion de tests cypress.
# mocks: get_vector_store, extract_selectors, Ollama y RetrievalQA.
# la db de prueba se limpia automaticamente entre tests (APITestCase).
# =============================================================================

class GenerateTestIntegrationTest(APITestCase):

    def setUp(self):
        self.project = Project.objects.create(
            name="test_project",
            directory_path="/fake/test_project",
        )
        self.url = f"/api/projects/{self.project.id}/generate/"

    def _mock_rag_chain(self, mock_ollama, mock_get_store, mock_rag, mock_selectors,
                        llm_output=FAKE_CYPRESS_CODE):
        """helper para configurar los mocks del flujo rag de una sola vez."""
        mock_selectors.return_value = FAKE_SELECTORS
        mock_chain = MagicMock()
        mock_chain.run.return_value = llm_output
        mock_rag.from_chain_type.return_value = mock_chain
        return mock_chain

    @patch("api.views.extract_selectors", return_value=FAKE_SELECTORS)
    @patch("api.views.RetrievalQA")
    @patch("api.views.get_vector_store")
    @patch("api.views.Ollama")
    def test_generate_retorna_201_y_cypress_code(self, mock_ollama, mock_get_store, mock_rag, mock_selectors):
        """el endpoint tiene que devolver 201 con cypress_code en el json."""
        mock_chain = self._mock_rag_chain(mock_ollama, mock_get_store, mock_rag, mock_selectors)

        response = self.client.post(
            self.url,
            data={"instruction": "test the login flow with valid email and password"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn("cypress_code", response.json())

    @patch("api.views.extract_selectors", return_value=FAKE_SELECTORS)
    @patch("api.views.RetrievalQA")
    @patch("api.views.get_vector_store")
    @patch("api.views.Ollama")
    def test_generate_response_type_es_code(self, mock_ollama, mock_get_store, mock_rag, mock_selectors):
        """cuando el llm devuelve codigo cypress, response_type tiene que ser 'code'."""
        self._mock_rag_chain(mock_ollama, mock_get_store, mock_rag, mock_selectors)

        response = self.client.post(
            self.url,
            data={"instruction": "test the login flow"},
            format="json",
        )

        self.assertEqual(response.json()["response_type"], "code")

    @patch("api.views.extract_selectors", return_value=FAKE_SELECTORS)
    @patch("api.views.RetrievalQA")
    @patch("api.views.get_vector_store")
    @patch("api.views.Ollama")
    def test_generate_crea_test_request_en_db(self, mock_ollama, mock_get_store, mock_rag, mock_selectors):
        """la generacion tiene que persistir un TestRequest en la db."""
        self._mock_rag_chain(mock_ollama, mock_get_store, mock_rag, mock_selectors)

        response = self.client.post(
            self.url,
            data={"instruction": "test the login flow"},
            format="json",
        )

        data = response.json()
        self.assertIn("test_request_id", data)

        # verificar que el registro existe de verdad en la db
        saved = TestRequest.objects.filter(id=data["test_request_id"]).exists()
        self.assertTrue(saved, "el TestRequest no se guardo en la db")

    @patch("api.views.extract_selectors", return_value=FAKE_SELECTORS)
    @patch("api.views.RetrievalQA")
    @patch("api.views.get_vector_store")
    @patch("api.views.Ollama")
    def test_generate_inyecta_selectores_en_el_prompt(self, mock_ollama, mock_get_store, mock_rag, mock_selectors):
        """el prompt que llega al llm tiene que contener los selectores y la instruccion."""
        mock_chain = self._mock_rag_chain(mock_ollama, mock_get_store, mock_rag, mock_selectors)
        instruction = "test the login flow"

        self.client.post(self.url, data={"instruction": instruction}, format="json")

        # el argumento que recibio chain.run tiene que tener ambas partes
        prompt_enviado = mock_chain.run.call_args[0][0]
        self.assertIn(FAKE_SELECTORS, prompt_enviado)
        self.assertIn(instruction, prompt_enviado)

    @patch("api.views.extract_selectors", return_value=FAKE_SELECTORS)
    @patch("api.views.RetrievalQA")
    @patch("api.views.get_vector_store")
    @patch("api.views.Ollama")
    def test_generate_response_type_es_plan_cuando_llm_devuelve_plan_needed(
        self, mock_ollama, mock_get_store, mock_rag, mock_selectors
    ):
        """si el llm responde 'PLAN_NEEDED:', response_type tiene que ser 'plan'."""
        plan_output = "PLAN_NEEDED:\nNo se pudo mapear el paso 'clic en boton fantasma'."
        self._mock_rag_chain(mock_ollama, mock_get_store, mock_rag, mock_selectors, llm_output=plan_output)

        response = self.client.post(
            self.url,
            data={"instruction": "click the ghost button"},
            format="json",
        )

        self.assertEqual(response.json()["response_type"], "plan")

    @patch("api.views.Ollama")
    def test_generate_modo_chat_para_instruccion_sin_palabras_clave(self, mock_ollama):
        """un mensaje de chat sin palabras clave tiene que devolver response_type 'chat'."""
        # configuramos el llm para responder como chat
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.return_value = "I help you generate Cypress tests!"
        mock_ollama.return_value = mock_llm_instance

        response = self.client.post(
            self.url,
            data={"instruction": "Hello, what can you do?"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["response_type"], "chat")

    @patch("api.views.Ollama")
    def test_generate_modo_chat_no_llama_al_vector_store(self, mock_ollama):
        """en modo chat, get_vector_store no tiene que llamarse (no hay rag)."""
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.return_value = "Sure, I can help!"
        mock_ollama.return_value = mock_llm_instance

        with patch("api.views.get_vector_store") as mock_get_store:
            self.client.post(
                self.url,
                data={"instruction": "Hello, how are you?"},
                format="json",
            )
            mock_get_store.assert_not_called()


# =============================================================================
# suite 3 — manejo de errores
#
# verifica que la api responda correctamente cuando hay inputs invalidos o
# recursos que no existen.
# =============================================================================

class ErrorHandlingIntegrationTest(APITestCase):

    def test_sync_proyecto_inexistente_devuelve_404(self):
        """sincronizar un id que no existe tiene que devolver 404."""
        response = self.client.post("/api/projects/9999/sync/")
        self.assertEqual(response.status_code, 404)

    def test_sync_404_incluye_clave_error_en_el_json(self):
        """la respuesta de error tiene que venir con una clave 'error'."""
        response = self.client.post("/api/projects/9999/sync/")
        self.assertIn("error", response.json())

    def test_generate_proyecto_inexistente_devuelve_404(self):
        """generar un test para un proyecto que no existe tiene que devolver 404."""
        response = self.client.post(
            "/api/projects/9999/generate/",
            data={"instruction": "test the login flow"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_generate_instruccion_vacia_devuelve_400(self):
        """mandar instruccion vacia tiene que devolver 400."""
        project = Project.objects.create(name="dummy", directory_path="/fake")
        response = self.client.post(
            f"/api/projects/{project.id}/generate/",
            data={"instruction": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
