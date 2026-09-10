const API_URL = '/api/v1';

export const fetchWithAuth = async (endpoint: string, options: RequestInit = {}) => {
  const token = localStorage.getItem('token');
  const headers = new Headers(options.headers || {});
  
  headers.set('Content-Type', 'application/json');
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers,
  });

    if (!response.ok) {
    let errorMsg = 'An error occurred';
    try {
      const data = await response.json();
      if (data.detail) {
        if (typeof data.detail === 'string') {
          errorMsg = data.detail;
        } else if (Array.isArray(data.detail)) {
          // Format FastAPI validation array
          errorMsg = data.detail.map((err: any) => `${err.loc?.slice(-1)}: ${err.msg}`).join(', ');
        } else {
          errorMsg = data.detail.message || JSON.stringify(data.detail);
        }
      }
    } catch (e) {}
    throw new Error(errorMsg);
  }

  return response.json();
};
