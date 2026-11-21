(() => {
  const pages = [...document.querySelectorAll("[data-page]")];
  const accepted = document.querySelector("#rules-accepted");
  const launchButton = document.querySelector("#launch-studio");
  const rulesError = document.querySelector("#rules-error");
  const feed = document.querySelector("#camera-feed");
  const videoCard = document.querySelector("#video-card");
  const fullscreenButton = document.querySelector("#fullscreen-drawing");
  const fullscreenLabel = document.querySelector("#fullscreen-label");
  const placeholder = document.querySelector("#video-placeholder");
  const cameraStatus = document.querySelector("#camera-status");
  const handStatus = document.querySelector("#hand-status");
  const gestureStatus = document.querySelector("#gesture-status");
  const studioStatus = document.querySelector(".studio-status");
  const palette = document.querySelector("#color-palette");
  const toolMessage = document.querySelector("#tool-message");
  let currentPage = "home";
  let cameraState = "idle";
  let statusTimer = null;
  let studioStarting = false;
  let paletteSignature = "";

  function showPage(name, updateHistory = true) {
    currentPage = name;
    for (const page of pages) {
      const active = page.dataset.page === name;
      page.hidden = !active;
      page.classList.toggle("active", active);
    }
    document.querySelectorAll("[data-page-link]").forEach((link) => {
      link.classList.toggle("active", link.dataset.pageLink === name);
    });
    document.querySelectorAll(".main-nav [data-scroll]").forEach((link) => {
      link.classList.remove("active");
    });
    if (updateHistory) {
      const path = name === "home" ? "/" : `/${name}`;
      history.pushState({ page: name }, "", path);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openRules() {
    rulesError.textContent = "";
    showPage("rules");
  }

  async function request(path, payload) {
    const response = await fetch(path, {
      method: payload === undefined ? "GET" : "POST",
      headers: payload === undefined ? {} : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Something went wrong.");
    return data;
  }

  function updateState(state) {
    const labels = {
      idle: "Waiting for camera…",
      starting: "Requesting camera…",
      running: "Camera connected",
      standby: "Camera standby",
      stopping: "Closing camera…",
      error: "Camera unavailable"
    };
    cameraState = state.status;
    cameraStatus.textContent = state.message || labels[state.status] || "Studio status";
    studioStatus.classList.toggle("online", state.status === "running");
    studioStatus.classList.toggle("error", state.status === "error");
    handStatus.textContent = state.handDetected ? "Hand detected" : "Hand not detected";
    handStatus.classList.toggle("hand-present", state.handDetected);

    const gestureLabels = {
      draw: "Drawing · index finger",
      pause: "Paused · pinch",
      erase: "Erasing · fist",
      color: "Color change · open palm",
      exit: "Closing studio · sign of horns",
      resume: "Show your hand for 2 seconds to restart",
      none: "Show your palm to draw"
    };
    gestureStatus.textContent = gestureLabels[state.gesture] || gestureLabels.none;

    if (state.status === "error") {
      feed.hidden = true;
      feed.removeAttribute("src");
      placeholder.hidden = false;
      placeholder.classList.remove("closed");
      placeholder.classList.add("error");
      placeholder.querySelector("h2").textContent = "Camera needs attention";
      placeholder.querySelector("p").textContent = state.error || state.message;
      stopPolling();
    } else if (state.status === "standby" && currentPage === "studio") {
      feed.hidden = true;
      feed.removeAttribute("src");
      placeholder.hidden = false;
      placeholder.classList.remove("error");
      placeholder.classList.add("closed");
      placeholder.querySelector("h2").textContent = "Show your hand to restart";
      placeholder.querySelector("p").textContent = state.message;
    } else if (state.status === "idle" && currentPage === "studio") {
      feed.hidden = true;
      feed.removeAttribute("src");
      stopPolling();
      placeholder.hidden = false;
      placeholder.classList.remove("closed");
      placeholder.classList.add("error");
      placeholder.querySelector("h2").textContent = "Studio closed";
      placeholder.querySelector("p").textContent = state.message || "Return home to start another session.";
    } else if (state.status === "running") {
      placeholder.classList.remove("closed", "error");
      if (!feed.getAttribute("src")) {
        placeholder.hidden = false;
        placeholder.querySelector("h2").textContent = "Connecting to your camera";
        placeholder.querySelector("p").textContent = "Your live feed will appear here. Camera video stays on this computer.";
        feed.src = `/video_feed?t=${Date.now()}`;
      }
      if (feed.naturalWidth > 0) {
        feed.hidden = false;
        placeholder.hidden = true;
      } else {
        feed.hidden = true;
        placeholder.hidden = false;
      }
    }

    if (state.colors?.length) renderPalette(state);
  }

  function renderPalette(state) {
    const signature = state.colors.map((color) => `${color.name}:${color.hex}`).join("|");
    if (signature !== paletteSignature) {
      palette.replaceChildren();
      state.colors.forEach((color, index) => {
        const swatch = document.createElement("button");
        swatch.type = "button";
        swatch.className = "color-swatch";
        swatch.style.backgroundColor = color.hex;
        swatch.title = color.name;
        swatch.setAttribute("aria-label", `Select ${color.name}`);
        swatch.addEventListener("click", async () => {
          await runTool(async () => {
            await request("/api/studio/color", { index });
            const current = await request("/api/status");
            renderPalette(current);
            toolMessage.textContent = `${color.name} selected.`;
          });
        });
        palette.append(swatch);
      });
      paletteSignature = signature;
    }

    [...palette.children].forEach((swatch, index) => {
      const selected = index === state.selectedColor;
      swatch.classList.toggle("selected", selected);
      swatch.setAttribute("aria-pressed", String(selected));
    });
    const selected = state.colors[state.selectedColor];
    if (selected) {
      document.querySelector("#selected-color-name").textContent = selected.name;
      document.querySelector("#selected-swatch").style.backgroundColor = selected.hex;
    }
    document.querySelector("#toggle-eraser").classList.toggle("tool-active", Boolean(state.eraser));
  }

  async function pollStatus() {
    try {
      const state = await request("/api/status");
      updateState(state);
      if (state.status === "idle" || state.status === "error") stopPolling();
    } catch (error) {
      updateState({ status: "error", error: error.message, message: error.message });
    }
  }

  function startPolling() {
    stopPolling();
    pollStatus();
    statusTimer = window.setInterval(pollStatus, 500);
  }

  function stopPolling() {
    if (statusTimer !== null) window.clearInterval(statusTimer);
    statusTimer = null;
  }

  async function launchStudio() {
    if (!accepted.checked) {
      rulesError.textContent = "Please confirm that you have read the gesture controls.";
      return;
    }
    if (studioStarting) return;
    studioStarting = true;
    launchButton.disabled = true;
    launchButton.classList.add("button-loading");
    launchButton.innerHTML = '<span class="button-spinner"></span> Starting camera…';
    rulesError.textContent = "";
    try {
      await request("/api/studio/start", { confirmed: true });
      placeholder.hidden = false;
      placeholder.classList.remove("error");
      placeholder.classList.remove("closed");
      placeholder.querySelector("h2").textContent = "Connecting to your camera";
      placeholder.querySelector("p").textContent = "Your live feed will appear here. Camera video stays on this computer.";
      feed.hidden = true;
      feed.src = `/video_feed?t=${Date.now()}`;
      showPage("studio");
      toolMessage.textContent = "";
      startPolling();
    } catch (error) {
      rulesError.textContent = error.message;
    } finally {
      studioStarting = false;
      launchButton.disabled = !accepted.checked;
      launchButton.classList.remove("button-loading");
      launchButton.innerHTML = 'Launch Drawing Studio <span aria-hidden="true">→</span>';
    }
  }

  async function exitStudio() {
    stopPolling();
    if (document.fullscreenElement === videoCard) {
      try {
        await document.exitFullscreen();
      } catch (error) {
        console.error("Could not exit fullscreen:", error);
      }
    }
    feed.removeAttribute("src");
    feed.hidden = true;
    showPage("home");
    try {
      await request("/api/studio/stop", {});
    } catch (error) {
      console.error("Could not stop the drawing studio:", error);
    }
  }

  async function runTool(action) {
    toolMessage.classList.remove("error");
    try {
      await action();
    } catch (error) {
      toolMessage.textContent = error.message;
      toolMessage.classList.add("error");
    }
  }

  async function toggleFullscreen() {
    if (!videoCard.requestFullscreen) {
      throw new Error("Fullscreen is not supported by this browser.");
    }
    if (document.fullscreenElement === videoCard) {
      await document.exitFullscreen();
    } else {
      await videoCard.requestFullscreen();
    }
  }

  document.querySelectorAll("[data-open-rules]").forEach((button) => button.addEventListener("click", openRules));
  document.querySelectorAll("[data-page-link]").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    showPage(link.dataset.pageLink);
  }));
  document.querySelectorAll("[data-scroll]").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    const target = document.getElementById(link.dataset.scroll);
    showPage("home");
    if (link.classList.contains("nav-link")) {
      document.querySelectorAll(".main-nav .nav-link").forEach((navLink) => {
        navLink.classList.toggle("active", navLink === link);
      });
    }
    window.setTimeout(() => target?.scrollIntoView({ behavior: "smooth" }), 30);
  }));
  accepted.addEventListener("change", () => {
    launchButton.disabled = !accepted.checked || studioStarting;
    rulesError.textContent = "";
  });
  launchButton.addEventListener("click", launchStudio);
  document.querySelector("#exit-studio").addEventListener("click", exitStudio);
  document.querySelector("#clear-canvas").addEventListener("click", () => runTool(async () => {
    await request("/api/studio/clear", {});
    toolMessage.textContent = "Canvas cleared.";
  }));
  document.querySelector("#toggle-eraser").addEventListener("click", () => runTool(async () => {
    const state = await request("/api/studio/eraser", {});
    updateState(state);
    toolMessage.textContent = state.eraser ? "Eraser enabled." : "Drawing color restored.";
  }));
  document.querySelector("#save-artwork").addEventListener("click", () => runTool(async () => {
    const result = await request("/api/studio/save", {});
    toolMessage.textContent = `Saved ${result.filename} in the output folder.`;
  }));
  fullscreenButton.addEventListener("click", () => runTool(toggleFullscreen));
  document.addEventListener("fullscreenchange", () => {
    const isFullscreen = document.fullscreenElement === videoCard;
    fullscreenButton.setAttribute("aria-pressed", String(isFullscreen));
    fullscreenLabel.textContent = isFullscreen ? "Exit full screen" : "Full screen drawing";
  });
  feed.addEventListener("load", () => {
    if (cameraState === "running" && feed.naturalWidth > 0) {
      feed.hidden = false;
      placeholder.hidden = true;
    }
  });
  feed.addEventListener("error", () => {
    if (currentPage === "studio" && ["starting", "running"].includes(cameraState)) {
      placeholder.hidden = false;
      placeholder.classList.add("error");
      placeholder.querySelector("h2").textContent = "Waiting for camera";
      placeholder.querySelector("p").textContent = "Allow camera access and check that another app is not using it.";
    }
  });
  window.addEventListener("popstate", () => {
    const name = location.pathname.replace("/", "");
    showPage(["rules", "studio"].includes(name) ? name : "home", false);
  });
  window.addEventListener("keydown", (event) => {
    if (currentPage !== "studio" || event.repeat || event.target instanceof HTMLInputElement) return;
    const key = event.key.toLowerCase();
    if (key === "q" || key === "escape") exitStudio();
    else if (key === "c") document.querySelector("#clear-canvas").click();
    else if (key === "s") document.querySelector("#save-artwork").click();
    else if (key === "e") document.querySelector("#toggle-eraser").click();
    else if (key === "n") {
      const selected = palette.querySelector(".selected");
      const swatches = [...palette.querySelectorAll(".color-swatch")];
      if (swatches.length) swatches[(swatches.indexOf(selected) + 1) % swatches.length].click();
    } else if (key === "f") runTool(toggleFullscreen);
  });
  launchButton.disabled = true;
  showPage("home", false);
})();
