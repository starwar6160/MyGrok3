import React, { useState, useRef } from "react";
export default function InputBar({ onSend, onCopy, onDelete }) {
  const [text, setText] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const textareaRef = useRef();

  // 动态高度
  const handleFocus = () => {
    setIsFocused(true);
    setTimeout(() => {
      textareaRef.current && textareaRef.current.scrollIntoView({ behavior: "smooth" });
    }, 200);
  };
  const handleBlur = () => setIsFocused(false);

  const handleSend = () => {
    if (text.trim()) {
      onSend(text);
      setText("");
    }
  };

  return (
    <div className="input-bar">
      <textarea
        ref={textareaRef}
        value={text}
        onChange={e => setText(e.target.value)}
        onFocus={handleFocus}
        onBlur={handleBlur}
        rows={isFocused ? 8 : 2}
        style={{
          minHeight: isFocused ? "40vh" : "2.5em",
          maxHeight: "50vh",
          transition: "min-height 0.2s"
        }}
        placeholder="输入你的问题..."
      />
      <div className="input-bar-bottom">
        <div className="action-btns action-btns-bottom">
          <button onClick={handleSend} title="发送">发送</button>
          <button onClick={onCopy} title="复制会话">复制</button>
          <button onClick={onDelete} title="删除会话">删除</button>
        </div>
      </div>
    </div>
  );
}
