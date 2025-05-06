import React, { useState } from "react";

export default function Sidebar({ conversations, currentId, setCurrentId, addConversation }) {
  const [collapsedGroups, setCollapsedGroups] = useState({});

  const groupConversations = () => {
    const groups = [];
    for (let i = 0; i < conversations.length; i += 5) {
      groups.push(conversations.slice(i, i + 5));
    }
    return groups;
  };

  const toggleGroup = (index) => {
    setCollapsedGroups(prev => ({
      ...prev,
      [index]: !prev[index]
    }));
  };

  const conversationGroups = groupConversations();

  return (
    <div className="sidebar">
      <button onClick={addConversation}>＋ 新会话</button>
      <div className="list">
        {conversationGroups.map((group, index) => (
          <div key={index}>
            <button onClick={() => toggleGroup(index)}>
              {collapsedGroups[index] ? "展开" : "折叠"} 组 {index + 1}
            </button>
            {!collapsedGroups[index] && group.map(conv => (
              <button
                key={conv.id}
                className={conv.id === currentId ? "active" : ""}
                onClick={() => setCurrentId(conv.id)}
              >
                {conv.name}
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
