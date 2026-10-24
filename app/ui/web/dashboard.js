(() => {
  "use strict";

  const colors = {
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
  const state = {
    status: "all",
    page: "notes",
    view: "grid",
    query: "",
    color: "all",
    sort: "updated",
    taskFilter: "all",
    request: 0,
    toastTimer: 0,
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function showToast(message) {
    const toast = $("#toast");
    toast.textContent = message;
    toast.classList.add("is-visible");
    window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 2200);
  }

  function reportError(message, error) {
    console.error(message, error);
    showToast(message);
  }

  function escapeNoteColor(note) {
    if (note.color !== "custom") return colors[note.color] || colors.yellow;
    const color = /^#[0-9a-f]{6}$/i.test(note.custom_color || "")
      ? note.custom_color : "#E9D5FF";
    const channels = [1, 3, 5].map((offset) => parseInt(color.slice(offset, offset + 2), 16));
    const lightness = channels.reduce((sum, channel, index) =>
      sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
    const ink = lightness < 128;
    return [
      color,
      color,
      color,
      ink ? "#c8c3d1" : "#a991be",
      ink ? "#f7f3ec" : "#302b3d",
      ink ? "#d0c9d7" : "#665f70",
    ];
  }

  function formatDate(value) {
    if (!value) return "недавно";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "недавно";
    return new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    }).format(parsed);
  }

  function titleForStatus() {
    return {
      all: ["Мои заметки", "ВАШЕ ПРОСТРАНСТВО", "Мысли и дела — собраны в одном месте."],
      active: ["Активные заметки", "СЕЙЧАС В РАБОТЕ", "То, что пригодится вам сегодня."],
      archived: ["Архив", "СОХРАНЁННЫЕ ИДЕИ", "Заметки, к которым можно вернуться в любой момент."],
    }[state.status];
  }

  function applyPageHeading() {
    const [title, eyebrow, description] = state.page === "notes"
      ? titleForStatus()
      : state.page === "tasks"
        ? ["Задачи", "МАЛЕНЬКИЕ ШАГИ", "Планы из ваших стикеров — в одном списке."]
        : ["Корзина", "МОЖНО ВЕРНУТЬ", "Удалённые заметки пока можно восстановить."];
    $("#page-title").textContent = title;
    $("#page-eyebrow").textContent = eyebrow;
    $("#page-description").textContent = description;
    $("#notes-view").hidden = state.page !== "notes";
    $("#tasks-view").hidden = state.page !== "tasks";
    $("#trash-view").hidden = state.page !== "trash";
    $$(".nav-item").forEach((button) => {
      button.classList.toggle(
        "is-active",
        button.dataset.page === state.page
          && (state.page !== "notes" || button.dataset.status === state.status),
      );
    });
  }

  function renderStats(data) {
    const stats = data.stats;
    $("#stat-notes").textContent = stats.notes;
    $("#stat-active").textContent = stats.active_tasks;
    $("#stat-done").textContent = stats.completed_tasks;
    $("#all-count").textContent = stats.notes;
    $("#task-count").textContent = stats.active_tasks;
    $("#trash-count").textContent = data.trash.length;
    const total = stats.active_tasks + stats.completed_tasks;
    $("#stat-progress").style.width = total
      ? `${Math.round(stats.completed_tasks / total * 100)}%`
      : "0%";
  }

  function renderNoteCard(note) {
    const card = document.createElement("article");
    const theme = escapeNoteColor(note);
    card.className = "note-card";
    card.style.setProperty("--card-light", theme[0]);
    card.style.setProperty("--card-base", theme[1]);
    card.style.setProperty("--card-dark", theme[2]);
    card.style.setProperty("--card-fold", theme[3]);
    card.style.setProperty("--card-ink", theme[4]);
    card.style.setProperty("--card-muted", theme[5]);
    card.style.setProperty("--card-rotation", `${Number(note.rotation) || 0}deg`);

    const head = document.createElement("div");
    head.className = "note-card-head";
    const mark = document.createElement("span");
    mark.className = "note-color-mark";
    mark.setAttribute("aria-hidden", "true");
    const actions = document.createElement("div");
    actions.className = "note-card-actions";
    actions.append(
      actionButton("Дублировать заметку", "⧉", () => perform(
        () => window.pywebview.api.duplicate_note(note.id), "Создана копия заметки",
      )),
      actionButton(
        note.is_archived ? "Вернуть из архива" : "В архив",
        note.is_archived ? "↗" : "↘",
        () => perform(
          () => note.is_archived
            ? window.pywebview.api.open_note(note.id)
            : window.pywebview.api.archive_note(note.id),
          note.is_archived ? "Заметка возвращена из архива" : "Заметка перемещена в архив",
        ),
      ),
      actionButton("Переместить в корзину", "⌫", async () => {
        if (await confirmAction("Переместить в корзину?", "Заметку можно будет восстановить.")) {
          await perform(
            () => window.pywebview.api.trash_note(note.id),
            "Заметка перемещена в корзину",
          );
        }
      }),
    );
    head.append(mark, actions);

    const main = document.createElement("div");
    main.className = "note-card-main";
    const title = document.createElement("h3");
    title.textContent = note.title.trim() || "Без заголовка";
    const preview = document.createElement("p");
    preview.className = "note-preview";
    const body = note.body.replace(/\s+/g, " ").trim();
    preview.textContent = body || "Пустая заметка · откройте, чтобы добавить текст";
    const meta = document.createElement("div");
    meta.className = "note-meta";
    const taskCount = note.tasks.length;
    const completeCount = note.tasks.filter((task) => task.completed).length;
    if (taskCount) {
      const progress = document.createElement("span");
      progress.className = "note-progress";
      const track = document.createElement("i");
      const bar = document.createElement("span");
      bar.style.width = `${Math.round(completeCount / taskCount * 100)}%`;
      track.append(bar);
      progress.append(document.createTextNode(`${completeCount}/${taskCount}`), track);
      meta.append(progress);
    }
    const date = document.createElement("span");
    date.textContent = formatDate(note.updated_at);
    meta.append(date);
    main.append(title, preview);

    const open = document.createElement("button");
    open.type = "button";
    open.className = "note-open";
    open.textContent = note.is_archived ? "Вернуть и открыть" : "Открыть";
    open.addEventListener("click", () => perform(
      () => window.pywebview.api.open_note(note.id), "Стикер открыт",
    ));
    card.append(head, main, meta, open);
    return card;
  }

  function actionButton(label, text, callback) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "note-action";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.textContent = text;
    button.addEventListener("click", callback);
    return button;
  }

  function renderNotes(notes) {
    const grid = $("#notes-grid");
    grid.replaceChildren();
    grid.classList.toggle("is-list", state.view === "list");
    const labels = { all: "Все заметки", active: "Активные заметки", archived: "Архив" };
    $("#results-label").textContent = labels[state.status];
    $("#results-total").textContent = `${notes.length} ${plural(notes.length, ["заметка", "заметки", "заметок"])}`;
    if (!notes.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      const stack = document.createElement("span");
      stack.className = "empty-stack";
      stack.setAttribute("aria-hidden", "true");
      stack.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
      const title = document.createElement("h2");
      title.textContent = state.query ? "Ничего не найдено" : "Здесь пока пусто";
      const text = document.createElement("p");
      text.textContent = state.query
        ? "Попробуйте изменить запрос или фильтр."
        : "Создайте первый стикер — он появится отдельным окном и будет доступен на рабочем столе.";
      empty.append(stack, title, text);
      if (!state.query && state.status !== "archived") {
        const create = document.createElement("button");
        create.type = "button";
        create.className = "top-create-button";
        create.textContent = "＋ Создать стикер";
        create.addEventListener("click", createNote);
        empty.append(create);
      }
      grid.append(empty);
      return;
    }
    grid.append(...notes.map(renderNoteCard));
  }

  function renderTasks(tasks) {
    const board = $("#task-board");
    board.replaceChildren();
    if (!tasks.length) {
      board.append(emptyBoard(
        state.taskFilter === "completed" ? "Выполненных задач пока нет." : "Всё спокойно — задач пока нет.",
      ));
      return;
    }
    for (const task of tasks) {
      const row = document.createElement("article");
      row.className = `task-item${task.completed ? " is-complete" : ""}`;
      const check = document.createElement("button");
      check.type = "button";
      check.className = "task-check";
      check.setAttribute("aria-pressed", String(Boolean(task.completed)));
      check.setAttribute("aria-label", task.completed ? "Вернуть задачу" : "Отметить выполненной");
      if (task.completed) check.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7"/></svg>';
      check.addEventListener("click", async () => {
        try {
          await window.pywebview.api.set_task_completed(task.id, !task.completed);
          await refreshDashboard();
        } catch (error) {
          reportError("Не удалось сохранить задачу", error);
        }
      });
      const copy = document.createElement("div");
      copy.className = "task-copy";
      const text = document.createElement("strong");
      text.textContent = task.text;
      const noteTitle = document.createElement("small");
      noteTitle.textContent = task.note_title;
      copy.append(text, noteTitle);
      const open = document.createElement("button");
      open.type = "button";
      open.className = "task-note-open";
      open.textContent = "К стикеру";
      open.addEventListener("click", () => perform(
        () => window.pywebview.api.open_note(task.note_id), "Стикер открыт",
      ));
      row.append(check, copy, open);
      board.append(row);
    }
  }

  function renderTrash(notes) {
    const board = $("#trash-board");
    board.replaceChildren();
    $("#empty-trash").hidden = notes.length === 0;
    if (!notes.length) {
      board.append(emptyBoard("Корзина пуста."));
      return;
    }
    for (const note of notes) {
      const row = document.createElement("article");
      row.className = "trash-item";
      const copy = document.createElement("div");
      copy.className = "trash-copy";
      const title = document.createElement("strong");
      title.textContent = note.title.trim() || "Без заголовка";
      const date = document.createElement("small");
      date.textContent = `Удалено ${formatDate(note.deleted_at)}`;
      copy.append(title, date);
      const actions = document.createElement("div");
      actions.className = "trash-actions";
      const restore = document.createElement("button");
      restore.type = "button";
      restore.className = "small-button";
      restore.textContent = "Восстановить";
      restore.addEventListener("click", () => perform(
        () => window.pywebview.api.restore_note(note.id), "Заметка восстановлена",
      ));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "danger-outline";
      remove.textContent = "Удалить навсегда";
      remove.addEventListener("click", async () => {
        if (await confirmAction("Удалить навсегда?", "Заметка и её задачи будут удалены без возможности восстановления.")) {
          await perform(
            () => window.pywebview.api.delete_note_permanently(note.id),
            "Заметка удалена",
          );
        }
      });
      actions.append(restore, remove);
      row.append(copy, actions);
      board.append(row);
    }
  }

  function emptyBoard(text) {
    const item = document.createElement("div");
    item.className = "board-empty";
    item.textContent = text;
    return item;
  }

  function plural(count, words) {
    const mod100 = count % 100;
    if (mod100 >= 11 && mod100 <= 14) return words[2];
    const mod10 = count % 10;
    if (mod10 === 1) return words[0];
    if (mod10 >= 2 && mod10 <= 4) return words[1];
    return words[2];
  }

  async function perform(action, successMessage) {
    try {
      const result = await action();
      if (result === null) return false;
      showToast(successMessage);
      await refreshDashboard();
      return true;
    } catch (error) {
      reportError("Не удалось выполнить действие", error);
      return false;
    }
  }

  async function refreshDashboard() {
    const request = ++state.request;
    try {
      const data = await window.pywebview.api.get_dashboard_data(
        state.query, state.status, state.color, state.sort, state.taskFilter,
      );
      if (request !== state.request) return;
      renderStats(data);
      renderNotes(data.notes);
      renderTasks(data.tasks);
      renderTrash(data.trash);
      applyPageHeading();
    } catch (error) {
      console.error("Не удалось обновить Stickly", error);
      showToast("Не удалось загрузить заметки");
    }
  }

  async function createNote() {
    await perform(
      () => window.pywebview.api.create_note(), "Новый стикер создан",
    );
  }

  function confirmAction(title, message) {
    const dialog = $("#confirm-dialog");
    $("#confirm-title").textContent = title;
    $("#confirm-message").textContent = message;
    dialog.showModal();
    return new Promise((resolve) => {
      const accept = $("#confirm-accept");
      const finish = (result) => {
        accept.removeEventListener("click", onAccept);
        dialog.removeEventListener("close", onClose);
        resolve(result);
      };
      const onAccept = () => {
        dialog.close("confirm");
        finish(true);
      };
      const onClose = () => finish(dialog.returnValue === "confirm");
      accept.addEventListener("click", onAccept);
      dialog.addEventListener("close", onClose, { once: true });
    });
  }

  function setFormValues(settings) {
    for (const [name, value] of Object.entries(settings)) {
      const field = $(`[name="${name}"]`, $("#settings-form"));
      if (!field) continue;
      if (field.type === "checkbox") field.checked = Boolean(value);
      else field.value = value;
    }
  }

  function readSettingsForm() {
    const form = $("#settings-form");
    return {
      start_with_windows: form.elements.start_with_windows.checked,
      global_hotkeys: form.elements.global_hotkeys.checked,
      close_to_tray: form.elements.close_to_tray.checked,
      default_color: form.elements.default_color.value,
      default_width: Number(form.elements.default_width.value),
      default_height: Number(form.elements.default_height.value),
      default_font_size: Number(form.elements.default_font_size.value),
      autosave_delay: Number(form.elements.autosave_delay.value),
    };
  }

  async function openSettingsPanel() {
    try {
      const data = await window.pywebview.api.get_dashboard_data(
        state.query, state.status, state.color, state.sort, state.taskFilter,
      );
      setFormValues(data.settings);
      $("#settings-dialog").showModal();
    } catch (error) {
      reportError("Не удалось открыть настройки", error);
    }
  }

  async function saveSettings() {
    const button = $("#save-settings");
    button.disabled = true;
    try {
      await window.pywebview.api.set_settings(readSettingsForm());
      $("#settings-dialog").close();
      showToast("Настройки сохранены");
      await refreshDashboard();
    } catch (error) {
      reportError("Не удалось сохранить настройки", error);
    } finally {
      button.disabled = false;
    }
  }

  async function connectControls() {
    $("#create-note").addEventListener("click", createNote);
    $("#top-create").addEventListener("click", createNote);
    $("#settings-open").addEventListener("click", openSettingsPanel);
    $("#close-main").addEventListener("click", async () => {
      try {
        await window.pywebview.api.close_main();
      } catch (error) {
        reportError("Не удалось свернуть Stickly", error);
      }
    });
    $("#save-settings").addEventListener("click", saveSettings);
    $("#export-notes").addEventListener("click", () => perform(
      () => window.pywebview.api.export_notes(), "Экспорт завершён",
    ));
    $("#import-notes").addEventListener("click", async () => {
      try {
        const count = await window.pywebview.api.import_notes();
        if (count !== null) showToast(`Добавлено заметок: ${count}`);
        await refreshDashboard();
      } catch (error) {
        reportError("Не удалось импортировать файл", error);
      }
    });
    $("#backup-database").addEventListener("click", () => perform(
      () => window.pywebview.api.backup_database(), "Резервная копия создана",
    ));
    $("#empty-trash").addEventListener("click", async () => {
      if (!await confirmAction("Очистить корзину?", "Все заметки и задачи в корзине будут удалены навсегда.")) return;
      try {
        const count = await window.pywebview.api.empty_trash();
        showToast(`Удалено заметок: ${count}`);
        await refreshDashboard();
      } catch (error) {
        reportError("Не удалось очистить корзину", error);
      }
    });
    $("#search-notes").addEventListener("input", (event) => {
      state.query = event.currentTarget.value;
      refreshDashboard();
    });
    $("#color-filter").addEventListener("change", (event) => {
      state.color = event.currentTarget.value;
      refreshDashboard();
    });
    $("#sort-filter").addEventListener("change", (event) => {
      state.sort = event.currentTarget.value;
      refreshDashboard();
    });
    $("#task-filter").addEventListener("change", (event) => {
      state.taskFilter = event.currentTarget.value;
      refreshDashboard();
    });
    $$(".nav-item").forEach((button) => {
      button.addEventListener("click", () => {
        state.page = button.dataset.page;
        if (state.page === "notes") state.status = button.dataset.status;
        applyPageHeading();
      });
    });
    $$(".view-switch button").forEach((button) => {
      button.addEventListener("click", () => {
        state.view = button.dataset.view;
        $$(".view-switch button").forEach((item) =>
          item.classList.toggle("is-selected", item === button));
        $("#notes-grid").classList.toggle("is-list", state.view === "list");
      });
    });
    document.addEventListener("keydown", async (event) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "n") {
        event.preventDefault();
        await createNote();
      } else if (key === "f") {
        event.preventDefault();
        state.page = "notes";
        applyPageHeading();
        $("#search-notes").focus();
      } else if (key === "s") {
        event.preventDefault();
        try {
          await window.pywebview.api.save_all();
          showToast("Все заметки сохранены");
        } catch (error) {
          reportError("Не удалось сохранить заметки", error);
        }
      }
    });
  }

  async function initialize() {
    try {
      await connectControls();
      await refreshDashboard();
      document.body.classList.add("is-ready");
    } catch (error) {
      console.error("Не удалось запустить главную панель", error);
      showToast("Не удалось запустить Stickly");
    }
  }

  window.refreshDashboard = refreshDashboard;
  window.openSettingsPanel = openSettingsPanel;
  if (window.pywebview && window.pywebview.api) initialize();
  else window.addEventListener("pywebviewready", initialize, { once: true });
})();
