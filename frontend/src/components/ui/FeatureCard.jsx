export default function FeatureCard({ icon, title, description }) {
  return (
    <div className="feature-card">
      <div className="feature-card-icon" aria-hidden="true">{icon}</div>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}
