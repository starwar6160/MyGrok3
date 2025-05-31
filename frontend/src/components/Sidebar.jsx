import React from "react";
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faPlus, faTrash, faHistory, faComment } from '@fortawesome/free-solid-svg-icons';

export default function Sidebar({ conversations, currentId, setCurrentId, addConversation, showHistory, setShowHistory, loadConversations }) {
  const handleToggleHistory = () => {
    const newShowHistory = !showHistory;
    setShowHistory(newShowHistory);
    loadConversations(newShowHistory ? 'history' : 'active');
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <button className="new-chat-button" onClick={addConversation}>
          <FontAwesomeIcon icon={faPlus} /> 新会话
        </button>
        <button className="history-toggle-button" onClick={handleToggleHistory}>
          <FontAwesomeIcon icon={showHistory ? faComment : faHistory} /> {showHistory ? '活跃会话' : '历史会话'}
        </button>
      </div>
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
