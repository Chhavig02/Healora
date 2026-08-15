export default function SectionHeading({ tag, title, subtitle, align = 'center' }) {
  return (
    <div className={`section-header section-header-${align}`}>
      {tag && <span className="section-tag">{tag}</span>}
      <h2>{title}</h2>
      {subtitle && <p>{subtitle}</p>}
    </div>
  );
}
