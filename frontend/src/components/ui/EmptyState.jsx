import { ClipboardList } from 'lucide-react';

export default function EmptyState({ icon = <ClipboardList size={36} />, title, description, action }) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon" aria-hidden="true">{icon}</div>
      {title && <h4>{title}</h4>}
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}
