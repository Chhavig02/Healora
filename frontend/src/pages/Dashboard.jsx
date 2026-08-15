import { useEffect, useState } from 'react';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import { useAuth } from '../context/useAuth';
import { api } from '../lib/api';

const FREQUENCIES = [
  { value: 'daily', label: 'Daily' },
  { value: 'twice_daily', label: 'Twice daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'as_needed', label: 'As needed' },
];

const EMPTY_FORM = { medication_name: '', dosage: '', time_of_day: '', frequency: 'daily', notes: '' };

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export default function Dashboard({ onOpenChat }) {
  const { user, token, logout } = useAuth();
  const [reminders, setReminders] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const [reloadIndex, setReloadIndex] = useState(0);
  const reload = () => setReloadIndex((i) => i + 1);

  useEffect(() => {
    let cancelled = false;
    api
      .listReminders(token)
      .then((d) => {
        if (!cancelled) setReminders(d.reminders);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, reloadIndex]);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.medication_name.trim()) return;
    setSaving(true);
    setError('');
    try {
      if (editingId) {
        await api.updateReminder(token, editingId, form);
      } else {
        await api.createReminder(token, form);
      }
      setForm(EMPTY_FORM);
      setEditingId(null);
      setShowForm(false);
      reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const edit = (r) => {
    setEditingId(r.id);
    setShowForm(true);
    setForm({
      medication_name: r.medication_name,
      dosage: r.dosage || '',
      time_of_day: r.time_of_day || '',
      frequency: r.frequency || 'daily',
      notes: r.notes || '',
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setShowForm(false);
  };

  const remove = async (id) => {
    if (!confirm('Delete this reminder?')) return;
    try {
      await api.deleteReminder(token, id);
      reload();
    } catch (err) {
      setError(err.message);
    }
  };

  const toggleActive = async (r) => {
    try {
      await api.updateReminder(token, r.id, { active: !r.active });
      reload();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section className="dashboard-section">
      <div className="section-container">
        <div className="dashboard-hdr">
          <div>
            <span className="section-tag">Your Dashboard</span>
            <h1>{greeting()}, {user?.name || 'there'}</h1>
            <p className="dashboard-subtitle">How can Healora help today?</p>
          </div>
          <Button variant="outline" onClick={logout}>Log Out</Button>
        </div>

        {error && <div className="auth-error">{error}</div>}

        {/* QUICK ACTIONS */}
        <div className="quick-actions-grid">
          <button className="quick-action-card" onClick={onOpenChat}>
            <div className="quick-action-icon">💬</div>
            <div>
              <h3>Symptom Check</h3>
              <p>Describe what you're experiencing.</p>
            </div>
          </button>
          <a className="quick-action-card" href="#reminders">
            <div className="quick-action-icon">⏰</div>
            <div>
              <h3>Medication Reminders</h3>
              <p>View today's reminders.</p>
            </div>
          </a>
        </div>

        {/* RECENT ACTIVITY */}
        <div className="dashboard-block">
          <h2 className="dashboard-block-title">Recent activity</h2>
          <div className="ui-card">
            <EmptyState
              icon="🩺"
              title="No recent activity yet"
              description="Start a symptom check to see your health guidance history here."
              action={<Button onClick={onOpenChat}>Start a symptom check</Button>}
            />
          </div>
        </div>

        {/* REMINDERS */}
        <div className="dashboard-block" id="reminders">
          <div className="dashboard-block-hdr">
            <h2 className="dashboard-block-title">Today's reminders</h2>
            {!showForm && (
              <Button size="sm" onClick={() => setShowForm(true)}>+ Add reminder</Button>
            )}
          </div>

          {showForm && (
            <form className="reminder-form" onSubmit={submit}>
              <input
                placeholder="Medication name *"
                value={form.medication_name}
                onChange={(e) => setForm({ ...form, medication_name: e.target.value })}
                required
              />
              <input
                placeholder="Dosage (e.g. 500mg)"
                value={form.dosage}
                onChange={(e) => setForm({ ...form, dosage: e.target.value })}
              />
              <input
                type="time"
                value={form.time_of_day}
                onChange={(e) => setForm({ ...form, time_of_day: e.target.value })}
                aria-label="Time"
              />
              <select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })} aria-label="Frequency">
                {FREQUENCIES.map((f) => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
              <input
                placeholder="Notes"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
              />
              <div className="reminder-form-actions">
                <Button type="submit" disabled={saving}>
                  {editingId ? 'Save changes' : 'Add reminder'}
                </Button>
                <Button type="button" variant="ghost" onClick={cancelEdit}>Cancel</Button>
              </div>
            </form>
          )}

          {loading ? (
            <p className="dashboard-loading">Loading reminders…</p>
          ) : reminders.length === 0 ? (
            !showForm && (
              <div className="ui-card">
                <EmptyState
                  icon="💊"
                  title="No reminders yet"
                  description="Add your first medication to get started."
                  action={<Button onClick={() => setShowForm(true)}>+ Add reminder</Button>}
                />
              </div>
            )
          ) : (
            <div className="reminder-list">
              {reminders.map((r) => (
                <div key={r.id} className={`reminder-card ${r.active ? '' : 'inactive'}`}>
                  <div className="reminder-card-main">
                    <div className="reminder-card-title-row">
                      <strong>{r.medication_name}</strong>
                      {r.dosage && <span className="reminder-dosage">{r.dosage}</span>}
                    </div>
                    <div className="reminder-meta">
                      {r.time_of_day && <Badge tone="blue">{r.time_of_day}</Badge>}
                      <Badge tone="teal">{FREQUENCIES.find((f) => f.value === r.frequency)?.label || r.frequency}</Badge>
                      <Badge tone={r.active ? 'strong' : 'danger'}>{r.active ? 'Active' : 'Paused'}</Badge>
                    </div>
                    {r.notes && <p className="reminder-notes">{r.notes}</p>}
                  </div>
                  <div className="reminder-card-actions">
                    <Button variant="ghost" size="sm" onClick={() => edit(r)}>Edit</Button>
                    <Button variant="ghost" size="sm" onClick={() => toggleActive(r)}>{r.active ? 'Pause' : 'Resume'}</Button>
                    <Button variant="danger" size="sm" onClick={() => remove(r.id)}>Delete</Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
