(() => {
  "use strict";

  const palette = {
    yellow: ["#fff3bd", "#f6e79c", "#e7d884", "#d3bd68", "#35302a", "#6d6047"],
    pink: ["#ffe4eb", "#f5d0dc", "#eac0ce", "#d6a1b2", "#3d3034", "#705660"],
    mint: ["#e1f4e4", "#cbe9d2", "#b9ddc2", "#8fbd9c", "#293b30", "#526c5a"],
    blue: ["#e2f0fb", "#cde2f2", "#bad8eb", "#91b8d3", "#2e3b46", "#586f80"],
    lavender: ["#eee8fb", "#dcd2f1", "#c9bde5", "#a898d0", "#393247", "#655c76"],
    peach: ["#ffeadb", "#f5d7c1", "#e9c4aa", "#d7a47d", "#44362e", "#765d4d"],
    gray: ["#f0efea", "#e2e0d8", "#d3d0c8", "#b7b2a5", "#34332f", "#66645b"],
    graphite: ["#555360", "#454450", "#343440", "#8d849f", "#f7f2e9", "#d1c8d4"],
    cream: ["#fff5e2", "#f1e5ca", "#e6d7b6", "#ceba8e", "#40372b", "#71624d"],
    dark: ["#555360", "#454450", "#343440", "#8d849f", "#f7f2e9", "#d1c8d4"],
  };
  const iconCheck = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3.2 3.2L13 4.5"/></svg>';
  const state = { note: null, tasks: [], timer: 0, drag: null, resize: null, toastTimer: 0 };
  const el = (id) => document.getElementById(id);

  function setTheme(color, customColor) {
    const values = [...(palette[color] || palette.yellow)];
    const root = document.documentElement;
    if (color === "custom" && /^#[0-9a-f]{6}$/i.test(customColor || "")) {
      const channels = [1, 3, 5].map((offset) => parseInt(customColor.slice(offset, offset + 2), 16));
      const lightness = channels.reduce((sum, channel, index) =>
        sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
      values[0] = customColor;
      values[1] = customColor;
      values[2] = customColor;
      values[3] = lightness < 128 ? "#c8c3d1" : "#a991be";
      values[4] = lightness < 128 ? "#f7f3ec" : "#302b3d";
      values[5] = lightness < 128 ? "#d0c9d7" : "#665f70";
    }
    root.style.setProperty("--paper-light", values[0]);
    root.style.setProperty("--paper-base", values[1]);
    root.style.setProperty("--paper-dark", values[2]);
    root.style.setProperty("--paper-fold", values[3]);
    root.style.setProperty("--paper-edge", values[3]);
    root.style.setProperty("--ink", values[4]);
    root.style.setProperty("--ink-muted", values[5]);
    el("paper").dataset.color = color;
  }

  function renderTasks() {
    const list = el("task-list");
    list.replaceChildren();
    state.tasks.forEach((task, index) => {
      const row = document.createElement("div");
      row.className = `task-row${task.completed ? " is-complete" : ""}`;
      row.dataset.taskId = task.id;
      const check = document.createElement("button");
      check.className = "task-check";
      check.type = "button";
      check.setAttribute("aria-label", task.completed ? "Отметить незавершённой" : "Отметить выполненной");
      check.setAttribute("aria-pressed", String(Boolean(task.completed)));
      check.innerHTML = iconCheck;
      check.addEventListener("click", () => toggleTask(task));
      const text = document.createElement("span");
      text.className = "task-text";
      text.textContent = task.text;
      const remove = document.createElement("button");
      remove.className = "task-remove";
      remove.type = "button";
      remove.textContent = "×";
      remove.setAttribute("aria-label", "Удалить задачу");
      remove.title = "Удалить задачу";
      remove.addEventListener("click", () => deleteTask(task.id));
      row.append(check, text, remove);
      list.append(row);
      row.draggable = true;
      row.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/plain", String(index));
        event.dataTransfer.effectAllowed = "move";
      });
      row.addEventListener("dragover", (event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
      });
      row.addEventListener("drop", (event) => {
        event.preventDefault();
        const from = Number(event.dataTransfer.getData("text/plain"));
        const to = index;
        if (Number.isInteger(from) && from !== to) reorderTask(from, to);
      });
    });
    const complete = state.tasks.filter((task) => task.completed).length;
    const total = state.tasks.length;
    el("task-count").textContent = `${complete} из ${total}`;
    el("task-progress").style.width = total ? `${Math.round(complete / total * 100)}%` : "0%";
  }

  function showToast(message) {
    const toast = el("toast");
    toast.textContent = message;
    toast.classList.add("is-visible");
    window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 1800);
  }

  async function saveContent() {
    await window.pywebview.api.save_content(
      state.note.id, el("title").value, el("body").value, state.note.font_size,
    );
    el("save-status").textContent = "Сохранено";
  }

  async function flushSave() {
    window.clearTimeout(state.timer);
    await saveContent();
  }

  function scheduleSave() {
    el("save-status").textContent = "Сохраняю…";
    window.clearTimeout(state.timer);
    state.timer = window.setTimeout(async () => {
      try {
        await saveContent();
      } catch (error) {
        console.error("Не удалось сохранить стикер", error);
        el("save-status").textContent = "Ошибка сохранения";
      }
    }, Math.max(300, Math.min(1500, Number(state.note.autosave_delay) || 450)));
  }

  async function toggleTask(task) {
    try {
      const updated = await window.pywebview.api.toggle_task(task.id, !task.completed);
      Object.assign(task, updated);
      renderTasks();
    } catch (error) {
      console.error("Не удалось изменить задачу", error);
      showToast("Не удалось сохранить задачу");
    }
  }

  async function deleteTask(taskId) {
    try {
      await window.pywebview.api.delete_task(taskId);
      state.tasks = state.tasks.filter((task) => task.id !== taskId);
      renderTasks();
    } catch (error) {
      console.error("Не удалось удалить задачу", error);
      showToast("Не удалось удалить задачу");
    }
  }

  async function reorderTask(from, to) {
    const previous = [...state.tasks];
    const [task] = state.tasks.splice(from, 1);
    state.tasks.splice(to, 0, task);
    renderTasks();
    try {
      await window.pywebview.api.reorder_tasks(state.note.id, state.tasks.map((item) => item.id));
    } catch (error) {
      state.tasks = previous;
      renderTasks();
      console.error("Не удалось сохранить порядок задач", error);
      showToast("Не удалось сохранить порядок");
    }
  }

  function setupDragging() {
    const handle = el("drag-region");
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || event.target.closest("button")) return;
      state.drag = { x: event.screenX, y: event.screenY, lastX: event.screenX, lastY: event.screenY };
      el("paper").classList.add("is-dragging");
      handle.setPointerCapture(event.pointerId);
    });
    handle.addEventListener("pointermove", (event) => {
      if (!state.drag) return;
      const dx = event.screenX - state.drag.lastX;
      const dy = event.screenY - state.drag.lastY;
      state.drag.lastX = event.screenX;
      state.drag.lastY = event.screenY;
      if (dx || dy) {
        window.pywebview.api.move_window(dx, dy).catch((error) =>
          console.error("Не удалось переместить стикер", error));
      }
    });
    const release = async () => {
      if (!state.drag) return;
      state.drag = null;
      el("paper").classList.remove("is-dragging");
      try { await window.pywebview.api.save_geometry(); }
      catch (error) { console.error("Не удалось сохранить положение", error); }
    };
    handle.addEventListener("pointerup", release);
    handle.addEventListener("pointercancel", release);
  }

  function setupResize() {
    const grip = el("resize-grip");
    grip.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      state.resize = { x: event.screenX, y: event.screenY, lastX: event.screenX, lastY: event.screenY };
      grip.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    grip.addEventListener("pointermove", (event) => {
      if (!state.resize) return;
      const dx = event.screenX - state.resize.lastX;
      const dy = event.screenY - state.resize.lastY;
      state.resize.lastX = event.screenX;
      state.resize.lastY = event.screenY;
      if (dx || dy) {
        window.pywebview.api.resize_window(dx, dy).catch((error) =>
          console.error("Не удалось изменить размер стикера", error));
      }
    });
    const release = async () => {
      if (!state.resize) return;
      state.resize = null;
      try { await window.pywebview.api.save_geometry(); }
      catch (error) { console.error("Не удалось сохранить размер", error); }
    };
    grip.addEventListener("pointerup", release);
    grip.addEventListener("pointercancel", release);
    grip.addEventListener("keydown", (event) => {
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const dx = event.key === "ArrowRight" ? 16 : event.key === "ArrowLeft" ? -16 : 0;
      const dy = event.key === "ArrowDown" ? 16 : event.key === "ArrowUp" ? -16 : 0;
      window.pywebview.api.resize_window(dx, dy)
        .then(() => window.pywebview.api.save_geometry())
        .catch((error) => console.error("Не удалось изменить размер стикера", error));
    });
  }

  async function changeColor(color, customColor = "") {
    try {
      await window.pywebview.api.set_color(state.note.id, color, customColor);
      state.note.color = color;
      if (color === "custom") state.note.custom_color = customColor;
      setTheme(color, state.note.custom_color);
      el("palette").hidden = true;
    } catch (error) {
      console.error("Не удалось изменить цвет стикера", error);
      showToast("Не удалось изменить цвет");
    }
  }

  async function runAction(action) {
    try {
      await flushSave();
      switch (action) {
        case "duplicate": await window.pywebview.api.duplicate_note(state.note.id); break;
        case "archive": await window.pywebview.api.archive_note(state.note.id); break;
        case "trash": await window.pywebview.api.trash_note(state.note.id); break;
        case "font-up":
        case "font-down": {
          const delta = action === "font-up" ? 1 : -1;
          state.note.font_size = Math.max(9, Math.min(32, Number(state.note.font_size) + delta));
          document.documentElement.style.setProperty("--body-size", `${Math.max(16, state.note.font_size)}px`);
          scheduleSave();
          break;
        }
        default: return;
      }
      el("more").hidden = true;
    } catch (error) {
      console.error("Не удалось выполнить действие со стикером", error);
      showToast("Не удалось выполнить действие");
    }
  }

  function connectControls() {
    el("title").addEventListener("input", scheduleSave);
    el("body").addEventListener("input", scheduleSave);
    el("task-input").addEventListener("keydown", async (event) => {
      if (event.key === "Escape") { event.currentTarget.value = ""; return; }
      if (event.key !== "Enter") return;
      event.preventDefault();
      const text = event.currentTarget.value.trim();
      if (!text) return;
      try {
        const task = await window.pywebview.api.add_task(state.note.id, text);
        state.tasks.push(task);
        event.currentTarget.value = "";
        renderTasks();
      } catch (error) {
        console.error("Не удалось добавить задачу", error);
        showToast("Не удалось добавить задачу");
      }
    });
    el("pin").addEventListener("click", async () => {
      const enabled = el("pin").getAttribute("aria-pressed") !== "true";
      try {
        await window.pywebview.api.set_pin(state.note.id, enabled);
        el("pin").setAttribute("aria-pressed", String(enabled));
        state.note.always_on_top = enabled;
      } catch (error) {
        console.error("Не удалось закрепить стикер", error);
        showToast("Не удалось изменить закрепление");
      }
    });
    el("hide").addEventListener("click", async () => {
      try {
        await flushSave();
        await window.pywebview.api.hide_sticker(state.note.id);
      } catch (error) {
        console.error("Не удалось скрыть стикер", error);
        showToast("Не удалось скрыть стикер");
      }
    });
    el("palette-toggle").addEventListener("click", () => {
      el("more").hidden = true;
      el("palette").hidden = !el("palette").hidden;
    });
    el("more-toggle").addEventListener("click", () => {
      el("palette").hidden = true;
      el("more").hidden = !el("more").hidden;
    });
    el("palette").addEventListener("click", (event) => {
      const button = event.target.closest("[data-color]");
      if (button) changeColor(button.dataset.color);
    });
    el("custom-color").addEventListener("change", (event) => {
      changeColor("custom", event.currentTarget.value);
    });
    el("more").addEventListener("click", (event) => {
      const button = event.target.closest("[data-action]");
      if (button) runAction(button.dataset.action);
    });
    document.addEventListener("pointerdown", (event) => {
      if (!event.target.closest(".popover, #palette-toggle, #more-toggle")) {
        el("palette").hidden = true;
        el("more").hidden = true;
      }
    });
    window.addEventListener("blur", () => el("paper").classList.add("is-unfocused"));
    window.addEventListener("focus", () => el("paper").classList.remove("is-unfocused"));
    setupDragging();
    setupResize();
  }

  async function initialize() {
    try {
      const note = await window.pywebview.api.get_note_data();
      state.note = note;
      state.tasks = note.tasks || [];
      el("title").value = note.title || "";
      el("body").value = note.body || "";
      el("custom-color").value = /^#[0-9a-f]{6}$/i.test(note.custom_color || "")
        ? note.custom_color : "#E9D5FF";
      document.documentElement.style.setProperty("--body-size", `${Math.max(16, Number(note.font_size) || 18)}px`);
      document.documentElement.style.setProperty("--paper-rotation", `${Number(note.rotation) || 0}deg`);
      setTheme(note.color, note.custom_color);
      el("pin").setAttribute("aria-pressed", String(Boolean(note.always_on_top)));
      renderTasks();
      connectControls();
      window.sticklyReadContent = () => ({
        title: el("title").value,
        body: el("body").value,
        font_size: state.note.font_size,
      });
      document.body.classList.add("is-ready");
    } catch (error) {
      console.error("Не удалось загрузить стикер", error);
      showToast("Не удалось загрузить заметку");
    }
  }

  if (window.pywebview && window.pywebview.api) initialize();
  else window.addEventListener("pywebviewready", initialize, { once: true });
})();
