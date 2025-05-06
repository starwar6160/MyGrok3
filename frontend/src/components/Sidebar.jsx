import React from "react";
export default function Sidebar({ conversations, currentId, setCurrentId, addConversation }) {
  return (
    <div className="sidebar">
      <button onClick={addConversation}>＋ 新会话</button>
      <div className="list">
        {conversations.map(conv => (
          <button
            key={conv.id}
            className={conv.id === currentId ? "active" : ""}
            onClick={() => setCurrentId(conv.id)}
          >
            {conv.name}
          </button>
        ))}
      </div>
    </div>
  );
}
