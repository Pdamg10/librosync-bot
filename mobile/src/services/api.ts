import { Platform } from 'react-native';
import { Book, TelegramLink, LinkCodeResponse, ReadingState, ShelfSummary, BuddyRead, BuddyReadMember } from '../types';


// Default host: en emulador Android es 10.0.2.2, en web/iOS es localhost
let BASE_URL = Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000';
let CURRENT_USER_ID = 1;

export function setApiBaseUrl(url: string) {
  // Limpiar trailing slash
  BASE_URL = url.replace(/\/+$/, '');
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

export async function checkServerHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/health`, { method: 'GET' });
    if (!res.ok) return false;
    const data = await res.json();
    return data.status === 'healthy';
  } catch {
    return false;
  }
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

