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
LLM_MODEL = "llama3.1"

CYPRESS_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""You are an expert QA engineer specialised in Cypress end-to-end testing.
Below is the actual source code of the project under test. Read it carefully.

---
{context}
---

Your task: write a Cypress test for this requirement:
"{question}"

STRICT RULES — violations make the test useless:
1. ONLY use CSS selectors (classes, IDs, data-testid, element tags) that you can SEE VERBATIM in the source code above. Do NOT invent or guess any selector.
2. ONLY use route paths that appear in the source code above. Do NOT guess URLs.
3. If you cannot find a selector for an element, use cy.contains('exact visible text') instead of inventing an attribute.
4. Before writing the test, output a short comment block listing every selector you found in the context and will use.
5. Wrap everything in a single describe() block.
6. Output only valid Cypress JavaScript. No markdown fences, no explanations outside comments.
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
    if len(instruction) < 20:
        return JsonResponse(
            {"error": "Instruction too short. Describe what you want to test in more detail."},
            status=400,
        )

    # 1. Retrieve semantically relevant chunks
    vector_store = get_vector_store(project.id)
    retriever = vector_store.as_retriever(search_kwargs={"k": 10})

    # 2. Build RAG chain
    llm = Ollama(model=LLM_MODEL, base_url=OLLAMA_BASE_URL)
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

    return JsonResponse(
        {
            "test_request_id": test_request.id,
            "cypress_code": cypress_code,
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
