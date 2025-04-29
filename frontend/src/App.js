import React, { useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatWindow from "./components/ChatWindow";
import InputBar from "./components/InputBar";
import ConfirmDialog from "./components/ConfirmDialog";
import "./index.css";

const initialConversations = [
  { id: 1, name: "会话1", messages: [] }
];

export default function App() {
  const [selectedModel, setSelectedModel] = useState("grok-3-mini");
  const [conversations, setConversations] = useState(initialConversations);
  const [currentId, setCurrentId] = useState(1);
  const [showDelete, setShowDelete] = useState(false);

  const currentConv = conversations.find(c => c.id === currentId);

  // 新建会话
  const addConversation = () => {
    const newId = Date.now();
    setConversations([...conversations, { id: newId, name: `会话${conversations.length+1}`, messages: [] }]);
    setCurrentId(newId);
  };

  // 删除会话
  const deleteConversation = () => {
    const newList = conversations.filter(c => c.id !== currentId);
    setConversations(newList.length ? newList : [{ id: 1, name: "会话1", messages: [] }]);
    setCurrentId(newList.length ? newList[0].id : 1);
    setShowDelete(false);
  };

  // 发送消息
  const sendMessage = async (text) => {
    // ...
    // 使用 selectedModel

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
    const text = currentConv.messages.map(m => (m.role === "user" ? "Q: " : "A: ") + m.content).join("\n\n");
    navigator.clipboard.writeText(text);
    alert("会话内容已复制");
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
        <ChatWindow messages={currentConv.messages} />
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
