@echo off
echo Starting MVP - Cypress Test Generator
echo.

start "Backend (Django)" cmd /k "cd /d %~dp0backend && venv\Scripts\activate && python manage.py runserver"
start "Frontend (Next.js)" cmd /k "cd /d %~dp0frontend && npm run dev"
start "Test Project" cmd /k "cd /d %~dp0test_project && python -m http.server 8081"
start "Cypress" cmd /k "cd /d %~dp0test_project && npx cypress open"

echo  Backend      ^>  http://localhost:8000
echo  Frontend     ^>  http://localhost:3000
echo  Test Project ^>  http://localhost:8081
echo  Cypress      ^>  npx cypress open
echo.
echo Make sure Ollama is running: ollama run llama3.1
