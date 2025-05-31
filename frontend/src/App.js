import React, { useState, useEffect } from "react";
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faHistory, faComment, faPlus } from '@fortawesome/free-solid-svg-icons';
import Sidebar from "./components/Sidebar";
import ChatWindow from "./components/ChatWindow";
import InputBar from "./components/InputBar";
import ConfirmDialog from "./components/ConfirmDialog";
import "./index.css";
import { v4 as uuidv4 } from 'uuid';

const initialConversations = [
  { id: 1, name: "会话1", messages: [] } // This might become obsolete or a placeholder
];

async function getInitialState() {
  let conversations = [];
  let currentId = null;

  try {
    // Fetch active conversations from backend
    const response = await fetch("/api/conversations?type=active");
    if (response.ok) {
      conversations = await response.json();
      if (conversations.length > 0) {
        currentId = conversations[0].id;
      }
    }
  } catch (e) {
    console.error("Error fetching conversations from backend:", e);
    // Fallback to local storage if backend fetch fails
    const saved = localStorage.getItem("grok3_conversations");
    if (saved) {
      conversations = JSON.parse(saved);
      if (!Array.isArray(conversations) || !conversations.length) {
        conversations = initialConversations;
      }
    } else {
      conversations = initialConversations;
    }
    if (conversations.length > 0) {
      currentId = conversations[0].id;
    }
  }

  // Try to restore currentId from localStorage if it exists and is valid
  const savedId = localStorage.getItem("grok3_current_id");
  if (savedId && conversations.find(c => c.id === savedId)) {
    currentId = savedId;
  } else if (conversations.length > 0) {
    currentId = conversations[0].id;
  } else {
    // If no conversations, create a new one
    const newConv = { id: uuidv4(), name: "新会话", messages: [] };
    conversations.push(newConv);
    currentId = newConv.id;
  }

  return { conversations, currentId };
}

export default function App() {
  // 新增状态
  const [lastFailedQuestion, setLastFailedQuestion] = useState("");
  const [showRetry, setShowRetry] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [showMobileSidebar, setShowMobileSidebar] = useState(false); // Mobile sidebar visibility

  const [selectedModel, setSelectedModel] = useState("grok-3-mini");
  const [{ conversations, currentId }, setState] = useState({
    conversations: initialConversations,
    currentId: initialConversations[0].id,
  });

  const loadConversations = async (type = 'active') => {
    try {
      const response = await fetch(`/api/conversations?type=${type}`);
      if (response.ok) {
        let fetchedConversations = await response.json();
        
        // Ensure each conversation has the required fields
        fetchedConversations = fetchedConversations.map(conv => ({
          ...conv,
          id: String(conv.id), // Ensure ID is a string for consistency
          name: conv.name || conv.title || '新会话', // Use name or title, default to '新会话'
          messages: Array.isArray(conv.messages) ? conv.messages : []
        }));

        // If no conversations, create a new one
        if (fetchedConversations.length === 0 && type !== 'history') {
          const newConv = { 
            id: uuidv4(), 
            name: "新会话", 
            title: "新会话",
            messages: [] 
          };
          fetchedConversations = [newConv];
        }

        // Only update state if we have conversations or we're showing history
        if (fetchedConversations.length > 0 || type === 'history') {
          setState(prevState => {
            // Preserve currentId if it's still valid
            const currentIdStillValid = fetchedConversations.some(c => c.id === prevState.currentId);
            const newCurrentId = currentIdStillValid ? prevState.currentId : 
              (fetchedConversations[0] ? fetchedConversations[0].id : null);
            
            // Only save to localStorage if we're not in history mode
            if (type !== 'history' && newCurrentId) {
              localStorage.setItem("grok3_conversations", JSON.stringify(fetchedConversations));
              localStorage.setItem("grok3_current_id", String(newCurrentId));
            }
            
            return { 
              conversations: fetchedConversations, 
              currentId: newCurrentId || prevState.currentId
            };
          });

          // If we have a current conversation, load its messages
          const currentId = fetchedConversations[0]?.id;
          if (currentId) {
            await loadMessages(currentId);
          }
        }
        
        return fetchedConversations;
      } else {
        throw new Error(`Failed to load conversations: ${response.status}`);
      }
    } catch (e) {
      console.error("Error loading conversations:", e);
      // If we're not showing history, try to load from localStorage
      if (type !== 'history') {
        const saved = localStorage.getItem("grok3_conversations");
        if (saved) {
          try {
            const parsed = JSON.parse(saved);
            if (Array.isArray(parsed) && parsed.length > 0) {
              const currentId = localStorage.getItem("grok3_current_id");
              setState({
                conversations: parsed,
                currentId: currentId || (parsed[0] ? parsed[0].id : null)
              });
              return parsed;
            }
          } catch (parseError) {
            console.error("Error parsing saved conversations:", parseError);
          }
        }
      }
      throw e; // Re-throw to be caught by the caller
    }
  };

  // Load conversations when component mounts
  useEffect(() => {
    const loadInitialData = async () => {
      try {
        // First try to load from backend
        const loadedConversations = await loadConversations('active');
        
        // If conversations were loaded, ensure we have a current conversation
        if (loadedConversations && loadedConversations.length > 0) {
          const currentConv = loadedConversations.find(c => c.id === currentId) || loadedConversations[0];
          
          // Load messages for the current conversation
          if (currentConv && (!currentConv.loaded || !currentConv.messages || currentConv.messages.length === 0)) {
            await loadMessages(currentConv.id);
          }
          
          return;
        }
        
        // If no conversations were loaded, create a new one
        const newConv = { 
          id: uuidv4(), 
          name: "新会话", 
          title: "新会话",
          messages: [],
          loaded: false
        };
        
        setState({
          conversations: [newConv],
          currentId: newConv.id
        });
        
      } catch (error) {
        console.error('Error loading initial data:', error);
        
        // Fallback to local storage if backend fails
        try {
          const saved = localStorage.getItem("grok3_conversations");
          if (saved) {
            const parsed = JSON.parse(saved);
            if (Array.isArray(parsed) && parsed.length > 0) {
              const savedCurrentId = localStorage.getItem("grok3_current_id") || parsed[0].id;
              setState({
                conversations: parsed,
                currentId: savedCurrentId
              });
              
              // Load messages for the current conversation
              const currentConv = parsed.find(c => c.id === savedCurrentId) || parsed[0];
              if (currentConv && (!currentConv.loaded || !currentConv.messages || currentConv.messages.length === 0)) {
                await loadMessages(currentConv.id);
              }
              
              return;
            }
          }
        } catch (e) {
          console.error('Error loading from localStorage:', e);
        }
        
        // If all else fails, create a new conversation
        const newConv = { 
          id: uuidv4(), 
          name: "新会话", 
          title: "新会话",
          messages: [],
          loaded: false
        };
        
        setState({
          conversations: [newConv],
          currentId: newConv.id
        });
      }
    };
    
    loadInitialData();
  }, []);

  const [showDelete, setShowDelete] = useState(false);

  // 保证 conversations 和 currentId 同步更新
  function setConversationsAndCurrentId(newConvs, id) {
    setState(prevState => {
      const conversations = typeof newConvs === 'function' ? newConvs(prevState.conversations) : newConvs;
      const currentId = id !== undefined ? id : (conversations[0] ? conversations[0].id : 1);
      localStorage.setItem("grok3_conversations", JSON.stringify(conversations));
      localStorage.setItem("grok3_current_id", String(currentId));
      console.log('[UPDATE] conversations:', conversations);
      console.log('[UPDATE] currentId:', currentId);
      return { conversations, currentId };
    });
  }
  // 兼容原有用法
  const setConversations = (newConvs) => setState(prevState => {
    const conversations = typeof newConvs === 'function' ? newConvs(prevState.conversations) : newConvs;
    localStorage.setItem("grok3_conversations", JSON.stringify(conversations));
    return {
      conversations: conversations,
      currentId: prevState.currentId
    };
  });
  const loadMessages = async (conversationId) => {
    if (!conversationId) {
      console.error('No conversation ID provided to loadMessages');
      return [];
    }

    try {
      const response = await fetch(`/api/conversations/${conversationId}/messages`);
      if (response.ok) {
        const messages = await response.json();
        
        // Ensure messages is an array
        const validMessages = Array.isArray(messages) ? messages : [];
        
        // Update the conversation with the loaded messages
        setState(prevState => {
          const updatedConversations = prevState.conversations.map(conv => 
            conv.id === conversationId 
              ? { 
                  ...conv, 
                  messages: validMessages, 
                  loaded: true,
                  // Preserve name if it exists, otherwise use the first user message as title
                  name: conv.name || validMessages.find(m => m.role === 'user')?.content?.substring(0, 30) || '新会话'
                } 
              : conv
          );
          
          // Save to localStorage if this is the current conversation
          if (prevState.currentId === conversationId) {
            localStorage.setItem("grok3_conversations", JSON.stringify(updatedConversations));
          }
          
          return {
            ...prevState,
            conversations: updatedConversations
          };
        });
        
        return validMessages;
      } else {
        throw new Error(`Failed to load messages: ${response.status}`);
      }
    } catch (error) {
      console.error('Error loading messages:', error);
      
      // Fallback to any messages we might have in memory
      const currentConv = conversations.find(c => c.id === conversationId);
      if (currentConv?.messages?.length > 0) {
        return currentConv.messages;
      }
      
      return [];
    }
  };

  const setCurrentId = async (id) => {
    // Don't do anything if already current
    if (id === currentId) return;
    
    // First update the current ID
    setState(prevState => ({
      ...prevState,
      currentId: id
    }));
    localStorage.setItem("grok3_current_id", String(id));
    
    // Check if we need to load messages for this conversation
    const currentConv = conversations.find(c => c.id === id);
    if (currentConv && (!currentConv.loaded && (!currentConv.messages || currentConv.messages.length === 0))) {
      await loadMessages(id);
    }
    
    // Close mobile sidebar if open
    setShowMobileSidebar(false);
  };

  const currentConv = conversations.find(c => c.id === currentId);

  // 用 useEffect 监控 currentId/conversations，自动修正无效 currentId
  useEffect(() => {
    if (!conversations.find(c => c.id === currentId) && conversations.length > 0) {
      const fallbackId = conversations[0].id;
      setState(state => {
        localStorage.setItem("grok3_current_id", String(fallbackId));
        return { ...state, currentId: fallbackId };
      });
    }
  }, [currentId, conversations]);

  console.log('[RENDER] conversations:', conversations);
  console.log('[RENDER] currentId:', currentId);
  console.log('[RENDER] localStorage.grok3_conversations:', localStorage.getItem('grok3_conversations'));
  console.log('[RENDER] localStorage.grok3_current_id:', localStorage.getItem('grok3_current_id'));



  // 新建会话
  const addConversation = () => {
    setSelectedModel("grok-3-mini"); // Reset model to default for new conversation
    const newId = uuidv4(); // Use UUID for new conversation ID
    setConversationsAndCurrentId(
      [...conversations, { id: newId, name: `新会话`, messages: [] }], // Default name to '新会话'
      newId
    );
  };


  // 删除会话
  const deleteConversation = () => {
    const newList = conversations.filter(c => c.id !== currentId);
    // TODO: Also delete from backend
    if (newList.length > 0) {
      setConversationsAndCurrentId(newList, newList[0].id);
    } else {
      // If no conversations left, create a new one
      addConversation();
    }
    setShowDelete(false);
  };

  // 用 grok-3-mini 自动归纳标题
  const summarizeTitleAI = async (messages) => {
    try {
      const response = await fetch("/api/title_summary", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ messages, conversation_id: currentId }), // Pass conversation_id
      });
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      return data.title;
    } catch (error) {
      console.error("Error summarizing title:", error);
      return "新会话";
    }
  };

  // 发送消息
  const sendMessage = async (text) => {
    if (!text.trim()) return;
    const conv = conversations.find(c => c.id === currentId);
    if (!conv) return;

    const userMessage = { role: "user", content: text };
    // 立即更新 UI
    setConversations(convs =>
      convs.map(c =>
        c.id === currentId
          ? { ...c, messages: [...c.messages, userMessage] }
          : c
      )
    );

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: text,
          model: selectedModel,
          history: conv.messages, // 传递当前会话的历史消息
          conversation_id: currentId, // Pass conversation_id
        }),
      });
      // 流式读取
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let result = "";
      // 先插入一个空的 assistant 消息
      setConversations(convs =>
        convs.map(c =>
          c.id === currentId
            ? { ...c, messages: [...c.messages, { role: "assistant", content: "" }] }
            : c
        )
      );
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        result += decoder.decode(value);
        // 实时更新最后一条 assistant 消息内容
        setConversations(convs =>
          convs.map(c => {
            if (c.id !== currentId) return c;
            const msgs = [...c.messages];
            // 找到最后一条 assistant 消息并更新
            for (let i = msgs.length - 1; i >= 0; i--) {
              if (msgs[i].role === "assistant") {
                msgs[i] = { ...msgs[i], content: result };
                break;
              }
            }
            return { ...c, messages: msgs };
          })
        );
      }
      // assistant 回复结束后自动归纳标题
      const updatedConv = conversations.find(c => c.id === currentId);
      if (updatedConv) {
        // Use the messages from the state after the assistant's message has been added
        const msgsForTitleSummary = [...updatedConv.messages, { role: "assistant", content: result }];
        const title = await summarizeTitleAI(msgsForTitleSummary);
        setConversations(convs =>
          convs.map(c =>
            c.id === currentId ? { ...c, name: title } : c
          )
        );
      }
    } catch (err) {
      console.error("Error sending message:", err);
      setConversations(convs =>
        convs.map(c =>
          c.id === currentId
            ? { ...c, messages: [...c.messages, { role: "assistant", content: "[AI接口请求失败]" }] }
            : c
        )
      );
      setLastFailedQuestion(text);
      setShowRetry(true);
    }
  };

  // 重试上次提问
  const handleRetry = () => {
    if (lastFailedQuestion) {
      sendMessage(lastFailedQuestion);
    }
  };


  // 复制会话
  const copyConversation = () => {
    if (!currentConv || !currentConv.messages.length) {
      alert("当前会话没有内容");
      return;
    }
    const text = currentConv.messages.map(m => (m.role === "user" ? "Q: " : "A: ") + m.content).join("\n\n");
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        alert("会话内容已复制");
      }, () => {
        alert("复制失败，请手动复制");
      });
    } else {
      // 兼容旧浏览器
      const textarea = document.createElement('textarea');
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand('copy');
        alert("会话内容已复制");
      } catch {
        alert("复制失败，请手动复制");
      }
      document.body.removeChild(textarea);
    }
  };

  const [isMobile, setIsMobile] = useState(window.innerWidth <= 600);

  useEffect(() => {
    const handleResize = () => {
      const mobile = window.innerWidth <= 600;
      setIsMobile(mobile);
      if (!mobile) {
        setShowMobileSidebar(false);
      }
    };
    
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const toggleMobileSidebar = () => {
    setShowMobileSidebar(!showMobileSidebar);
  };

  // Mobile menu button
  const mobileMenuButton = (
    <button 
      className="mobile-menu-button"
      onClick={toggleMobileSidebar}
      style={{
        position: 'fixed',
        top: '10px',
        left: '10px',
        zIndex: 100,
        background: '#f8f8fa',
        border: '1px solid #ddd',
        borderRadius: '4px',
        padding: '8px',
        cursor: 'pointer'
      }}
    >
      <FontAwesomeIcon icon={faHistory} />
    </button>
  );

  return (
    <div className={`app-root ${showMobileSidebar ? 'mobile-sidebar-visible' : ''}`}>
      {/* Sidebar */}
      <div className={`sidebar-container ${showMobileSidebar ? 'mobile-visible' : ''}`}>
        <Sidebar
          conversations={conversations}
          currentId={currentId}
          setCurrentId={setCurrentId}
          addConversation={addConversation}
          showHistory={showHistory}
          setShowHistory={setShowHistory}
          loadConversations={loadConversations}
          onClose={toggleMobileSidebar}
        />
      </div>
      
      {/* Main Content */}
      <div className="main" onClick={() => showMobileSidebar && setShowMobileSidebar(false)}>
        {/* Mobile Menu Button */}
        {isMobile && mobileMenuButton}
        
        {/* Desktop Header */}
        <div className="desktop-header" style={{display: isMobile ? 'none' : 'flex', justifyContent:'flex-end', alignItems:'center', padding:'8px 0'}}>
          <div className="header-actions">
            <button 
              className="history-toggle" 
              onClick={() => {
                const newShowHistory = !showHistory;
                setShowHistory(newShowHistory);
                loadConversations(newShowHistory ? 'history' : 'active');
              }}
              style={{
                background: '#f8f8fa',
                border: '1px solid #eee',
                borderRadius: '4px',
                padding: '6px 12px',
                marginRight: '8px',
                cursor: 'pointer'
              }}
            >
              <FontAwesomeIcon icon={showHistory ? faComment : faHistory} />
              {showHistory ? ' 活跃会话' : ' 历史会话'}
            </button>
            {conversations.length > 0 && (
              <button 
                onClick={() => setShowDelete(true)} 
                style={{
                  background: '#f8f8fa',
                  border: '1px solid #eee',
                  borderRadius: '8px',
                  padding: '6px 18px',
                  fontSize: '1em',
                  color: '#d9534f',
                  cursor: 'pointer'
                }}
              >
                删除会话
              </button>
            )}
          </div>
        </div>
        
        {/* Chat Window */}
        <div className="chat-container">
          {currentConv ? (
            <ChatWindow messages={currentConv.messages || []} />
          ) : (
            <div className="no-conversation" style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              padding: '20px',
              textAlign: 'center'
            }}>
              <p>没有找到对话，请创建一个新会话</p>
              <button 
                onClick={addConversation} 
                style={{
                  marginTop: '20px',
                  padding: '8px 16px',
                  background: '#007bff',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '1em'
                }}
              >
                <FontAwesomeIcon icon={faPlus} /> 新会话
              </button>
            </div>
          )}
        </div>
        
        {/* Input Bar */}
        <InputBar
          onSend={sendMessage}
          onCopy={copyConversation}
          selectedModel={selectedModel}
          onModelChange={setSelectedModel}
          onRetry={showRetry ? handleRetry : undefined}
        />
      </div>
      
      {/* Delete Confirmation Dialog */}
      {showDelete && (
        <ConfirmDialog
          onConfirm={deleteConversation}
          onCancel={() => setShowDelete(false)}
        />
      )}
    </div>
  );
}
