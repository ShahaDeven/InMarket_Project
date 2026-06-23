// InMarket chat UI — sends questions to /chat and renders the agent's reply.
(() => {
  "use strict";

  const chat = document.getElementById("chat");
  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send");
  const statusEl = document.getElementById("status");
  const tplUser = document.getElementById("tpl-user");
  const tplBot = document.getElementById("tpl-bot");

  const scrollDown = () => { chat.scrollTop = chat.scrollHeight; };

  function addUser(text) {
    const node = tplUser.content.cloneNode(true);
    node.querySelector(".msg__content").textContent = text; // textContent = safe
    chat.appendChild(node);
    scrollDown();
  }

  function addBot() {
    const node = tplBot.content.cloneNode(true);
    chat.appendChild(node);
    const el = chat.lastElementChild;
    scrollDown();
    return el;
  }

  // Indicative phases shown while the (non-streaming) agent works. They are
  // cosmetic reassurance, not the agent's real-time step — true per-step
  // progress would require streaming (LangGraph astream + SSE).
  const PHASES = [
    "Understanding your question",
    "Querying live FRED data",
    "Crunching the numbers",
    "Composing the answer",
  ];

  function startLoading(botEl) {
    const content = botEl.querySelector(".msg__content");
    content.innerHTML =
      '<span class="loading">' +
        '<span class="typing"><i></i><i></i><i></i></span>' +
        '<span class="loading__caption"></span>' +
      "</span>";
    const caption = content.querySelector(".loading__caption");
    const t0 = Date.now();
    const update = () => {
      const secs = Math.floor((Date.now() - t0) / 1000);
      const phase = Math.min(Math.floor(secs / 2.5), PHASES.length - 1);
      caption.textContent = PHASES[phase] + "…  ·  " + secs + "s";
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id); // call to stop the timer
  }

  function renderTools(botEl, toolCalls) {
    if (!toolCalls || !toolCalls.length) return;
    const box = botEl.querySelector(".tools");
    const label = document.createElement("span");
    label.className = "tools__label";
    label.textContent = "tools";
    box.appendChild(label);
    toolCalls.forEach((tc) => {
      const pill = document.createElement("span");
      pill.className = "tool-pill";
      pill.textContent = tc.name;
      box.appendChild(pill);
    });
  }

  function setStatus(state) {
    const labels = { ready: "ready", thinking: "thinking…", error: "error" };
    statusEl.lastChild.textContent = " " + (labels[state] || state);
  }

  async function ask(question) {
    addUser(question);
    const botEl = addBot();
    const stopLoading = startLoading(botEl);
    setStatus("thinking");
    sendBtn.disabled = true;
    try {
      const resp = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Request failed");
      // answer_html is server-rendered Markdown, allowlist-sanitized with nh3
      // server-side before it reaches the browser — safe to inject (OWASP LLM05).
      botEl.querySelector(".msg__content").innerHTML = data.answer_html;
      renderTools(botEl, data.tool_calls);
    } catch (err) {
      const c = botEl.querySelector(".msg__content");
      c.innerHTML = "";
      const p = document.createElement("p");
      p.className = "error";
      p.textContent = "⚠ " + err.message;
      c.appendChild(p);
    } finally {
      stopLoading();
      setStatus("ready");
      sendBtn.disabled = false;
      scrollDown();
    }
  }

  function autoGrow() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    autoGrow();
    ask(q);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", autoGrow);

  // Example prompt chips (event delegation so it also covers the intro block).
  document.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (chip && chip.dataset.q) ask(chip.dataset.q);
  });

  input.focus();
})();
