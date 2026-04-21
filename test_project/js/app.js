document.addEventListener("DOMContentLoaded", () => {
  // Protect route
  const userRaw = localStorage.getItem("user");
  if (!userRaw) {
    window.location.href = "login.html";
    return;
  }

  // Setup user info
  const user = JSON.parse(userRaw);
  const welcomeMsg = document.getElementById("welcome-msg");
  if (welcomeMsg) {
    welcomeMsg.textContent = `Hello, ${user.name || user.email.split('@')[0]}`;
  }

  // Handle logout
  const logoutBtn = document.getElementById("logout-btn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      localStorage.removeItem("user");
      window.location.href = "login.html";
    });
  }

  // Task logic
  const taskInput = document.getElementById("new-task-input");
  const addBtn = document.getElementById("add-task-btn");
  const taskList = document.getElementById("task-list");
  const taskCount = document.getElementById("task-count");
  const emptyMsg = document.getElementById("empty-msg");

  let tasks = [];

  function renderTasks() {
    taskList.innerHTML = "";
    
    if (tasks.length === 0) {
      emptyMsg.classList.add("visible");
      taskCount.textContent = "0 tasks";
      return;
    }

    emptyMsg.classList.remove("visible");
    taskCount.textContent = `${tasks.length} task${tasks.length !== 1 ? 's' : ''}`;

    tasks.forEach((task, index) => {
      const li = document.createElement("li");
      li.className = `task-item ${task.completed ? 'completed' : ''}`;
      li.id = `task-item-${index}`;

      const textSpan = document.createElement("span");
      textSpan.className = "task-text";
      textSpan.textContent = task.text;

      const actionsDiv = document.createElement("div");
      actionsDiv.className = "task-actions";

      const toggleBtn = document.createElement("button");
      toggleBtn.className = "btn btn-sm btn-success";
      toggleBtn.textContent = task.completed ? "Undo" : "Done";
      toggleBtn.id = `toggle-task-${index}`;
      toggleBtn.addEventListener("click", () => {
        tasks[index].completed = !tasks[index].completed;
        renderTasks();
      });

      actionsDiv.appendChild(toggleBtn);
      li.appendChild(textSpan);
      li.appendChild(actionsDiv);
      taskList.appendChild(li);
    });
  }

  if (addBtn && taskInput) {
    addBtn.addEventListener("click", () => {
      const text = taskInput.value.trim();
      if (text) {
        tasks.push({ text, completed: false });
        taskInput.value = "";
        renderTasks();
      }
    });
    
    taskInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") {
        addBtn.click();
      }
    });
  }

  renderTasks();
});
