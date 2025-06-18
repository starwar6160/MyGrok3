import React, { useState, useRef } from "react";
export default function InputBar({ onSend, onCopy, onDelete, selectedModel, onModelChange, onRetry, models }) {
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
      <div style={{display:'flex',alignItems:'stretch'}}>
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
            transition: "min-height 0.2s",
            flex:1
          }}
          placeholder="输入你的问题..."
        />
        {onRetry && (
          <button
            onClick={onRetry}
            title="刷新/重试"
            style={{marginLeft:8,padding:'0 16px',fontSize:'1.1em',background:'#f0f0f0',border:'1px solid #ccc',borderRadius:6,cursor:'pointer',display:'flex',alignItems:'center'}}>
            🔄
          </button>
        )}
      </div>
      <div className="input-bar-bottom">
        <div className="action-btns action-btns-bottom">
          <div className="left-buttons">
            {/* 删除按钮已移至顶部 */}
          </div>
          <div className="right-buttons">
            <select value={selectedModel} onChange={e => onModelChange(e.target.value)} style={{ marginLeft: 12 }}>
              {models.map(model => (
                <option key={model} value={model}>{model}</option>
              ))}
            </select>
            <button onClick={onCopy} title="复制会话">复制</button>
            <button onClick={handleSend} title="发送">发送</button>
          </div>
        </div>
      </div>
    </div>
  );
}
