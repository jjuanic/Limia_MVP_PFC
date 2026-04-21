// Valid credentials for demo purposes
const VALID_EMAIL    = "test@example.com";
const VALID_PASSWORD = "password123";

const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", function (e) {
    e.preventDefault();
    const email    = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;
    const errorEl  = document.getElementById("login-error");

    if (email === VALID_EMAIL && password === VALID_PASSWORD) {
      localStorage.setItem("user", JSON.stringify({ name: "Test User", email }));
      window.location.href = "index.html";
    } else {
      errorEl.textContent = "Invalid email or password.";
      errorEl.classList.add("visible");
    }
  });
}

const registerForm = document.getElementById("register-form");
if (registerForm) {
  registerForm.addEventListener("submit", function (e) {
    e.preventDefault();
    const name     = document.getElementById("name").value.trim();
    const email    = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;
    const errorEl  = document.getElementById("register-error");
    const successEl = document.getElementById("register-success");

    errorEl.classList.remove("visible");
    successEl.classList.remove("visible");

    if (!name || !email || !password) {
      errorEl.textContent = "All fields are required.";
      errorEl.classList.add("visible");
      return;
    }

    if (password.length < 6) {
      errorEl.textContent = "Password must be at least 6 characters.";
      errorEl.classList.add("visible");
      return;
    }

    localStorage.setItem("user", JSON.stringify({ name, email }));
    successEl.textContent = "Account created! Redirecting…";
    successEl.classList.add("visible");
    setTimeout(() => { window.location.href = "index.html"; }, 1200);
  });
}
