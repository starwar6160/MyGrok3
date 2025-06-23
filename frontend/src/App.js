import React, { useState, useEffect } from "react";
import Sidebar from "./components/Sidebar";
import ChatWindow from "./components/ChatWindow";
import InputBar from "./components/InputBar";
import ConfirmDialog from "./components/ConfirmDialog";
import "./index.css";

const defaultModels = [
  "google/gemini-flash-1.5",
  "anthropic/claude-3-haiku",
  // Add other default models here if needed
];

const initialConversations = [
  { id: 1, name: "会话1", messages: [] }
];

function getInitialState() {
  try {
    // Try to load conversations from localStorage
    const savedConversations = localStorage.getItem("grok3_conversations");
    const savedCurrentId = localStorage.getItem("grok3_current_id");
    
    let conversations = initialConversations;
    let currentId = initialConversations[0].id;
    
    if (savedConversations) {
      const parsed = JSON.parse(savedConversations);
      if (Array.isArray(parsed) && parsed.length > 0) {
        conversations = parsed;
        
        // Set currentId from saved value if it exists and is valid
        if (savedCurrentId) {
          const id = Number(savedCurrentId);
          if (conversations.some(c => c.id === id)) {
            currentId = id;
          }
        }
        
        // Do not set a default selectedModel here; let the backend handle it.
        conversations = conversations.map(conv => ({
          ...conv,
          selectedModel: conv.selectedModel // Keep existing selectedModel, or leave undefined
        }));
      }
    }
    
    return { conversations, currentId };
  } catch (error) {
    console.error('Error loading state from localStorage:', error);
    return {
      conversations: initialConversations.map(conv => ({
        ...conv,
        selectedModel: conv.selectedModel // Keep existing selectedModel, or leave undefined
      })),
      currentId: initialConversations[0].id
    };
  }
}

export default function App() {
  // 新增状态
  const [lastFailedQuestion, setLastFailedQuestion] = useState("");
  const [showRetry, setShowRetry] = useState(false);

  const [models, setModels] = useState((window.appConfig && window.appConfig.models) || defaultModels);
  const [state, setState] = useState(() => {
    const initialState = getInitialState();
    console.log('[INIT] state from localStorage:', initialState);
    return initialState;
  });
  
  const { conversations, currentId } = state;
  const currentConv = conversations.find(c => c.id === currentId);
  const [selectedModel, setSelectedModel] = useState(
    (currentConv && currentConv.selectedModel) || models[0]
  );

  // Custom setter to update both selectedModel and conversation state
  const updateSelectedModel = (newModel) => {
    setSelectedModel(newModel);
    if (currentConv) {
      setState(prev => {
        const updatedConversations = prev.conversations.map(conv =>
          conv.id === currentId
            ? { ...conv, selectedModel: newModel }
            : conv
        );
        localStorage.setItem("grok3_conversations", JSON.stringify(updatedConversations));
        return {
          ...prev,
          conversations: updatedConversations
        };
      });
    }
  };

  // Sync selectedModel with current conversation
  useEffect(() => {
    if (currentConv && currentConv.selectedModel && currentConv.selectedModel !== selectedModel) {
      setSelectedModel(currentConv.selectedModel);
    }
  }, [currentId, currentConv]);
  // 只在切换会话时同步 selectedModel，发送消息时不触发
  const prevId = React.useRef(currentId);
  useEffect(() => {
    if (prevId.current !== currentId) {
      const conv = conversations.find(c => c.id === currentId);
      if (conv && conv.selectedModel) {
        setSelectedModel(conv.selectedModel);
      }
      prevId.current = currentId;
    }
  }, [currentId, conversations]);
  const [showDelete, setShowDelete] = useState(false);

  // 保证 conversations 和 currentId 同步更新
  function setConversationsAndCurrentId(newConvs, id) {
    setState(() => {
      const conversations = typeof newConvs === 'function' ? newConvs(getInitialState().conversations) : newConvs;
      const currentId = id !== undefined ? id : (conversations[0] ? conversations[0].id : 1);
      localStorage.setItem("grok3_conversations", JSON.stringify(conversations));
      localStorage.setItem("grok3_current_id", String(currentId));
      console.log('[UPDATE] conversations:', conversations);
      console.log('[UPDATE] currentId:', currentId);
      return { conversations, currentId };
    });
  }
  // 兼容原有用法
  const setConversations = (newConvs) => setState(state => {
    localStorage.setItem("grok3_conversations", JSON.stringify(typeof newConvs === 'function' ? newConvs(state.conversations) : newConvs));
    return {
      conversations: typeof newConvs === 'function' ? newConvs(state.conversations) : newConvs,
      currentId: state.currentId
    };
  });
  const setCurrentId = (id) => {
    setState(state => {
      localStorage.setItem("grok3_current_id", String(id));
      return {
        conversations: state.conversations,
        currentId: id
      };
    });
    // Also update the selected model when the conversation changes
    const conv = conversations.find(c => c.id === id);
    if (conv && conv.selectedModel) {
      setSelectedModel(conv.selectedModel);
    }
  };

  // currentConv is now defined earlier in the component

  // 用 useEffect 监控 currentId/conversations，自动修正无效 currentId
  React.useEffect(() => {
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
    const newId = Date.now();
    const newConv = { 
      id: newId, 
      name: `新会话${conversations.length + 1}`,
      messages: []
      // 不设置 selectedModel 字段，让后端决定默认
    };

    setState(prev => {
      const newConversations = [...prev.conversations, newConv];
      localStorage.setItem("grok3_conversations", JSON.stringify(newConversations));
      localStorage.setItem("grok3_current_id", String(newId));
      return {
        conversations: newConversations,
        currentId: newId
      };
    });
    // 不再 setSelectedModel，selectedModel 会跟随当前会话或后端默认
  };


  // 删除会话
  const deleteConversation = () => {
    const newList = conversations.filter(c => c.id !== currentId);
    setConversations(newList.length ? newList : [{ id: 1, name: "会话1", messages: [] }]);
    setCurrentId(newList.length ? newList[0].id : 1);
    setShowDelete(false);
  };

  // 发送消息
  // 用 grok-3-mini 自动归纳标题
  async function summarizeTitleAI(messages) {
    try {
      const response = await fetch("/api/title_summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: messages.slice(0, 10) // 只取前10条，避免太长
        })
      });
      const data = await response.json();
      return data.title || "新会话";
    } catch {
      return "新会话";
    }
  }

  const sendMessage = async (text) => {
    setShowRetry(false);
    setLastFailedQuestion("");
    if (!text.trim()) return;
    const updated = conversations.map(c =>
      c.id === currentId
        ? { ...c, messages: [...c.messages, { role: "user", content: text }] }
        : c
    );
    setConversations(updated);

    // 调用后端API获取AI回复
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: text,
          model: selectedModel, // 可根据UI选择
          history: updated.find(c => c.id === currentId).messages
        })
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
            // 保证当前会话的selectedModel被最新选中值覆盖
            return { ...c, messages: msgs, selectedModel: selectedModel };
          })
        );
      }
      // assistant 回复结束后自动归纳标题
      const conv = conversations.find(c => c.id === currentId);
      if (conv) {
        const msgs = [...conv.messages, { role: "assistant", content: result }];
        const title = await summarizeTitleAI(msgs);
        setConversations(convs =>
          convs.map(c =>
            c.id === currentId ? { ...c, name: title } : c
          )
        );
      }
    } catch (err) {
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

  return (
    <div className="app-root">
      <Sidebar
        conversations={conversations}
        currentId={currentId}
        setCurrentId={setCurrentId}
        addConversation={addConversation}
      />
      <div className="main">
        {/* 删除按钮置顶，仅在有会话时显示 */}
        <div style={{display:'flex',justifyContent:'flex-end',alignItems:'center',padding:'8px 0'}}>
          {conversations.length > 0 && (
            <button onClick={() => setShowDelete(true)} style={{background:'#f8f8fa',border:'1px solid #eee',borderRadius:8,padding:'6px 18px',fontSize:'1em',color:'#d9534f',marginRight:12}}>删除会话</button>
          )}
        </div>
        <ChatWindow messages={currentConv ? currentConv.messages : []} />
        <InputBar
          onSend={sendMessage}
          onCopy={copyConversation}
          selectedModel={selectedModel}
          onModelChange={updateSelectedModel}
          onRetry={showRetry ? handleRetry : undefined}
          models={models}
        />
      </div>
      {showDelete && (
        <ConfirmDialog
          onConfirm={deleteConversation}
          onCancel={() => setShowDelete(false)}
        />
      )}
    </div>
  );
}
