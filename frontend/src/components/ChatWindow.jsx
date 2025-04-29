import React, { useEffect, useRef } from "react";
export default function ChatWindow({ messages }) {
  const ref = useRef();
  useEffect(() => {
    ref.current && (ref.current.scrollTop = ref.current.scrollHeight);
  }, [messages]);
  return (
    <div className="chat" ref={ref}>
      {messages.map((msg, i) => (
        <div
          key={i}
          className={`msg-bubble ${msg.role}`}
        >
          <span className="msg-label">{msg.role === "user" ? "Q:" : "A:"}</span>
          {msg.role === "assistant"
            ? msg.content.split('\n').map((line, i) =>
                line.trim() === '' ? <br key={i} /> :
                  line.split(/(?<=[。！？])/g).map((sentence, j, arr) =>
                    sentence ? (
                      <span
                        key={j}
                        style={{ display: 'block', whiteSpace: 'pre-wrap', marginBottom: j === arr.length - 1 ? 8 : 0 }}
                      >
                        {sentence}
                      </span>
                    ) : null
                  )
              )
            : <span>{msg.content}</span>
          }
        </div>
      ))}
    </div>
  );
}
