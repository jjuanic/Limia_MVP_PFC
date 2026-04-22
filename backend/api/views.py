import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

from .models import Project, TestRequest
from .rag import get_vector_store, index_project, extract_selectors

OLLAMA_BASE_URL = "http://localhost:11434"
LLM_MODEL = "deepseek-coder:6.7b"

CYPRESS_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""You are an expert QA engineer specialised in Cypress end-to-end testing.

The REQUIREMENT and the PROJECT MAP (routes, IDs, button texts, UI messages) are embedded in the REQUIREMENT block below.
Additional source-code context is provided here for reference:

---
{context}
---

REQUIREMENT (includes project map):
{question}

PRE-FLIGHT — decide which of three responses to give:

A) If the message is a greeting, question, or general conversation (not a test instruction):
   Respond ONLY with:
   CHAT: <friendly response in the same language as the user, max 2 sentences>

B) If the message is a test instruction but some steps cannot be mapped to real elements:
   Respond ONLY with this exact format:

PLAN_NEEDED:
I could not generate the test because some steps could not be matched to real elements.

Mapped steps:
- <step description>: <selector or route used>

Unmapped steps:
- <step description>: MISSING — <what is needed>

Suggestion: <one sentence on what the user should clarify or add to the instruction>

C) If the message is a test instruction and ALL steps can be mapped → write the Cypress test following the RULES below.

RULES — any violation makes the test wrong:
1. cy.visit() — ONLY use paths listed under "Available pages". Never visit a path not in that list.
   - Use the exact filename: cy.visit('/register.html'), NOT cy.visit('/register') or cy.visit('/').

2. Clicking elements:
   - If the element has an ID: cy.get('#id').click() — that's it. Nothing else.
   - NEVER write cy.get('#id').contains('...').click() — chaining .contains() after .get() searches for child elements, not the element itself. This is always wrong for buttons.
   - NEVER write cy.contains('text').click() for an element that has an ID in the project map.

3. CSS class selectors:
   - NEVER use class selectors like cy.contains('.notification', '...') or cy.get('.someClass') unless that exact class appears in the project map.
   - If a success or error message needs to be asserted, use cy.get('#id').should('be.visible') where #id is from the project map.

4. cy.contains() — ONLY for elements with NO id in the project map, using exact strings from "Visible button/link text" or "UI messages". Never paraphrase or change capitalisation.

5. Text assertions — copy strings VERBATIM from "UI messages". If none listed, use .should('be.visible') instead of asserting text content.

6. Redirections — the destination page is listed under "Available pages". Use the exact filename (e.g. index.html, not /dashboard or /home).

7. Wrap everything in a single describe() block. No markdown fences. No prose outside code comments.
8. Output ONLY the JavaScript code. No preamble ("Here is your test..."), no explanation after the closing brace. The first character of your response must be the letter 'd' (from describe).
""",
)


# ── Projects ──────────────────────────────────────────────────────────────────


@csrf_exempt
@require_http_methods(["GET"])
def list_projects(request):
    projects = list(
        Project.objects.values("id", "name", "directory_path", "last_synced_at")
    )
    return JsonResponse({"projects": projects})


@csrf_exempt
@require_http_methods(["POST"])
def create_project(request):
    body = json.loads(request.body)
    name = body.get("name", "").strip()
    directory_path = body.get("directory_path", "").strip()

    if not name or not directory_path:
        return JsonResponse(
            {"error": "name and directory_path are required"}, status=400
        )

    project = Project.objects.create(name=name, directory_path=directory_path)
    return JsonResponse({"id": project.id, "name": project.name}, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def sync_project(request, project_id):
    """
    Scan the project directory, chunk source files and upsert into ChromaDB.
    This is CU01 in the spec.
    """
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return JsonResponse({"error": "Project not found"}, status=404)

    chunks_indexed = index_project(project.id, project.directory_path)

    project.last_synced_at = timezone.now()
    project.save(update_fields=["last_synced_at"])

    return JsonResponse({"chunks_indexed": chunks_indexed})


# ── Test generation ────────────────────────────────────────────────────────────


@csrf_exempt
@require_http_methods(["POST"])
def generate_test(request, project_id):
    """
    CU02: receive a natural-language instruction, run RAG against the project's
    ChromaDB collection, call Ollama/Mistral, return Cypress code.
    """
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return JsonResponse({"error": "Project not found"}, status=404)

    body = json.loads(request.body)
    instruction = body.get("instruction", "").strip()
    if not instruction:
        return JsonResponse({"error": "Instruction cannot be empty."}, status=400)

    TEST_WORDS = {
        "visit", "click", "type", "fill", "check", "verify", "test",
        "register", "login", "navigate", "assert", "submit", "enter",
        "select", "open", "form", "button", "field", "redirect", "page",
        "sign", "user", "password", "email", "input", "appear", "show",
    }
    looks_like_test = any(w in instruction.lower().split() for w in TEST_WORDS)

    llm = Ollama(model=LLM_MODEL, base_url=OLLAMA_BASE_URL)

    if not looks_like_test:
        # Skip RAG — direct conversational reply
        chat_prompt = (
            "You are Limia, a friendly assistant that helps generate Cypress tests. "
            "Respond naturally and briefly (1-2 sentences) in the same language the user used. "
            "Do not refuse or restrict your response.\n\n"
            f"User: {instruction}"
        )
        cypress_code = f"CHAT: {llm.invoke(chat_prompt).strip()}"
    else:
        # 1. Retrieve semantically relevant chunks
        vector_store = get_vector_store(project.id)
        retriever = vector_store.as_retriever(search_kwargs={"k": 4})

        # 2. Build RAG chain
        chain = RetrievalQA.from_chain_type(
            llm=llm,
            retriever=retriever,
            chain_type="stuff",
            chain_type_kwargs={"prompt": CYPRESS_PROMPT},
        )

        # 3. Generate — inject real selectors so the model can't hallucinate them
        selectors = extract_selectors(project.directory_path)
        augmented_instruction = f"{selectors}\nREQUIREMENT: {instruction}"
        cypress_code = chain.run(augmented_instruction)

    # 4. Persist
    test_request = TestRequest.objects.create(
        project=project,
        natural_instruction=instruction,
        generated_cypress_code=cypress_code,
    )

    stripped = cypress_code.strip()
    if stripped.startswith("CHAT:"):
        response_type = "chat"
    elif stripped.startswith("PLAN_NEEDED:"):
        response_type = "plan"
    else:
        response_type = "code"

    return JsonResponse(
        {
            "test_request_id": test_request.id,
            "cypress_code": cypress_code,
            "response_type": response_type,
        },
        status=201,
    )


@require_http_methods(["GET"])
def pick_directory(request):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        path = filedialog.askdirectory(parent=root)
        root.destroy()
        if not path:
            return JsonResponse({"path": ""})
        return JsonResponse({"path": path})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def list_test_requests(request, project_id):
    requests = list(
        TestRequest.objects.filter(project_id=project_id).values(
            "id", "natural_instruction", "generated_cypress_code", "created_at"
        )
    )
    return JsonResponse({"test_requests": requests})
