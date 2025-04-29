import React, { useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatWindow from "./components/ChatWindow";
import InputBar from "./components/InputBar";
import ConfirmDialog from "./components/ConfirmDialog";
import "./index.css";

const initialConversations = [
  { id: 1, name: "会话1", messages: [] }
];

function getInitialState() {
  let conversations = initialConversations;
  let currentId = initialConversations[0].id;
  try {
    const saved = localStorage.getItem("grok3_conversations");
    if (saved) {
      conversations = JSON.parse(saved);
      if (!Array.isArray(conversations) || !conversations.length) {
        conversations = initialConversations;
      }
    }
    const savedId = localStorage.getItem("grok3_current_id");
    if (savedId && conversations.find(c => c.id === Number(savedId))) {
      currentId = Number(savedId);
    } else {
      currentId = conversations[0].id;
    }
  } catch {
    conversations = initialConversations;
    currentId = initialConversations[0].id;
  }
  return { conversations, currentId };
}

export default function App() {
  const [selectedModel, setSelectedModel] = useState("grok-3-mini");
  const [{ conversations, currentId }, setState] = useState(() => {
  const state = getInitialState();
  console.log('[INIT] state from localStorage:', state);
  return state;
});
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
  const setCurrentId = (id) => setState(state => {
    localStorage.setItem("grok3_current_id", String(id));
    return {
      conversations: state.conversations,
      currentId: id
    };
  });

  const currentConv = conversations.find(c => c.id === currentId);

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
    setConversationsAndCurrentId(
      [...conversations, { id: newId, name: `会话${conversations.length+1}`, messages: [] }],
      newId
    );
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
            return { ...c, messages: msgs };
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
        <ChatWindow messages={currentConv ? currentConv.messages : []} />
        <InputBar
          onSend={sendMessage}
          onCopy={copyConversation}
          onDelete={() => setShowDelete(true)}
          selectedModel={selectedModel}
          onModelChange={setSelectedModel}
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
