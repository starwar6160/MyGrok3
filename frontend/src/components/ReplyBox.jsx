import React from "react";

// 工具函数：分离markdown代码块和正文
function splitContent(content) {
  const regex = /```([\w]*)\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;
  const result = [];
  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      result.push({ type: "text", text: content.slice(lastIndex, match.index) });
    }
    result.push({ type: "code", lang: match[1], code: match[2] });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < content.length) {
    result.push({ type: "text", text: content.slice(lastIndex) });
  }
  return result;
}

// 工具函数：按中文标点和换行分段
function splitByPunctuation(text) {
  // 按“。！？\n”分割，保留标点
  return text.split(/([。！？\n])/).reduce((arr, cur, idx, src) => {
    if (["。", "！", "？", "\n"].includes(cur)) {
      arr[arr.length - 1] += cur === "\n" ? "" : cur;
      arr.push("");
    } else if (cur) {
      arr.push(cur);
    }
    return arr;
  }, []).filter(Boolean);
}

export default function ReplyBox({ content }) {
  const parts = splitContent(content);

  // 复制全部内容
  const handleCopy = () => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(content);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = content;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
  };

  // 复制代码块
  const handleCopyCode = code => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(code).then(() => {
        // 简单反馈
        alert('代码已复制');
      });
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = code;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      alert('代码已复制');
    }
  };


  return (
    <div className="pre-code-box" style={{display: 'block'}}>
      <span className="ai-label">A:</span>
      <div className="ai-content" style={{padding: 0}}>
        {parts.map((part, i) => {
          if (part.type === "code") {
            return (
              <div className="code-block" key={i} style={{position:'relative', margin:'10px 0'}}>
                <pre style={{background:'#222',color:'#fff',padding:'12px',borderRadius:'7px',fontSize:'1em',overflowX:'auto'}}>
                  <code>{part.code}</code>
                </pre>
                <button className="copy-btn" style={{position:'absolute',top:8,right:10}} onClick={()=>handleCopyCode(part.code)} title="复制代码">📋</button>
                {part.lang && <span style={{position:'absolute',top:8,left:12,color:'#aaa',fontSize:'0.9em'}}>{part.lang}</span>}
              </div>
            );
          } else {
            // 正文分句渲染
            const sentences = splitByPunctuation(part.text);
            return sentences.map((sent, j) => sent.trim() ? <span key={i+"-"+j} style={{display:'block',whiteSpace:'pre-wrap',marginBottom:4}}>{sent}</span> : null);
          }
        })}
      </div>
      <button className="copy-btn" onClick={handleCopy} title="复制全部" style={{position:'absolute',top:10,right:10}}>📋</button>
    </div>
  );
}
