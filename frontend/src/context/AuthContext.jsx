import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { AuthContext } from './auth-context';

const TOKEN_KEY = 'healora_token';

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(() => !!localStorage.getItem(TOKEN_KEY));

  useEffect(() => {
    if (!token) return;

    let cancelled = false;
    api
      .me(token)
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(() => {
        if (!cancelled) {
          setToken(null);
          localStorage.removeItem(TOKEN_KEY);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  const persistToken = (t) => {
    setToken(t);
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  };

  const login = async (email, password) => {
    const data = await api.login(email, password);
    setUser(data.user);
    persistToken(data.token);
    return data.user;
  };

  const signup = async (name, email, password) => {
    const data = await api.signup(name, email, password);
    setUser(data.user);
    persistToken(data.token);
    return data.user;
  };

  const logout = () => {
    setUser(null);
    persistToken(null);
  };

  return (
    <AuthContext.Provider value={{ token, user, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
