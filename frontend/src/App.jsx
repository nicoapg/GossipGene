import { useEffect, useState } from "react";
import "./App.css";
import { useGossipChat } from "./useGossipChat";

function getGreeting(hour) {
  if (hour < 12) return "Good Morning";
  if (hour < 18) return "Good Afternoon";
  if (hour < 22) return "Evening";
  return "Good Night";
}

// Frontend-only "typing" reveal for static text bubbles (purely a UX gimmick).
function Typewriter({ text, speed = 12 }) {
  const [shown, setShown] = useState("");
  useEffect(() => {
    setShown("");
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setShown(text.slice(0, i));
      if (i >= text.length) clearInterval(id);
    }, speed);
    return () => clearInterval(id);
  }, [text, speed]);
  return shown;
}

export default function App() {
  const { input, setInput, send, preamble, queryResult, directAnswer, status, hasContent, thinking } =
    useGossipChat();

  return (
    <div className="app">
      <main className="main">
        {!hasContent ? (
          <div className="greeting">
            <h1>{getGreeting(new Date().getHours())}</h1>
            <p>Let's find some data from datavisyn's Catalogues and Repositories</p>
          </div>
        ) : (
          <div className="messages">
            {preamble.map((message, index) => (
              <div key={`pre-${index}`} className={`msg ${message.role}`}>
                {message.role === "assistant" ? <Typewriter text={message.text} /> : message.text}
              </div>
            ))}
            {directAnswer && <div className="msg assistant">{directAnswer}</div>}
            {queryResult && status === "ready" && (
              <>
                <div className="msg assistant">
                  <Typewriter text={`This is the recommended query:\n\`\`\`sql\n${queryResult.sql}\n\`\`\``} />
                </div>
                <div className="msg assistant">
                  {queryResult.error ? (
                    <div>Query failed: {queryResult.error}</div>
                  ) : queryResult.rows.length === 0 ? (
                    <div>No rows matched.</div>
                  ) : (
                    <div className="result-scroll">
                      <table className="result-table">
                        <thead>
                          <tr>
                            {Object.keys(queryResult.rows[0]).map((column) => (
                              <th key={column}>{column}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {queryResult.rows.map((row, rowIndex) => (
                            <tr key={rowIndex}>
                              {Object.values(row).map((value, cellIndex) => (
                                <td key={cellIndex}>{String(value)}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </>
            )}
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
