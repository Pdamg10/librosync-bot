export interface Book {
  id: number;
  user_id: number;
  title: string;
  author: string;
  genre: string;
  cover_url?: string | null;
  source: 'app' | 'telegram';
  telegram_link_id?: number | null;
  telegram_message_id?: number | null;
  telegram_file_id?: string | null;
  file_format: 'pdf' | 'epub' | 'mobi' | string;
  reading_progress: number;
  publication_year?: string | null;
  uploaded_at: string;
}

export interface TelegramLink {
  id: number;
  user_id: number;
  chat_id: number;
  chat_type: string;
  chat_title: string;
  bot_is_admin: boolean;
  forum_enabled: boolean;
  linked_at: string;
}

export interface LinkCodeResponse {
  code: string;
  deep_link: string;
  expires_at: string;
}

export type ThemeMode = 'dark' | 'light' | 'sepia';

export interface ReaderSettings {
  fontSize: number;
  theme: ThemeMode;
  lineHeight: number;
}

export interface ReadingState {
  id: number;
  user_id: number;
  book_id: number;
  status: 'reading' | 'finished' | 'to_read' | 'abandoned';
  is_favorite: boolean;
  progress_percent: number;
  current_page?: number | null;
  total_pages?: number | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
  book?: Book;
}

export interface ShelfSummary {
  reading: ReadingState[];
  finished: ReadingState[];
  to_read: ReadingState[];
  favorites: ReadingState[];
  total_tracked: number;
}

export interface BuddyReadMember {
  id: number;
  user_id: number;
  telegram_user_id?: number | null;
  telegram_username?: string | null;
  telegram_name?: string | null;
  progress_percent: number;
  current_page?: number | null;
  status: string;
  joined_at: string;
  last_progress_at: string;
}

export interface BuddyRead {
  id: number;
  book_id: number;
  telegram_link_id?: number | null;
  creator_user_id: number;
  title?: string | null;
  status: string;
  created_at: string;
  book?: Book;
  members: BuddyReadMember[];
}

