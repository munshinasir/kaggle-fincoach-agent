(() => {
  const body = document.body;
  const transcript = document.getElementById("transcript");
  const composer = document.getElementById("composer");
  const messageInput = document.getElementById("message-input");
  const sendBtn = document.getElementById("send-btn");
  const uploadBtn = document.getElementById("upload-btn");
  const fileInput = document.getElementById("file-input");
  const fileChipsEl = document.getElementById("file-chips");
  const chips = document.querySelectorAll(".chip");

  let sessionId = null;
  let selectedFiles = [];

  function updateSendState() {
    sendBtn.disabled = messageInput.value.trim() === "" && selectedFiles.length === 0;
  }

  function autoGrow() {
    messageInput.style.height = "auto";
    messageInput.style.height = Math.min(messageInput.scrollHeight, 200) + "px";
  }

  function renderFileChips() {
    fileChipsEl.innerHTML = "";
    selectedFiles.forEach((file, index) => {
      const chip = document.createElement("span");
      chip.className = "file-chip";
      chip.textContent = file.name + " ";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.style.border = "none";
      remove.style.background = "transparent";
      remove.style.cursor = "pointer";
      remove.addEventListener("click", () => {
        selectedFiles.splice(index, 1);
        renderFileChips();
        updateSendState();
      });
      chip.appendChild(remove);
      fileChipsEl.appendChild(chip);
    });
  }

  function startConversation() {
    body.classList.add("started");
  }

  function addUserTurn(text, files) {
    const turn = document.createElement("div");
    turn.className = "turn user";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (text) {
      const p = document.createElement("div");
      p.textContent = text;
      bubble.appendChild(p);
    }
    files.forEach((file) => {
      const chip = document.createElement("span");
      chip.className = "file-chip";
      chip.textContent = "📄 " + file.name;
      bubble.appendChild(chip);
    });
    turn.appendChild(bubble);
    transcript.appendChild(turn);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function addAssistantTurn() {
    const turn = document.createElement("div");
    turn.className = "turn assistant";
    transcript.appendChild(turn);
    transcript.scrollTop = transcript.scrollHeight;
    return turn;
  }

  function renderQuestionTurn(message) {
    const turn = addAssistantTurn();
    const p = document.createElement("p");
    p.textContent = message;
    turn.appendChild(p);

    const reply = document.createElement("div");
    reply.className = "inline-reply";
    const textarea = document.createElement("textarea");
    textarea.rows = 2;
    textarea.placeholder = "Your answer...";
    const actions = document.createElement("div");
    actions.className = "actions";
    const skipLabel = document.createElement("label");
    const skipCheckbox = document.createElement("input");
    skipCheckbox.type = "checkbox";
    skipLabel.appendChild(skipCheckbox);
    skipLabel.appendChild(document.createTextNode(" Skip further questions"));
    const replyBtn = document.createElement("button");
    replyBtn.type = "button";
    replyBtn.className = "button primary";
    replyBtn.textContent = "Reply";
    replyBtn.addEventListener("click", async () => {
      const answer = textarea.value;
      addUserTurn(answer || "(skip remaining questions)", []);
      reply.remove();
      await sendResume({ session_id: sessionId, answer, skip_remaining: skipCheckbox.checked });
    });
    actions.appendChild(skipLabel);
    actions.appendChild(replyBtn);
    reply.appendChild(textarea);
    reply.appendChild(actions);
    turn.appendChild(reply);
  }

  function renderSecurityTurn(message) {
    const turn = addAssistantTurn();
    const p = document.createElement("p");
    p.textContent = message;
    turn.appendChild(p);

    const actions = document.createElement("div");
    actions.className = "actions";
    const continueBtn = document.createElement("button");
    continueBtn.type = "button";
    continueBtn.className = "button primary";
    continueBtn.textContent = "Continue";
    const stopBtn = document.createElement("button");
    stopBtn.type = "button";
    stopBtn.className = "button";
    stopBtn.textContent = "Stop here";

    async function choose(proceed) {
      addUserTurn(proceed ? "Continue" : "Stop here", []);
      actions.remove();
      await sendResumeSecurity({ session_id: sessionId, proceed });
    }

    continueBtn.addEventListener("click", () => choose(true));
    stopBtn.addEventListener("click", () => choose(false));
    actions.appendChild(continueBtn);
    actions.appendChild(stopBtn);
    turn.appendChild(actions);
  }

  function renderFinalTurn(confirmationHtml, recommendationsHtml) {
    const turn = addAssistantTurn();
    turn.innerHTML = confirmationHtml + recommendationsHtml;
    sessionId = null;
  }

  function renderHaltedTurn(message) {
    const turn = addAssistantTurn();
    const p = document.createElement("p");
    p.textContent = message;
    turn.appendChild(p);
    sessionId = null;
  }

  function handleResponse(data) {
    if (data.type === "question") {
      renderQuestionTurn(data.message);
    } else if (data.type === "security") {
      renderSecurityTurn(data.message);
    } else if (data.type === "halted") {
      renderHaltedTurn(data.message);
    } else if (data.type === "final") {
      renderFinalTurn(data.confirmation_html, data.recommendations_html);
    } else {
      renderQuestionTurn(data.message || "Something went wrong — please try again.");
    }
  }

  async function sendResume(payload) {
    const response = await fetch("/api/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    handleResponse(await response.json());
  }

  async function sendResumeSecurity(payload) {
    const response = await fetch("/api/resume-security", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    handleResponse(await response.json());
  }

  async function sendAnalyze(text, files) {
    const formData = new FormData();
    formData.append("message", text);
    files.forEach((file) => formData.append("documents", file));
    const response = await fetch("/api/analyze", { method: "POST", body: formData });
    const data = await response.json();
    sessionId = data.session_id;
    handleResponse(data);
  }

  composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = messageInput.value.trim();
    if (!text && selectedFiles.length === 0) return;

    startConversation();
    addUserTurn(text, selectedFiles);
    sendBtn.disabled = true;

    const files = selectedFiles;
    selectedFiles = [];
    renderFileChips();
    messageInput.value = "";
    autoGrow();
    updateSendState();

    await sendAnalyze(text, files);
  });

  messageInput.addEventListener("input", () => {
    autoGrow();
    updateSendState();
  });

  uploadBtn.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", () => {
    selectedFiles = selectedFiles.concat(Array.from(fileInput.files));
    fileInput.value = "";
    renderFileChips();
    updateSendState();
  });

  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      messageInput.value = chip.textContent;
      autoGrow();
      updateSendState();
      messageInput.focus();
    });
  });
})();
