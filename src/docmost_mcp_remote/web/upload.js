// The upload link page: send files one by one with progress, reorder them, then Done.
"use strict";

(function () {
  const list = document.getElementById("list");
  if (!list) return;
  const base = location.pathname.replace(/\/+$/, "");
  const drop = document.getElementById("drop");
  const picker = document.getElementById("picker");
  const hint = document.getElementById("hint");
  const done = document.getElementById("done");
  const status = document.getElementById("status");
  const maxBytes = Number(list.dataset.maxBytes);
  const items = [];
  let sending = false;
  let dragged = null;

  const expiry = document.getElementById("expiry");
  const expires = new Date(expiry.dataset.expires);
  if (!isNaN(expires)) {
    const time = expires.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    expiry.textContent = expiry.textContent.replace(/until [^.]+\./, "until " + time + ".");
  }

  function size(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
  }

  function say(text, isError) {
    status.textContent = text;
    status.className = isError ? "error" : "muted";
  }

  function button(label, title, onClick, className) {
    const element = document.createElement("button");
    element.type = "button";
    element.textContent = label;
    element.title = title;
    element.setAttribute("aria-label", title);
    if (className) element.className = className;
    element.addEventListener("click", onClick);
    return element;
  }

  function render(item) {
    const row = document.createElement("li");
    row.draggable = true;
    const preview = item.file && item.file.type.startsWith("image/");
    if (preview) {
      const image = document.createElement("img");
      image.alt = "";
      image.src = URL.createObjectURL(item.file);
      row.append(image);
    } else {
      const icon = document.createElement("span");
      icon.className = "icon";
      icon.textContent = (item.name.split(".").pop() || "file").slice(0, 5).toUpperCase();
      row.append(icon);
    }
    const info = document.createElement("div");
    info.className = "info";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = item.name;
    const note = document.createElement("div");
    note.className = "muted";
    const bar = document.createElement("progress");
    bar.max = 100;
    info.append(name, note, bar);
    const move = document.createElement("div");
    move.className = "move";
    move.append(
      button("▲", "Move up", () => shift(item, -1)),
      button("▼", "Move down", () => shift(item, 1)),
    );
    row.append(info, move, button("✕", "Remove", () => remove(item), "remove"));
    row.addEventListener("dragstart", (event) => {
      dragged = item;
      row.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", item.name);
    });
    row.addEventListener("dragend", () => {
      dragged = null;
      row.classList.remove("dragging");
    });
    row.addEventListener("dragover", (event) => {
      if (!dragged || dragged === item) return;
      event.preventDefault();
      const box = row.getBoundingClientRect();
      const after = event.clientY > box.top + box.height / 2;
      const from = items.indexOf(dragged);
      items.splice(from, 1);
      items.splice(items.indexOf(item) + (after ? 1 : 0), 0, dragged);
      redraw();
    });
    item.row = row;
    item.note = note;
    item.bar = bar;
    update(item);
  }

  function update(item) {
    const labels = {
      queued: "Waiting",
      sending: "Sending",
      stored: "Ready",
      failed: item.error || "Failed",
    };
    item.note.textContent = size(item.size) + " · " + labels[item.state];
    item.note.className = item.state === "failed" ? "error" : "muted";
    item.bar.hidden = item.state !== "sending";
    item.bar.value = item.progress || 0;
  }

  function redraw() {
    list.replaceChildren(...items.map((item) => item.row));
    hint.hidden = items.length < 2;
    const busy = items.some((item) => item.state === "queued" || item.state === "sending");
    done.disabled = busy || !items.some((item) => item.state === "stored");
  }

  function shift(item, by) {
    const from = items.indexOf(item);
    const to = from + by;
    if (to < 0 || to >= items.length) return;
    items.splice(from, 1);
    items.splice(to, 0, item);
    redraw();
  }

  function remove(item) {
    if (item.request) item.request.abort();
    if (item.state === "stored") {
      fetch(base + "/files/" + item.id, { method: "DELETE" }).catch(() => {});
    }
    items.splice(items.indexOf(item), 1);
    redraw();
  }

  function add(files) {
    let total = items.reduce((sum, item) => sum + (item.state === "failed" ? 0 : item.size), 0);
    for (const file of files) {
      const item = { file, name: file.name, size: file.size, state: "queued" };
      total += file.size;
      if (total > maxBytes) {
        item.state = "failed";
        item.error = "Over the size limit of this link";
      }
      render(item);
      items.push(item);
    }
    say("");
    redraw();
    next();
  }

  function next() {
    if (sending) return;
    const item = items.find((candidate) => candidate.state === "queued");
    if (!item) return;
    sending = true;
    item.state = "sending";
    update(item);
    const form = new FormData();
    form.append("file", item.file, item.name);
    const request = new XMLHttpRequest();
    item.request = request;
    request.open("POST", base + "/files");
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        item.progress = (event.loaded / event.total) * 100;
        update(item);
      }
    });
    request.addEventListener("loadend", () => {
      sending = false;
      item.request = null;
      const answer = request.response || {};
      const stored = request.status === 200 && answer.files && answer.files[0];
      if (stored && !items.includes(item)) {
        fetch(base + "/files/" + stored.id, { method: "DELETE" }).catch(() => {});
      } else if (stored) {
        item.id = stored.id;
        item.state = "stored";
      } else if (request.status !== 0 || items.includes(item)) {
        item.state = "failed";
        item.error = answer.error || "Could not send the file";
      }
      update(item);
      redraw();
      next();
    });
    request.send(form);
  }

  for (const stored of JSON.parse(list.dataset.files || "[]")) {
    const item = {
      id: stored.id,
      file: null,
      name: stored.file_name,
      size: stored.size,
      state: "stored",
    };
    render(item);
    items.push(item);
  }
  redraw();

  picker.addEventListener("change", () => {
    add(picker.files);
    picker.value = "";
  });
  const hasFiles = (event) => Array.from(event.dataTransfer.types).includes("Files");
  drop.addEventListener("dragover", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    drop.classList.add("over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("over");
    add(event.dataTransfer.files);
  });
  // A file dropped next to the drop area would otherwise open in the browser.
  window.addEventListener("dragover", (event) => hasFiles(event) && event.preventDefault());
  window.addEventListener("drop", (event) => hasFiles(event) && event.preventDefault());

  done.addEventListener("click", async () => {
    done.disabled = true;
    say("Adding the files to the page…");
    const order = items.filter((item) => item.state === "stored").map((item) => item.id);
    let answer = {};
    let ok = false;
    try {
      const response = await fetch(base + "/done", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ order }),
      });
      answer = await response.json();
      ok = response.ok;
    } catch (error) {
      answer = { error: "The server could not be reached. Try again." };
    }
    if (!ok) {
      say(answer.error || "Adding the files failed. Try again.", true);
      redraw();
      return;
    }
    const main = document.querySelector("main");
    const heading = document.createElement("h1");
    heading.textContent = "Done";
    const text = document.createElement("p");
    text.textContent =
      answer.files.length + " file(s) added " + answer.placement + ". You can close this tab.";
    main.replaceChildren(heading, text);
    if (answer.warning) {
      const warning = document.createElement("p");
      warning.className = "muted";
      warning.textContent = answer.warning;
      main.append(warning);
    }
    if (answer.page_url) {
      const link = document.createElement("a");
      link.href = answer.page_url;
      link.textContent = "Open the page";
      main.append(link);
    }
  });
})();
