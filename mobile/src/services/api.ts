import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import { Book, TelegramLink, LinkCodeResponse, ReadingState, ShelfSummary, BuddyRead, BuddyReadMember } from '../types';

const STORAGE_KEY_BASE_URL = '@bookapp_api_base_url';

// Default host: En red local Wi-Fi para teléfonos físicos usamos la IP de la máquina host
export const DEFAULT_HOST_URL = 'http://10.46.1.120:8000';
export const FALLBACK_URLS = [
  'http://10.46.1.120:8000',
  'http://10.0.2.2:8000',
  'http://localhost:8000',
];

let BASE_URL = DEFAULT_HOST_URL;
let CURRENT_USER_ID = 1;

// Cargar URL persistida al iniciar
AsyncStorage.getItem(STORAGE_KEY_BASE_URL).then((savedUrl) => {
  if (savedUrl) {
    BASE_URL = savedUrl.replace(/\/+$/, '');
  }
}).catch(() => {});

export function setApiBaseUrl(url: string) {
  BASE_URL = url.replace(/\/+$/, '');
  AsyncStorage.setItem(STORAGE_KEY_BASE_URL, BASE_URL).catch(() => {});
}

export function getApiBaseUrl(): string {
  return BASE_URL;
}

export function getCurrentUserId(): number {
  return CURRENT_USER_ID;
}

export function setCurrentUserId(id: number) {
  CURRENT_USER_ID = id;
}

export async function checkServerHealth(targetUrl?: string): Promise<boolean> {
  const urlToCheck = targetUrl ? targetUrl.replace(/\/+$/, '') : BASE_URL;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3500);
    const res = await fetch(`${urlToCheck}/health`, {
      method: 'GET',
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (!res.ok) return false;
    const data = await res.json();
    return data.status === 'healthy';
  } catch {
    return false;
  }
}

export async function autoDiscoverServer(): Promise<string | null> {
  // Probar la URL actual primero
  if (await checkServerHealth(BASE_URL)) return BASE_URL;

  // Probar candidatos
  for (const candidate of FALLBACK_URLS) {
    if (candidate !== BASE_URL && await checkServerHealth(candidate)) {
      setApiBaseUrl(candidate);
      return candidate;
    }
  }
  return null;
}


export async function fetchBooks(genre?: string, search?: string, telegramLinkId?: number): Promise<Book[]> {
  const params = new URLSearchParams();
  params.append('user_id', String(CURRENT_USER_ID));
  if (genre && genre !== 'Todos') {
    params.append('genre', genre);
  }
  if (search && search.trim()) {
    params.append('search', search.trim());
  }
  if (telegramLinkId) {
    params.append('telegram_link_id', String(telegramLinkId));
  }

  const res = await fetch(`${BASE_URL}/library?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Error ${res.status} al consultar biblioteca`);
  }
  return await res.json();
}

export async function getBookDetail(bookId: number): Promise<Book> {
  const res = await fetch(`${BASE_URL}/library/${bookId}`);
  if (!res.ok) {
    throw new Error(`Error ${res.status} al consultar detalle de libro`);
  }
  return await res.json();
}

export function getBookDownloadUrl(bookId: number): string {
  return `${BASE_URL}/library/${bookId}/file`;
}

export async function updateReadingProgress(bookId: number, progress: number): Promise<Book> {
  const res = await fetch(`${BASE_URL}/library/${bookId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reading_progress: progress }),
  });
  if (!res.ok) {
    throw new Error(`Error ${res.status} al actualizar progreso de lectura`);
  }
  return await res.json();
}

export async function deleteBook(bookId: number): Promise<void> {
  const res = await fetch(`${BASE_URL}/library/${bookId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw new Error(`Error ${res.status} al eliminar libro`);
  }
}

export async function fetchTelegramLinks(): Promise<TelegramLink[]> {
  const res = await fetch(`${BASE_URL}/telegram/links?user_id=${CURRENT_USER_ID}`);
  if (!res.ok) {
    throw new Error(`Error ${res.status} al consultar chats de Telegram`);
  }
  return await res.json();
}

export async function generateLinkCode(): Promise<LinkCodeResponse> {
  const res = await fetch(`${BASE_URL}/auth/telegram/link-code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: CURRENT_USER_ID }),
  });
  if (!res.ok) {
    throw new Error(`Error ${res.status} al generar código de vinculación`);
  }
  return await res.json();
}

export async function uploadBookFromDevice(
  fileUri: string,
  fileName: string,
  title: string,
  author: string,
  genre: string,
  telegramLinkId: number
): Promise<Book> {
  const formData = new FormData();
  formData.append('user_id', String(CURRENT_USER_ID));
  formData.append('telegram_link_id', String(telegramLinkId));
  formData.append('title', title);
  formData.append('author', author || 'Desconocido');
  formData.append('genre', genre || 'General');

  const fileData = {
    uri: fileUri,
    name: fileName,
    type: fileName.toLowerCase().endsWith('.epub') ? 'application/epub+zip' : 'application/pdf',
  } as any;

  formData.append('file', fileData);

  const res = await fetch(`${BASE_URL}/library/upload`, {
    method: 'POST',
    body: formData,
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Error ${res.status} al subir libro: ${errorText}`);
  }

  return await res.json();
}

export async function fetchReadingShelves(userId: number = CURRENT_USER_ID): Promise<ShelfSummary> {
  const res = await fetch(`${BASE_URL}/reading/shelves?user_id=${userId}`);
  if (!res.ok) {
    throw new Error(`Error ${res.status} al obtener estantes de lectura`);
  }
  return await res.json();
}

export async function updateBookReadingState(
  bookId: number,
  state: {
    status?: 'reading' | 'finished' | 'to_read' | 'abandoned';
    is_favorite?: boolean;
    progress_percent?: number;
    current_page?: number;
    total_pages?: number;
    notes?: string;
  },
  userId: number = CURRENT_USER_ID
): Promise<ReadingState> {
  const res = await fetch(`${BASE_URL}/reading/status?user_id=${userId}&book_id=${bookId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(state),
  });
  if (!res.ok) {
    throw new Error(`Error ${res.status} al actualizar estado de lectura`);
  }
  return await res.json();
}

export async function fetchBuddyReads(telegramLinkId?: number, status: string = 'active'): Promise<BuddyRead[]> {
  const params = new URLSearchParams();
  if (telegramLinkId) params.append('telegram_link_id', String(telegramLinkId));
  if (status) params.append('status', status);

  const res = await fetch(`${BASE_URL}/reading/buddy-reads?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Error ${res.status} al obtener lecturas conjuntas`);
  }
  return await res.json();
}

export async function createBuddyRead(
  bookId: number,
  title?: string,
  telegramLinkId?: number,
  userId: number = CURRENT_USER_ID
): Promise<BuddyRead> {
  const res = await fetch(`${BASE_URL}/reading/buddy-reads?user_id=${userId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      book_id: bookId,
      title: title || undefined,
      telegram_link_id: telegramLinkId || undefined,
    }),
  });
  if (!res.ok) {
    throw new Error(`Error ${res.status} al crear lectura conjunta`);
  }
  return await res.json();
}

export async function joinBuddyRead(buddyReadId: number, userId: number = CURRENT_USER_ID): Promise<BuddyReadMember> {
  const res = await fetch(`${BASE_URL}/reading/buddy-reads/${buddyReadId}/join?user_id=${userId}`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(`Error ${res.status} al unirse a la lectura conjunta`);
  }
  return await res.json();
}

export async function updateBuddyReadProgress(
  buddyReadId: number,
  progressPercent: number,
  currentPage?: number,
  userId: number = CURRENT_USER_ID
): Promise<BuddyReadMember> {
  const params = new URLSearchParams({
    user_id: String(userId),
    progress_percent: String(progressPercent),
  });
  if (currentPage !== undefined) {
    params.append('current_page', String(currentPage));
  }

  const res = await fetch(`${BASE_URL}/reading/buddy-reads/${buddyReadId}/progress?${params.toString()}`, {
    method: 'PUT',
  });
  if (!res.ok) {
    throw new Error(`Error ${res.status} al actualizar progreso en lectura conjunta`);
  }
  return await res.json();
}

export async function fetchCoReaders(bookId: number, excludeUserId?: number): Promise<{ count: number; readers: any[] }> {
  const params = new URLSearchParams();
  if (excludeUserId) params.append('exclude_user_id', String(excludeUserId));

  const res = await fetch(`${BASE_URL}/reading/co-readers/${bookId}?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Error ${res.status} al consultar co-lectores`);
  }
  return await res.json();
}

export async function askGriffinAi(
  message: string,
  userId: number = CURRENT_USER_ID,
  telegramLinkId?: number
): Promise<{ reply: string; recommended_books: Book[] }> {
  const res = await fetch(`${BASE_URL}/library/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      user_id: userId,
      telegram_link_id: telegramLinkId,
    }),
  });
  if (!res.ok) {
    throw new Error(`Error ${res.status} al consultar Griffin IA`);
  }
  return await res.json();
}

export async function syncTelegramLibrary(telegramLinkId?: number): Promise<{
  status: string;
  purged_books: number;
  duplicates_removed: number;
  active_books: number;
  active_topics: number;
  message?: string;
}> {
  const url = telegramLinkId
    ? `${BASE_URL}/library/sync?telegram_link_id=${telegramLinkId}`
    : `${BASE_URL}/library/sync`;

  const res = await fetch(url, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(`Error ${res.status} al sincronizar biblioteca`);
  }
  return await res.json();
}


