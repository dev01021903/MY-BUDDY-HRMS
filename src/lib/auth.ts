import { JWTPayload, SignInCredentials, SignUpCredentials, StoredUser, User, UserRole } from '@/types/auth';
import { SEED_USERS } from './mock-data';

export const USERS_KEY = 'my_buddy_hrms_users_v4';
export const TOKEN_KEY = 'my_buddy_hrms_jwt_v4';
export const THEME_KEY = 'my_buddy_hrms_theme';

export function initLocalStore(): void {
  if (typeof window === 'undefined') return;
  const existing = localStorage.getItem(USERS_KEY);
  if (!existing) {
    localStorage.setItem(USERS_KEY, JSON.stringify(SEED_USERS));
  }
}

export function getStoredUsers(): StoredUser[] {
  if (typeof window === 'undefined') return SEED_USERS;
  try {
    const raw = localStorage.getItem(USERS_KEY);
    return raw ? JSON.parse(raw) : SEED_USERS;
  } catch {
    return SEED_USERS;
  }
}

export function createJWT(user: User): string {
  const header = {
    alg: 'HS256',
    typ: 'JWT',
  };

  const payload: JWTPayload = {
    user_id: user.user_id,
    company_name: user.company_name,
    employee_id: user.employee_id,
    first_name: user.first_name,
    last_name: user.last_name,
    name: user.name || `${user.first_name} ${user.last_name}`.trim(),
    email: user.email,
    role: user.role,
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + 3600 * 24, // 24 hours
  };

  const encodedHeader = btoa(JSON.stringify(header));
  const encodedPayload = btoa(JSON.stringify(payload));
  const signature = 'sig_my_buddy_hrms_v4';

  return `${encodedHeader}.${encodedPayload}.${signature}`;
}

export function parseJWT(token: string): JWTPayload | null {
  try {
    const parts = token.split('.');
    if (parts.length < 2) return null;
    const payloadJson = atob(parts[1]);
    const payload: JWTPayload = JSON.parse(payloadJson);
    
    // Check expiration
    if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

export function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function removeStoredToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
}

export async function loginUser(credentials: SignInCredentials): Promise<{ user: User; token: string }> {
  try {
    const response = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: credentials.email, password: credentials.password })
    });
    if (response.ok) {
      const data = await response.json();
      if (data.success && data.user) {
        const safeUser: User = {
          ...data.user,
          company_name: 'My Buddy',
          user_id: String(data.user.id),
        };
        setStoredToken(data.token);
        return { user: safeUser, token: data.token };
      }
    }
  } catch {
    // Backend unavailable or static export environment
  }

  // Fallback to local storage store for static GitHub Pages hosting
  initLocalStore();
  const users = getStoredUsers();
  const found = users.find(
    (u) =>
      (u.email.toLowerCase() === credentials.email.toLowerCase() ||
        u.employee_id.toLowerCase() === credentials.email.toLowerCase()) &&
      u.password === credentials.password
  );

  if (!found) {
    throw new Error('Invalid Login ID/Email or password credentials.');
  }

  const { password, ...safeUser } = found;
  const token = createJWT(safeUser);
  setStoredToken(token);
  return { user: safeUser, token };
}

export async function registerUser(credentials: SignUpCredentials): Promise<{ user: User; token: string }> {
  const nameParts = credentials.name.trim().split(' ');
  const first_name = nameParts[0] || 'User';
  const last_name = nameParts.slice(1).join(' ') || '';
  const employee_id = credentials.employee_id || `EMP-${Math.floor(1000 + Math.random() * 9000)}`;
  const role: UserRole = credentials.role || 'HR_ADMIN';

  try {
    const response = await fetch('/api/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        employee_id, 
        first_name, 
        last_name, 
        email: credentials.email, 
        password: credentials.password, 
        role 
      })
    });
    if (response.ok) {
      const data = await response.json();
      if (data.success && data.data) {
        const safeUser: User = {
          user_id: String(data.data.user_id),
          company_name: credentials.company_name || 'My Buddy',
          employee_id: data.data.employee_id,
          first_name: data.data.first_name,
          last_name: data.data.last_name,
          email: data.data.email,
          role: data.data.role,
        };
        const token = data.data.verification_token || createJWT(safeUser);
        setStoredToken(token);
        return { user: safeUser, token };
      }
    }
  } catch {
    // Backend unavailable or static export environment
  }

  // Fallback to local storage store for static GitHub Pages hosting
  initLocalStore();
  const users = getStoredUsers();
  const existingUser = users.find((u) => u.email.toLowerCase() === credentials.email.toLowerCase());
  if (existingUser) {
    throw new Error('An account with this email address already exists.');
  }

  const newUser: StoredUser = {
    user_id: `usr_${Date.now()}`,
    company_name: credentials.company_name || 'My Buddy',
    employee_id,
    first_name,
    last_name,
    name: credentials.name.trim(),
    email: credentials.email.trim(),
    role,
    password: credentials.password,
    job_title: role === 'HR_ADMIN' ? 'HR Administrator' : 'Software Engineer',
    department: 'People Operations',
    joining_date: new Date().toISOString().slice(0, 10),
    attendance_status: 'PRESENT',
  };

  const updatedUsers = [...users, newUser];
  localStorage.setItem(USERS_KEY, JSON.stringify(updatedUsers));

  const { password, ...safeUser } = newUser;
  const token = createJWT(safeUser);
  setStoredToken(token);
  return { user: safeUser, token };
}

export function getRedirectPathForRole(_role: UserRole): string {
  return '/dashboard';
}
