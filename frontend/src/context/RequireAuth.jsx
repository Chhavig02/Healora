import { Navigate } from 'react-router-dom';
import { useAuth } from './useAuth';

export default function RequireAuth({ children }) {
  const { token, loading } = useAuth();

  if (loading) return <div className="auth-loading">Loading…</div>;
  if (!token) return <Navigate to="/login" replace />;
  return children;
}
