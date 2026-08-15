import Badge from './Badge';

const MATCH_LABELS = { strong: 'Strong match', moderate: 'Moderate match', possible: 'Possible match' };
const MATCH_TONE = { strong: 'strong', moderate: 'moderate', possible: 'possible' };
const SEVERE = new Set(['high', 'critical']);

function MatchBadge({ strength }) {
  return <Badge tone={MATCH_TONE[strength] || 'neutral'}>{MATCH_LABELS[strength] || strength}</Badge>;
}

/** Renders a primary result (name, description, matched symptoms, match
 * strength, severity) plus a compact "other possibilities" list — the
 * qualitative match strength only, never a numeric/percentage confidence. */
export default function ConditionCard({ data }) {
  const alternates = (data.possible_conditions || []).filter((c) => c.name !== data.disease);
  const matchedSymptoms = data.symptoms_present || [];

  return (
    <div className="condition-card">
      <div className="condition-card-head">
        <h3 className="condition-card-title">{data.disease}</h3>
        <div className="condition-card-badges">
          <MatchBadge strength={data.match_strength} />
          {data.severity && (
            <Badge tone={SEVERE.has(data.severity) ? 'danger' : 'neutral'}>
              {data.severity[0].toUpperCase() + data.severity.slice(1)} severity
            </Badge>
          )}
        </div>
      </div>

      {data.description && <p className="condition-card-desc">{data.description}</p>}

      {matchedSymptoms.length > 0 && (
        <ul className="condition-symptom-list">
          {matchedSymptoms.map((s, i) => (
            <li key={i}>
              <span className="condition-symptom-check" aria-hidden="true">✓</span>
              {s}
            </li>
          ))}
        </ul>
      )}

      {alternates.length > 0 && (
        <div className="condition-alternates">
          <div className="condition-alternates-label">Other possibilities</div>
          <ul>
            {alternates.map((c, i) => (
              <li key={i}>
                <span>{c.name}</span>
                <MatchBadge strength={c.match_strength} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.disclaimer && <p className="condition-disclaimer">{data.disclaimer}</p>}
    </div>
  );
}
