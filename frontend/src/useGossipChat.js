import { useState } from "react";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";

const API = "http://localhost:8000";

// tiny tagged logger so every step is greppable in the console
const log = (step, ...args) => console.log(`[GossipGene] ${step}`, ...args);

const postJSON = (path, body) =>
  fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json());

export function useGossipChat() {
  // This is the useChat hook that manages the chat history and status.
  const { messages, sendMessage, setMessages, status } = useChat({
    transport: new DefaultChatTransport({ api: `${API}/chat` }),
    // from the SDK docs
    onFinish: ({ message }) => log("2 chat ← done with the complete loop", message),
    onError: (err) => log("2 chat ✗ stream error", err),
  });

  // Separate stream for direct (non-DB) answers from the GateKeeper path.
  const answerChat = useChat({transport: new DefaultChatTransport({ api: `${API}/answer` }),});

  const [input, setInput] = useState("");

  // Step 1 messages (retrieved rows for example) here, separate from the useChat-managed Step 2 stream.
  const [preamble, setPreamble] = useState([]);

  // This activates teh GateKeeper and the Retrieval pipeline.
  const send = async (event) => {
    // here we avoid default browser behavior to avoid losing information when the user presses enter.
    event.preventDefault();
    const question = input.trim();
    if (!question) return;
    setInput("");
    setMessages([]);
    answerChat.setMessages([]);
    const userMsg = { role: "user", text: question };
    setPreamble([userMsg]);
    log("0 gate → asking", question);

    // Step 0: GateKeeper decides whether we need the DB pipeline at all - unrelated questions are directly answered    
    const gatekeeperDecision = await postJSON("/gate", { question });
    log("0 gate - First we want to check if the question is related to the database.");
    log("0 gate ← decision", gatekeeperDecision);

    // If gatekeeperDecision.use_database is false, we stream a direct answer, no need to query
    if (!gatekeeperDecision.use_database) {
      log("0 gate → use database is false, streaming direct answer");
      answerChat.sendMessage({ text: question });
      return;
    }

    // Step 1: retrieve candidate rows -> this is hybrid searc.
    const searchMsg = { role: "assistant", text: "First I will run a quick search with your query." };
    setPreamble([userMsg, searchMsg]);

    log("1 retrieve → searching in the database, via BM25 retrieval");
    const rows = await postJSON("/retrieve", { question });
    
    log("1 retrieve ← rows", rows.length);
    const list = rows.map((r) => `- ${r.gene_symbol || r.ensembl} - ${r.name} (${r.biotype}, chr ${r.chromosome})`).join("\n");

    setPreamble([userMsg, searchMsg, { role: "assistant", text: `Possible answers:\n${list}` }]);

    // Step 2: hand off to the agent.
    log("2 chat → handoff to agent...  work in progress...");
    sendMessage({ text: question });
  };

  // Rows executed by the recommend_query tool arrive as a structured tool-output part (not LLM text).
  const queryResult = messages
    .flatMap((m) => m.parts ?? [])
    .filter((p) => p.type === "tool-recommend_query" && p.state === "output-available")
    .map((p) => p.output)
    .at(-1);

  // Streamed text from the direct-answer path (token-by-token as it arrives).
  const directAnswer = answerChat.messages
    .flatMap((m) => (m.role === "assistant" ? m.parts ?? [] : []))
    .filter((p) => p.type === "text")
    .map((p) => p.text)
    .join("");

  const hasContent = preamble.length > 0 || messages.length > 0 || directAnswer.length > 0;

  const thinking =
    status === "submitted" ||
    status === "streaming" ||
    answerChat.status === "submitted" ||
    answerChat.status === "streaming";

  return {
    input,
    setInput,
    send,
    preamble,
    queryResult,
    directAnswer,
    status,
    hasContent,
    thinking,
  };
}
