export function ConfirmDialog({ title, children, onCancel, onConfirm }: {
  title: string;
  children: React.ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <span className="modal-mark">!</span>
        <h2 id="confirm-title">{title}</h2>
        <div>{children}</div>
        <footer><button onClick={onCancel}>取消</button><button className="danger" onClick={onConfirm}>确认并继续</button></footer>
      </div>
    </div>
  );
}
