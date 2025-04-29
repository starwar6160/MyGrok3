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
    if (!text.trim()) return;
    const updated = conversations.map(c =>
      c.id === currentId
        ? { ...c, messages: [...c.messages, { role: "user", content: text }] }
        : c
    );
    setConversations(updated);

    // 这里模拟AI回复，实际应fetch后端
    setTimeout(() => {
      setConversations(convs =>
        convs.map(c =>
          c.id === currentId
            ? { ...c, messages: [...c.messages, { role: "assistant", content: "AI回复：" + text }] }
            : c
        )
      );
    }, 800);
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
