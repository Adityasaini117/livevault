// Alexa+ Simulator Client-Side Logic
// Handles speech recognition, speech synthesis, settings management, and tool rendering.

const STORAGE_KEY_URL = "lifevault_sim_server_url";
const STORAGE_KEY_TOKEN = "lifevault_sim_bearer_token";

// DOM Elements
const toggleSettingsBtn = document.getElementById("toggleSettingsBtn");
const settingsPanel = document.getElementById("settingsPanel");
const serverUrlInput = document.getElementById("serverUrlInput");
const bearerTokenInput = document.getElementById("bearerTokenInput");
const saveSettingsBtn = document.getElementById("saveSettingsBtn");
const settingsSavedHint = document.getElementById("settingsSavedHint");
const speechWarningBanner = document.getElementById("speechWarningBanner");
const voiceOrb = document.getElementById("voiceOrb");
const statusLabel = document.getElementById("statusLabel");
const chatStream = document.getElementById("chatStream");
const chatForm = document.getElementById("chatForm");
const textInput = document.getElementById("textInput");
const micBtn = document.getElementById("micBtn");
const sendBtn = document.getElementById("sendBtn");
const chipButtons = document.querySelectorAll(".chip-btn");

// Conversation State (capped at last 10 turns)
let conversationHistory = [];
let isListening = false;
let isSpeaking = false;
let recognition = null;

// 1. Initialize Settings from localStorage
const storedUrl = localStorage.getItem(STORAGE_KEY_URL);
if (storedUrl) {
  serverUrlInput.value = storedUrl;
}
const storedToken = localStorage.getItem(STORAGE_KEY_TOKEN);
if (storedToken) {
  bearerTokenInput.value = storedToken;
}

toggleSettingsBtn.addEventListener("click", () => {
  settingsPanel.classList.toggle("open");
});

saveSettingsBtn.addEventListener("click", () => {
  localStorage.setItem(STORAGE_KEY_URL, serverUrlInput.value.trim());
  localStorage.setItem(STORAGE_KEY_TOKEN, bearerTokenInput.value.trim());
  settingsSavedHint.classList.add("visible");
  setTimeout(() => {
    settingsSavedHint.classList.remove("visible");
  }, 2000);
});

// 2. Feature Detection for Speech Recognition & Synthesis
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const hasSpeechSynthesis = "speechSynthesis" in window;
const unsupportedFeatures = [];

if (!SpeechRecognition) {
  unsupportedFeatures.push("Speech Recognition (Voice Input)");
  micBtn.disabled = true;
  micBtn.title = "Speech recognition is not supported in this browser. Please use text input.";
}

if (!hasSpeechSynthesis) {
  unsupportedFeatures.push("Speech Synthesis (Spoken Output)");
}

if (unsupportedFeatures.length > 0) {
  speechWarningBanner.textContent = `Note: ${unsupportedFeatures.join(" & ")} not supported in your browser. You can still use the text box below.`;
  speechWarningBanner.classList.remove("hidden");
}

// 3. Setup Speech Recognition
if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = "en-US";

  recognition.onstart = () => {
    isListening = true;
    micBtn.classList.add("listening");
    setOrbState("listening");
    statusLabel.textContent = "Listening to your voice...";
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    textInput.value = transcript;
    statusLabel.textContent = `Heard: "${transcript}"`;
    // Automatically submit once speech is recognized
    handleSendMessage(transcript);
  };

  recognition.onerror = (event) => {
    console.warn("Speech recognition error:", event.error);
    isListening = false;
    micBtn.classList.remove("listening");
    setOrbState("idle");
    statusLabel.textContent = `Mic error (${event.error}). Please type below or tap mic again.`;
  };

  recognition.onend = () => {
    isListening = false;
    micBtn.classList.remove("listening");
    if (!isSpeaking) {
      setOrbState("idle");
    }
  };

  micBtn.addEventListener("click", () => {
    if (isListening) {
      recognition.stop();
    } else {
      // Stop any active speech synthesis before listening
      if (hasSpeechSynthesis && window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
      }
      try {
        recognition.start();
      } catch (err) {
        console.error("Mic start failed:", err);
      }
    }
  });
}

// 4. Speech Synthesis (Alexa voice reply)
function speakReply(text) {
  if (!hasSpeechSynthesis || !text) return;

  // Cancel prior speech
  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.05;
  utterance.pitch = 1.0;

  // Try picking a natural English female voice if available
  const voices = window.speechSynthesis.getVoices();
  const preferredVoice = voices.find(
    (v) => v.lang.startsWith("en") && (v.name.includes("Female") || v.name.includes("Google") || v.name.includes("Samantha") || v.name.includes("Zira"))
  ) || voices.find((v) => v.lang.startsWith("en"));

  if (preferredVoice) {
    utterance.voice = preferredVoice;
  }

  utterance.onstart = () => {
    isSpeaking = true;
    setOrbState("speaking");
    statusLabel.textContent = "Alexa+ is speaking...";
  };

  utterance.onend = () => {
    isSpeaking = false;
    setOrbState("idle");
    statusLabel.textContent = "Tap microphone to speak or type below";
  };

  utterance.onerror = () => {
    isSpeaking = false;
    setOrbState("idle");
  };

  window.speechSynthesis.speak(utterance);
}

// 5. Visual Orb State Manager
function setOrbState(state) {
  voiceOrb.className = "alexa-ring large-ring " + state;
}

// 6. UI Rendering: Chat Bubbles and Tool Tray
function appendUserMessage(text) {
  const card = document.createElement("div");
  card.className = "message-card user";
  card.innerHTML = `
    <div class="msg-header">You</div>
    <div class="msg-body">${escapeHtml(text)}</div>
  `;
  chatStream.appendChild(card);
  chatStream.scrollTop = chatStream.scrollHeight;
}

function appendAssistantMessage(replyText, toolCalls = []) {
  const card = document.createElement("div");
  card.className = "message-card assistant";

  let toolsHtml = "";
  if (toolCalls && toolCalls.length > 0) {
    const toolCards = toolCalls.map((tc, index) => `
      <div class="tool-card">
        <div class="tool-name-tag">🔧 ${escapeHtml(tc.name)}</div>
        <div class="tool-args">
          <span class="tool-section-label">Arguments:</span>
          <pre>${escapeHtml(JSON.stringify(tc.args, null, 2))}</pre>
        </div>
        <div class="tool-result">
          <span class="tool-section-label">Server Result:</span>
          <pre>${escapeHtml(tc.result || "(empty)")}</pre>
        </div>
      </div>
    `).join("");

    toolsHtml = `
      <div class="tool-tray">
        <button class="tool-toggle-btn" type="button" aria-expanded="false">
          ▶ View ${toolCalls.length} LifeVault Tool Call${toolCalls.length > 1 ? "s" : ""}
        </button>
        <div class="tool-details" style="display: none;">
          ${toolCards}
        </div>
      </div>
    `;
  }

  card.innerHTML = `
    <div class="msg-header">Alexa+</div>
    <div class="msg-body">${escapeHtml(replyText)}</div>
    ${toolsHtml}
  `;

  // Attach toggle listener for the collapsible tool tray
  const toggleBtn = card.querySelector(".tool-toggle-btn");
  if (toggleBtn) {
    const details = card.querySelector(".tool-details");
    toggleBtn.addEventListener("click", () => {
      const isOpen = details.style.display !== "none";
      details.style.display = isOpen ? "none" : "flex";
      toggleBtn.textContent = isOpen
        ? `▶ View ${toolCalls.length} LifeVault Tool Call${toolCalls.length > 1 ? "s" : ""}`
        : `▼ Hide ${toolCalls.length} LifeVault Tool Call${toolCalls.length > 1 ? "s" : ""}`;
      toggleBtn.setAttribute("aria-expanded", !isOpen);
    });
  }

  chatStream.appendChild(card);
  chatStream.scrollTop = chatStream.scrollHeight;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// 7. Core Send Handler
async function handleSendMessage(messageText) {
  const cleanMsg = (messageText || textInput.value).trim();
  if (!cleanMsg) return;

  // Clear text input
  textInput.value = "";
  appendUserMessage(cleanMsg);

  // Update Orb & Status
  setOrbState("thinking");
  statusLabel.textContent = "Alexa+ is thinking...";
  sendBtn.disabled = true;
  micBtn.disabled = true;

  const currentUrl = serverUrlInput.value.trim() || "http://localhost:8000/mcp";
  const currentToken = bearerTokenInput.value.trim() || null;

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: cleanMsg,
        server_url: currentUrl,
        bearer_token: currentToken,
        history: conversationHistory,
      }),
    });

    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }

    const data = await res.json();
    appendAssistantMessage(data.reply, data.tool_calls);

    // Speak response
    speakReply(data.reply);

    // Record into capped history (last 10 turns)
    conversationHistory.push({ role: "user", content: cleanMsg });
    conversationHistory.push({ role: "assistant", content: data.reply });
    if (conversationHistory.length > 10) {
      conversationHistory = conversationHistory.slice(-10);
    }

  } catch (err) {
    console.error("Chat error:", err);
    const friendlyError = "I'm having trouble connecting to the service right now. Please check your settings and try again.";
    appendAssistantMessage(friendlyError, []);
    speakReply(friendlyError);
  } finally {
    sendBtn.disabled = false;
    if (SpeechRecognition) {
      micBtn.disabled = false;
    }
    if (!isSpeaking) {
      setOrbState("idle");
      statusLabel.textContent = "Tap microphone to speak or type below";
    }
  }
}

// 8. Event Listeners for Submission & Demo Chips
chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  handleSendMessage();
});

chipButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const prompt = btn.getAttribute("data-prompt");
    textInput.value = prompt;
    handleSendMessage(prompt);
  });
});
