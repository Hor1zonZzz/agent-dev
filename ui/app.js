const chatEl = document.getElementById("chat");
const composerEl = document.getElementById("composer");
const messageEl = document.getElementById("message");
const sendEl = document.getElementById("send");
const statusEl = document.getElementById("status");

let sessionId = null;
let isStreaming = false;

function setStatus(text) {
  statusEl.textContent = text;
}

function addMessage(role, text) {
  const item = document.createElement("article");
  item.className = `message ${role}`;

  const label = document.createElement("div");
  label.className = "label";
  label.textContent = role === "user" ? "You" : "Agent";

  const body = document.createElement("div");
  body.className = "body";
  body.textContent = text;

  item.append(label, body);
  chatEl.appendChild(item);
  chatEl.scrollTop = chatEl.scrollHeight;
  return body;
}

function parseEventBlock(block) {
  const lines = block.split("\n");
  let event = "";
  let data = "";

  for (const line of lines) {
    if (line.startsWith("event: ")) {
      event = line.slice(7);
    } else if (line.startsWith("data: ")) {
      data += line.slice(6);
    }
  }

  if (!event || !data) {
    return null;
  }

  return { event, payload: JSON.parse(data) };
}

async function streamChat(message) {
  if (isStreaming) return;

  isStreaming = true;
  sendEl.disabled = true;
  messageEl.disabled = true;
  setStatus("Streaming...");

  addMessage("user", message);

  try {
    const response = await fetch("/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message,
        session_id: sessionId,
      }),
    });

    if (!response.ok || !response.body) {
      const detail = await response.text();
      throw new Error(detail || `Request failed with ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      while (buffer.includes("\n\n")) {
        const splitIndex = buffer.indexOf("\n\n");
        const block = buffer.slice(0, splitIndex);
        buffer = buffer.slice(splitIndex + 2);

        const parsed = parseEventBlock(block);
        if (!parsed) continue;

        const { event, payload } = parsed;
        if (event === "session") {
          sessionId = payload.session_id;
          setStatus(`Connected: ${sessionId}`);
        } else if (event === "message") {
          addMessage("assistant", payload.text ?? "");
        } else if (event === "done") {
          setStatus(`Ready: ${payload.session_id}`);
        } else if (event === "error") {
          throw new Error(payload.detail || "Streaming failed");
        }
      }
    }
  } catch (error) {
    addMessage("assistant", `Error: ${error.message}`);
    setStatus("Request failed");
  } finally {
    isStreaming = false;
    sendEl.disabled = false;
    messageEl.disabled = false;
    messageEl.focus();
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    if (!response.ok) throw new Error("health check failed");
    const payload = await response.json();
    sessionId = payload.session_id;
    setStatus(`Ready: ${sessionId}`);
  } catch {
    setStatus("Backend unavailable");
  }
}

composerEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageEl.value.trim();
  if (!message) return;

  messageEl.value = "";
  await streamChat(message);
});

checkHealth();
