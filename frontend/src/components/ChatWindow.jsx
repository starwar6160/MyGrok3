import React, { useEffect, useRef, useState } from "react";

export default function ChatWindow({ messages }) {
  const ref = useRef();
  const [collapsedGroups, setCollapsedGroups] = useState({});

  useEffect(() => {
    ref.current && (ref.current.scrollTop = ref.current.scrollHeight);
  }, [messages]);

  const groupMessages = () => {
    const groups = [];
    for (let i = 0; i < messages.length; i += 10) {
      groups.push(messages.slice(i, i + 10));
    }
    return groups;
  };

  const toggleGroup = (index) => {
    setCollapsedGroups(prev => ({
      ...prev,
      [index]: !prev[index]
    }));
  };

  return (
    <div className="chat" ref={ref}>
      {groupMessages().map((group, index) => (
        <div key={index}>
          <button onClick={() => toggleGroup(index)}>
            {collapsedGroups[index] ? "展开" : "折叠"} 组 {index + 1}
          </button>
          {!collapsedGroups[index] && group.map((msg, msgIndex) => (
            <div key={`${index}-${msgIndex}`} className={`msg-bubble ${msg.role}`}>
              <span className="msg-label">{msg.role === "user" ? "Q:" : "A:"}</span>
              {msg.role === "assistant" ? msg.content.split('\n').map((line, i) => line.trim() === '' ? <br key={i} /> : line.split(/(?<=[。！？])/g).map((sentence, j, arr) => sentence ? <span key={j} style={{ display: 'block', whiteSpace: 'pre-wrap', marginBottom: j === arr.length - 1 ? 8 : 0 }}>{sentence}</span> : null)) : <span>{msg.content}</span>}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
