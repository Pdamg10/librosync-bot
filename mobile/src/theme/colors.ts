export const colors = {
  dark: {
    background: '#0f172a',
    surface: '#1e293b',
    surfaceLight: '#334155',
    border: '#334155',
    text: '#f8fafc',
    textSecondary: '#94a3b8',
    textMuted: '#64748b',
    primary: '#6366f1',
    primaryLight: '#818cf8',
    accent: '#38bdf8',
    success: '#10b981',
    warning: '#f59e0b',
    danger: '#ef4444',
    cardShadow: 'rgba(0, 0, 0, 0.4)',
  },
  light: {
    background: '#f8fafc',
    surface: '#ffffff',
    surfaceLight: '#f1f5f9',
    border: '#e2e8f0',
    text: '#0f172a',
    textSecondary: '#64748b',
    textMuted: '#94a3b8',
    primary: '#4f46e5',
    primaryLight: '#6366f1',
    accent: '#0284c7',
    success: '#059669',
    warning: '#d97706',
    danger: '#dc2626',
    cardShadow: 'rgba(0, 0, 0, 0.08)',
  },
  sepia: {
    background: '#fcf6ea',
    surface: '#f4ebd4',
    surfaceLight: '#ebe0c4',
    border: '#dfd2b5',
    text: '#443627',
    textSecondary: '#6b5840',
    textMuted: '#927d63',
    primary: '#b45309',
    primaryLight: '#d97706',
    accent: '#b45309',
    success: '#047857',
    warning: '#b45309',
    danger: '#b91c1c',
    cardShadow: 'rgba(68, 54, 39, 0.1)',
  },
  cream: {
    background: '#EFE8DE',
    canvas: '#F5EFE6',
    surface: '#FBF8F3',
    surfaceLight: '#F3ECE1',
    border: '#DFD5C6',
    borderLight: '#ECE4D8',
    text: '#2C221E',
    textSecondary: '#7A6E65',
    textMuted: '#A39587',
    primary: '#2C2523',
    primaryLight: '#4A3E39',
    accent: '#E05A47',
    success: '#3B8B67',
    warning: '#EAA023',
    danger: '#D94D38',
    bookmarkRibbon: '#EAA023',
    shelfWood: '#D8CEBF',
    shelfShadow: 'rgba(60, 48, 40, 0.12)',
    cardShadow: 'rgba(60, 48, 40, 0.12)',
  },
};

export const BOOK_GENRE_PALETTES: Record<string, { bg: string; text: string; accent: string; spine: string; ribbon: string }> = {
  'romance': { bg: '#E26D5C', text: '#FFFFFF', accent: '#FFE3DC', spine: '#C85141', ribbon: '#EAA023' },
  'dark romance': { bg: '#3B2F3E', text: '#FFFFFF', accent: '#D6A2E8', spine: '#29202B', ribbon: '#9D4EDD' },
  'fantas': { bg: '#2D6A4F', text: '#FFFFFF', accent: '#D8F3DC', spine: '#1B4332', ribbon: '#EAA023' },
  'ficci': { bg: '#1B4965', text: '#FFFFFF', accent: '#BEE9E8', spine: '#133549', ribbon: '#F4A261' },
  'terror': { bg: '#262A2E', text: '#FFFFFF', accent: '#CED4DA', spine: '#181A1C', ribbon: '#E63946' },
  'misterio': { bg: '#2B4162', text: '#FFFFFF', accent: '#E0E1DD', spine: '#1C2C43', ribbon: '#EAA023' },
  'thriller': { bg: '#3D314A', text: '#FFFFFF', accent: '#E0A96D', spine: '#271F30', ribbon: '#E05A47' },
  'autoayuda': { bg: '#C77D34', text: '#FFFFFF', accent: '#FEEAA1', spine: '#A26022', ribbon: '#EAA023' },
  'desarrollo': { bg: '#588157', text: '#FFFFFF', accent: '#DAD7CD', spine: '#3A5A40', ribbon: '#EAA023' },
  'manga': { bg: '#E76F51', text: '#FFFFFF', accent: '#FFE8D6', spine: '#C95337', ribbon: '#F4A261' },
  'ensayo': { bg: '#6B705C', text: '#FFFFFF', accent: '#DDBEA9', spine: '#4F5344', ribbon: '#EAA023' },
  'default': { bg: '#385A7C', text: '#FFFFFF', accent: '#D4E2ED', spine: '#26425E', ribbon: '#EAA023' },
};

export function getBookPalette(genre: string) {
  if (!genre) return BOOK_GENRE_PALETTES['default'];
  const g = genre.toLowerCase();
  for (const [key, palette] of Object.entries(BOOK_GENRE_PALETTES)) {
    if (key !== 'default' && g.includes(key)) {
      return palette;
    }
  }
  return BOOK_GENRE_PALETTES['default'];
}

export const GENRE_EMOJIS: Record<string, string> = {
  'Todos': '📚',
  'Dark Romance': '🖤',
  'Romance': '💖',
  'Fantasía': '🧙‍♂️',
  'Fantasia': '🧙‍♂️',
  'Ciencia Ficción': '🚀',
  'Ciencia Ficcion': '🚀',
  'Sci-Fi': '🚀',
  'Terror': '👻',
  'Horror': '👻',
  'Misterio': '🕵️',
  'Thriller': '🔍',
  'Policial': '🚓',
  'Desarrollo Personal': '🌱',
  'Autoayuda': '🌱',
  'Historia': '📜',
  'Filosofía': '🏛️',
  'Poesía': '✒️',
  'Aventura': '🗺️',
  'General': '📖',
};

export function getGenreEmoji(genre: string): string {
  if (!genre) return '📖';
  const match = Object.keys(GENRE_EMOJIS).find(
    (k) => k.toLowerCase() === genre.trim().toLowerCase()
  );
  return match ? GENRE_EMOJIS[match] : '📖';
}
