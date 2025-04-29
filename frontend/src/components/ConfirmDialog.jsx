import React from "react";
export default function ConfirmDialog({ onConfirm, onCancel }) {
  return (
    <div className="confirm-dialog-bg">
      <div className="confirm-dialog">
        <div>确定要删除当前会话吗？</div>
        <div className="confirm-actions">
          <button className="confirm" onClick={onConfirm}>确定</button>
          <button className="cancel" onClick={onCancel}>取消</button>
        </div>
      </div>
    </div>
  );
}
