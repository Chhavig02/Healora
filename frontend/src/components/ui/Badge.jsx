// tone: 'blue' (default) | 'teal' | 'strong' | 'moderate' | 'possible' | 'danger' | 'neutral'
export default function Badge({ tone = 'blue', className = '', children }) {
  return <span className={`ui-badge ui-badge-${tone} ${className}`}>{children}</span>;
}
