export default function Card({ className = '', children, ...props }) {
  return (
    <div className={`ui-card ${className}`} {...props}>
      {children}
    </div>
  );
}
