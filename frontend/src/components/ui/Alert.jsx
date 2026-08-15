// tone: 'danger' (emergency/error — the only place red is used) | 'info'
export default function Alert({ tone = 'info', icon, children, className = '' }) {
  return (
    <div className={`ui-alert ui-alert-${tone} ${className}`} role={tone === 'danger' ? 'alert' : 'status'}>
      {icon && <span className="ui-alert-icon" aria-hidden="true">{icon}</span>}
      <span>{children}</span>
    </div>
  );
}
