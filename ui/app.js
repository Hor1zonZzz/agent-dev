const chatEl = document.getElementById("chat");
const composerEl = document.getElementById("composer");
const messageEl = document.getElementById("message");
const statusEl = document.getElementById("status");

let ws = null;
let sessionId = null;

function setStatus(text) {
  statusEl.textContent = text;
}

function addMessage(role, text) {
  const item = document.createElement("article");
  item.className = `message ${role}`;

  const label = document.createElement("div");
  label.className = "label";
  label.textContent = role === "user" ? "You" : "Anna";

  const body = document.createElement("div");
  body.className = "body";
  body.textContent = text;

  item.append(label, body);
  chatEl.appendChild(item);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => setStatus("Connected");

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    switch (data.type) {
      case "session":
        sessionId = data.session_id;
        setStatus("Online");
        break;
      case "message":
        addMessage("assistant", data.text);
        break;
      case "status":
        if (data.status === "typing") setStatus("Anna is typing...");
        else if (data.status === "away") setStatus("Anna is away...");
        else if (data.status === "online") setStatus("Online");
        break;
    }
  };

  ws.onclose = () => {
    setStatus("Disconnected. Reconnecting...");
    setTimeout(connect, 3000);
  };

  ws.onerror = () => {
    ws.close();
  };
}

function sendMessage() {
  const text = messageEl.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

  addMessage("user", text);
  ws.send(JSON.stringify({ message: text }));
  messageEl.value = "";
  messageEl.focus();
}

composerEl.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage();
});

messageEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

connect();
