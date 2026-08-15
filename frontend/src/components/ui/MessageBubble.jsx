export default function MessageBubble({ sender = 'bot', children, actions }) {
  return (
    <div className={`bubble ${sender}`}>
      {children}
      {actions}
    </div>
  );
}
