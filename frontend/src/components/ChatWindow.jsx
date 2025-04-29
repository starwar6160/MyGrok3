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
          <span>{msg.content}</span>
        </div>
      ))}
    </div>
  );
}
