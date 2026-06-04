// src/lib/api/auth-client.ts
import { 
  LoginRequest, 
  RegisterRequest, 
  RefreshRequest,
  AuthTokens, 
  User, 
  RateLimitError 
} from '@/types/auth';

class AuthAPIClient {
  private baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  async register(data: RegisterRequest): Promise<User> {
    const response = await fetch(`${this.baseUrl}/api/v1/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    const responseData = await response.json();

    if (!response.ok) {
      if (response.status === 409) {
        throw new Error('Email already registered');
      }
      throw new Error(responseData.detail || 'Registration failed');
    }

    return responseData;
  }

  async login(data: LoginRequest): Promise<AuthTokens> {
    const response = await fetch(`${this.baseUrl}/api/v1/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    if (response.status === 429) {
      const retryAfter = response.headers.get('Retry-After');
      throw new RateLimitError(retryAfter ? parseInt(retryAfter) : 60);
    }

    const responseData = await response.json();

    if (!response.ok) {
      throw new Error(responseData.detail || 'Invalid email or password');
    }

    return responseData;
  }

  async refreshToken(refreshToken: string): Promise<AuthTokens> {
    const data: RefreshRequest = { refresh_token: refreshToken };
    
    const response = await fetch(`${this.baseUrl}/api/v1/auth/token/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    const responseData = await response.json();

    if (!response.ok) {
      throw new Error('Token refresh failed');
    }

    return responseData;
  }

  async getMe(accessToken: string): Promise<User> {
    const response = await fetch(`${this.baseUrl}/api/v1/auth/me`, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });

    if (!response.ok) {
      throw new Error('Failed to fetch user data');
    }

    return response.json();
  }

  decodeToken(token: string): { sub: string; role: string; exp: number } {
    try {
      const payload = token.split('.')[1];
      return JSON.parse(atob(payload));
    } catch {
      throw new Error('Invalid token');
    }
  }
}

export const authClient = new AuthAPIClient();