import { useEffect, useState } from "react";
import "./App.css";
import { useGossipChat } from "./useGossipChat";

function getGreeting(hour) {
  if (hour < 12) return "Good Morning";
  if (hour < 18) return "Good Afternoon";
  if (hour < 22) return "Evening";
  return "Good Night";
}

// Frontend-only "typing" 
// TODO: This kind of frontend animations would need more efficient implementation. (e.g. multiple tasks running in parallel)
function Typewriter({ text, speed = 12 }) {
  // "shown" holds the part of the text that is currently visible on screen.
  const [shown, setShown] = useState("");
  // A timer reveals one more character every few milliseconds, like typing.
  useEffect(() => {
    setShown("");
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setShown(text.slice(0, i));
      // this is the stop condition
      if (i >= text.length) clearInterval(id);
    }, speed);
    // Stop the timer when the text changes or the component goes away.
    return () => clearInterval(id);
  }, [text, speed]); // text and speed are the dependencies that control how this re-runs
  return shown;
}

export default function App() {
  // Destructuring the useGossipChat returns
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
        {
        /* This is where submission is taking place 
        
        TODO: Improve box container and "thinking" display
        
        */}
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
