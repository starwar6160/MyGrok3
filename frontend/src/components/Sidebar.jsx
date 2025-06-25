import React from "react";
export default function Sidebar({ conversations, currentId, setCurrentId, addConversation }) {
  return (
    <div className="sidebar">
      <button onClick={addConversation}>＋ 新会话</button>
      <a
        href="/translation/"
        style={{
          display: 'block',
          textAlign: 'center',
          marginBottom: 12,
          marginTop: 2,
          padding: 8,
          background: '#ff9800',
          color: 'white',
          textDecoration: 'none',
          borderRadius: 4,
          fontWeight: 'bold',
          fontSize: '1.08em'
        }}
      >🈯 翻译工具</a>
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
