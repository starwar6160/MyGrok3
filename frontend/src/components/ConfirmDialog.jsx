import React, { useEffect, useRef } from "react";
export default function ConfirmDialog({ onConfirm, onCancel }) {
  const cancelButtonRef = useRef(null);

  useEffect(() => {
    if (cancelButtonRef.current) {
      cancelButtonRef.current.focus();
    }
  }, []);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      onCancel();
    }
  };

  return (
    <div className="confirm-dialog-bg" onKeyDown={handleKeyDown} tabIndex="0">
      <div className="confirm-dialog">
        <div>确定要删除当前会话吗？</div>
        <div className="confirm-actions">
          <button className="confirm" onClick={onConfirm}>确定</button>
          <button className="cancel" ref={cancelButtonRef} onClick={onCancel}>取消</button>
        </div>
      </div>
    </div>
  );
}
