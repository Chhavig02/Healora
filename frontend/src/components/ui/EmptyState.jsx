export default function EmptyState({ icon = '📋', title, description, action }) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon" aria-hidden="true">{icon}</div>
      {title && <h4>{title}</h4>}
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}
