import React, { useState, useEffect } from "react";
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faPlus, faHistory, faComment, faChevronDown, faChevronUp } from '@fortawesome/free-solid-svg-icons';

export default function Sidebar({ conversations, currentId, setCurrentId, addConversation, showHistory, setShowHistory, loadConversations }) {
  const [collapsedSections, setCollapsedSections] = useState({});
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 600);

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 600);
    };
    
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleToggleHistory = () => {
    const newShowHistory = !showHistory;
    setShowHistory(newShowHistory);
    loadConversations(newShowHistory ? 'history' : 'active');
  };

  const toggleSection = (sectionIndex) => {
    setCollapsedSections(prev => ({
      ...prev,
      [sectionIndex]: !prev[sectionIndex]
    }));
  };

  // 每10个对话分为一组
  const CHUNK_SIZE = 10;
  const conversationChunks = [];
  for (let i = 0; i < conversations.length; i += CHUNK_SIZE) {
    conversationChunks.push(conversations.slice(i, i + CHUNK_SIZE));
  }

  // 在移动设备上，只显示切换按钮
  if (isMobile) {
    return null;
  }

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
        {conversationChunks.map((chunk, chunkIndex) => {
          const isCollapsed = collapsedSections[chunkIndex];
          const startIndex = chunkIndex * CHUNK_SIZE;
          const endIndex = Math.min(startIndex + CHUNK_SIZE, conversations.length);
          
          return (
            <div key={chunkIndex} className="conversation-chunk">
              {chunkIndex > 0 && (
                <button 
                  className="collapse-toggle"
                  onClick={() => toggleSection(chunkIndex)}
                >
                  {isCollapsed ? (
                    <><FontAwesomeIcon icon={faChevronDown} /> 展开 {startIndex + 1}-{endIndex}</>
                  ) : (
                    <><FontAwesomeIcon icon={faChevronUp} /> 收起 {startIndex + 1}-{endIndex}</>
                  )}
                </button>
              )}
              {!isCollapsed && chunk.map(conv => (
                <button
                  key={conv.id}
                  className={`conversation-item ${conv.id === currentId ? "active" : ""}`}
                  onClick={() => setCurrentId(conv.id)}
                >
                  {conv.name}
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
