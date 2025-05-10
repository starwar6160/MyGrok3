import React from "react";

export default function ReplyBox({ content }) {
  // 复制功能
  const handleCopy = () => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(content);
    } else {
      // fallback
      const textarea = document.createElement("textarea");
      textarea.value = content;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
  };

  return (
    <div className="pre-code-box">
      <span className="ai-label">A:</span>
      <span className="ai-content">{content}</span>
      <button className="copy-btn" onClick={handleCopy} title="复制">📋</button>
    </div>
  );
}
