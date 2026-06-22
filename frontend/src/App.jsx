import { useState } from "react";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import "./App.css";

// tiny tagged logger so every step is greppable in the console
const log = (step, ...args) => console.log(`[GossipGene] ${step}`, ...args);

export default function App() {
  // This is the useChat hook that manages the chat history and status.
  const { messages, sendMessage, setMessages, status } = useChat({
    transport: new DefaultChatTransport({ api: "http://localhost:8000/chat" }),
    // from the SDK docs
    onFinish: ({ message }) => log("2 chat ← done with the complete loop", message),
    onError: (err) => log("2 chat ✗ stream error", err),
  });
  const [input, setInput] = useState("");
  // Step 1 messages (user echo, loading notices, retrieved rows) here, separate from the useChat-managed Step 2 stream.
  const [preamble, setPreamble] = useState([]);

  const send = async (e) => {
    e.preventDefault();
    const question = input.trim();
    if (!question) return;
    setInput("");
    setPreamble([{ role: "user", text: question }]);
    log("0 gate → asking", question);

    // Step 0: GateKeeper decides whether we need the DB pipeline at all - unrelated questions are directly answered
    const gatekeeperResponse = await fetch("http://localhost:8000/gate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    // gatekeeperResponse.json() has two fields: use_database and answer. 
    // use_database is a boolean (do we need to query the database?)
    // answer is a string (the answer to the question).
    const gatekeeperDecision = await gatekeeperResponse.json();
    log("0 gate - First we want to check if the question is related to the database.");
    log("0 gate ← decision", gatekeeperDecision);

    // If gatekeeperDecision.use_database is false, we can answer the question directly, no need to query
    if (!gatekeeperDecision.use_database) {
      // TODO: Handle edge case where answer is empty/undefined/null bc falsy values could habe an issue. 
      log("0 gate → answered directly");
      setPreamble([
        { role: "user", text: question },
        { role: "assistant", text: gatekeeperDecision.answer },
      ]);
      return;
    }

    // Step 1: retrieve candidate rows.
    setPreamble([
      { role: "user", text: question },
      { role: "assistant", text: "First I will run a quick search with your query." },
    ]);

    log("1 retrieve → searching in the database, via BM25 retrieval");

    const res = await fetch("http://localhost:8000/retrieve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const rows = await res.json();
    log("1 retrieve ← rows", rows.length);
    const list = rows
      .map((r) => `- ${r.gene_symbol || r.ensembl} - ${r.name} (${r.biotype}, chr ${r.chromosome})`)
      .join("\n");

    setPreamble([
      { role: "user", text: question },
      { role: "assistant", text: "First I will run a quick search with your query." },
      { role: "assistant", text: `Possible answers:\n${list}` },
    ]);

    // Step 2: hand off to the agent.
    log("2 chat → handoff to agent...  work in progress...");
    sendMessage({ text: question });
  };

  const newTask = () => {
    setMessages([]);
    setPreamble([]);
  };

  const hasContent = preamble.length > 0 || messages.length > 0;
  const lastAssistant = messages.filter((m) => m.role === "assistant").at(-1);
  const assistantText =
    lastAssistant?.parts.filter((p) => p.type === "text").map((p) => p.text).join("") ?? "";

  const thinking = (status === "submitted" || status === "streaming") && !assistantText;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="label">RECENT CHATS</div>
        <div className="chat-item">Session 01</div>
        <button className="new-task" onClick={newTask}>
          + New Task
        </button>
      </aside>
      <main className="main">
        {!hasContent ? (
          <div className="greeting">
            <h1>Evening</h1>
            <p>Let's find some data from datavisyn's Catalogues and Repositories</p>
          </div>
        ) : (
          <div className="messages">
            {preamble.map((m, i) => (
              <div key={`pre-${i}`} className={`msg ${m.role}`}>
                {m.text}
              </div>
            ))}
            {messages
              .filter((m) => m.role === "assistant")
              .map((m) => {
                const text = m.parts
                  .filter((p) => p.type === "text")
                  .map((p) => p.text)
                  .join("");
                return text ? (
                  <div key={m.id} className="msg assistant">
                    {text}
                  </div>
                ) : null;
              })}
          </div>
        )}
        {thinking && (
          <div className="thinking">
            <span className="dot" /> Thinking…
          </div>
        )}
        <form className="input-bar" onSubmit={send}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything..."
          />
        </form>
      </main>
    </div>
  );
}
