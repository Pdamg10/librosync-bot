import React, { createContext, useContext, useState, useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

export type BackgroundType = 'solid' | 'gradient' | 'image' | 'gif' | 'video';

export interface ThemeColors {
  canvasBg: string;
  cardBg: string;
  cardBorder: string;
  cardSecondaryBg: string;
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  accent: string;
  shelfBar: string;
  shelfBarEdge: string;
  statusBar: 'dark-content' | 'light-content';
}

export interface CustomThemeState {
  backgroundType: BackgroundType;
  solidColor: string;
  gradientColors: string[];
  gradientAngle: number;
  mediaUri: string | null;
  mediaName: string | null;
  mediaOverlayOpacity: number;
  isDark: boolean;
  colors: ThemeColors;
}

export const LIGHT_CREAM_COLORS: ThemeColors = {
  canvasBg: '#EFE8DE',
  cardBg: '#FBF8F3',
  cardBorder: '#DFD5C6',
  cardSecondaryBg: '#EDE5D8',
  textPrimary: '#2C221E',
  textSecondary: '#7A6E65',
  textMuted: '#9C8E82',
  accent: '#D97706',
  shelfBar: '#D8CEBF',
  shelfBarEdge: '#C5B7A4',
  statusBar: 'dark-content',
};

export const DARK_OBSIDIAN_COLORS: ThemeColors = {
  canvasBg: '#181513',
  cardBg: '#231F1C',
  cardBorder: '#3D3631',
  cardSecondaryBg: '#2E2824',
  textPrimary: '#FAF7F2',
  textSecondary: '#C5B7A4',
  textMuted: '#8F8377',
  accent: '#EAA023',
  shelfBar: '#2C2521',
  shelfBarEdge: '#1E1916',
  statusBar: 'light-content',
};

export const SEPIA_VINTAGE_COLORS: ThemeColors = {
  canvasBg: '#EADBBE',
  cardBg: '#FAF4E3',
  cardBorder: '#D8CAA5',
  cardSecondaryBg: '#E4D4AE',
  textPrimary: '#382B18',
  textSecondary: '#78644A',
  textMuted: '#9B876C',
  accent: '#B45309',
  shelfBar: '#CFC097',
  shelfBarEdge: '#B9AA83',
  statusBar: 'dark-content',
};

export const MATCHA_TEA_COLORS: ThemeColors = {
  canvasBg: '#E3E9DC',
  cardBg: '#F5F9F1',
  cardBorder: '#C9D4BF',
  cardSecondaryBg: '#D8E2CE',
  textPrimary: '#233221',
  textSecondary: '#5C6D5A',
  textMuted: '#849581',
  accent: '#3E7B44',
  shelfBar: '#C4CEBA',
  shelfBarEdge: '#B0BAA6',
  statusBar: 'dark-content',
};

export const MIDNIGHT_BLUE_COLORS: ThemeColors = {
  canvasBg: '#131A22',
  cardBg: '#1D2733',
  cardBorder: '#314255',
  cardSecondaryBg: '#263445',
  textPrimary: '#EDF2F7',
  textSecondary: '#A0AEC0',
  textMuted: '#718096',
  accent: '#38BDF8',
  shelfBar: '#1E2B3A',
  shelfBarEdge: '#151F2A',
  statusBar: 'light-content',
};

export function isColorDark(hex: string): boolean {
  const cleanHex = hex.replace('#', '');
  if (cleanHex.length < 6) return false;
  const r = parseInt(cleanHex.substring(0, 2), 16);
  const g = parseInt(cleanHex.substring(2, 4), 16);
  const b = parseInt(cleanHex.substring(4, 6), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance < 0.55;
}

const STORAGE_THEME_KEY = '@bookapp_custom_theme_v2';

interface ThemeContextType {
  theme: CustomThemeState;
  setSolidTheme: (hex: string, isDark?: boolean, palette?: ThemeColors) => void;
  setGradientTheme: (colors: string[], isDark?: boolean) => void;
  addGradientColor: (color: string) => void;
  removeGradientColor: (index: number) => void;
  updateGradientColor: (index: number, color: string) => void;
  setMediaTheme: (uri: string, type: 'image' | 'gif' | 'video', name?: string, opacity?: number, isDark?: boolean) => void;
  setMediaOverlayOpacity: (opacity: number) => void;
  toggleContrastMode: () => void;
  resetToDefault: () => void;
}

const defaultTheme: CustomThemeState = {
  backgroundType: 'solid',
  solidColor: '#EFE8DE',
  gradientColors: ['#FAF7F2', '#EFE8DE'],
  gradientAngle: 180,
  mediaUri: null,
  mediaName: null,
  mediaOverlayOpacity: 0.45,
  isDark: false,
  colors: LIGHT_CREAM_COLORS,
};

const ThemeContext = createContext<ThemeContextType>({
  theme: defaultTheme,
  setSolidTheme: () => {},
  setGradientTheme: () => {},
  addGradientColor: () => {},
  removeGradientColor: () => {},
  updateGradientColor: () => {},
  setMediaTheme: () => {},
  setMediaOverlayOpacity: () => {},
  toggleContrastMode: () => {},
  resetToDefault: () => {},
});

export const PRESET_THEMES = {
  cream: { name: 'Crema Anaquel (Original)', hex: '#EFE8DE', isDark: false, colors: LIGHT_CREAM_COLORS },
  linen: { name: 'Blanco Lino Nórdico', hex: '#FAF8F5', isDark: false, colors: { ...LIGHT_CREAM_COLORS, canvasBg: '#FAF8F5' } },
  sepia: { name: 'Sepia Pergamino', hex: '#EADBBE', isDark: false, colors: SEPIA_VINTAGE_COLORS },
  matcha: { name: 'Verde Matcha', hex: '#E3E9DC', isDark: false, colors: MATCHA_TEA_COLORS },
  terracotta: { name: 'Terracota Suave', hex: '#F7E7DF', isDark: false, colors: { ...LIGHT_CREAM_COLORS, canvasBg: '#F7E7DF', accent: '#C25E3E' } },
  sky: { name: 'Cielo Nórdico', hex: '#E2EAF4', isDark: false, colors: { ...LIGHT_CREAM_COLORS, canvasBg: '#E2EAF4', accent: '#2563EB' } },
  lavender: { name: 'Lavanda Niebla', hex: '#EFE9F5', isDark: false, colors: { ...LIGHT_CREAM_COLORS, canvasBg: '#EFE9F5', accent: '#7C3AED' } },
  obsidian: { name: 'Obsidiana Noche', hex: '#181513', isDark: true, colors: DARK_OBSIDIAN_COLORS },
  midnight: { name: 'Azul Medianoche', hex: '#131A22', isDark: true, colors: MIDNIGHT_BLUE_COLORS },
  emerald_dark: { name: 'Bosque Esmeralda', hex: '#122019', isDark: true, colors: { ...DARK_OBSIDIAN_COLORS, canvasBg: '#122019', accent: '#10B981' } },
  burgundy: { name: 'Vino Borgoña', hex: '#241419', isDark: true, colors: { ...DARK_OBSIDIAN_COLORS, canvasBg: '#241419', accent: '#F43F5E' } },
};

export const COLOR_PALETTE_SWATCHES = [
  '#EFE8DE', '#FAF8F5', '#F5EFEB', '#EADBBE', '#E3E9DC', '#F7E7DF',
  '#FCE7F3', '#FEF3C7', '#E0F2FE', '#E0E7FF', '#EDE9FE', '#F3E8FF',
  '#FDE047', '#FB923C', '#F87171', '#34D399', '#38BDF8', '#818CF8',
  '#A78BFA', '#F472B6', '#78716C', '#334155', '#1E293B', '#181513',
  '#131A22', '#122019', '#241419', '#09090B'
];

export const PRESET_GRADIENTS: Array<{ id: string; name: string; colors: string[]; isDark: boolean }> = [
  { id: 'vintage_cream', name: 'Crema & Marfil Vintage', colors: ['#FAF7F2', '#EFE8DE'], isDark: false },
  { id: 'sunset_glow', name: 'Atardecer Dorado', colors: ['#FFFBEB', '#FCE7C3', '#F8D49D'], isDark: false },
  { id: 'warm_terracotta', name: 'Crepúsculo Terracota', colors: ['#FFF5F0', '#FAD8C8', '#F5BCAC'], isDark: false },
  { id: 'sage_breeze', name: 'Brisa de Salvia', colors: ['#F2F8F0', '#DCE8D6', '#C4D8BC'], isDark: false },
  { id: 'lavender_dusk', name: 'Lavanda Silvestre', colors: ['#F8F3FC', '#E7D8F2', '#D3BEE6'], isDark: false },
  { id: 'rose_quartz', name: 'Cuarzo Rosa & Miel', colors: ['#FDF2F8', '#FCE7F3', '#FEF3C7'], isDark: false },
  { id: 'deep_night', name: 'Noche Profunda & Cuero', colors: ['#28221D', '#1B1613', '#120F0D'], isDark: true },
  { id: 'cosmic_indigo', name: 'Índigo Cósmico', colors: ['#1C2533', '#131B26', '#0E141D'], isDark: true },
  { id: 'aurora_dark', name: 'Aurora Boreal Nocturna', colors: ['#0F172A', '#132A24', '#064E3B'], isDark: true },
];

export const PRESET_WALLPAPERS = {
  images: [
    {
      id: 'rustic_wood',
      name: 'Madera de Roble Rústica',
      uri: 'https://images.unsplash.com/photo-1546484475-7f7bd55792da?auto=format&fit=crop&w=1080&q=80',
      isDark: true,
    },
    {
      id: 'antique_library',
      name: 'Estantería Antigua de Libros',
      uri: 'https://images.unsplash.com/photo-1507842229456-11f8e1217036?auto=format&fit=crop&w=1080&q=80',
      isDark: true,
    },
    {
      id: 'cozy_coffee',
      name: 'Café & Lectura Acogedora',
      uri: 'https://images.unsplash.com/photo-1495446815901-a7297e633e8d?auto=format&fit=crop&w=1080&q=80',
      isDark: false,
    },
    {
      id: 'starry_night',
      name: 'Cielo Estrellado de Ensueño',
      uri: 'https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=1080&q=80',
      isDark: true,
    },
  ],
  gifs: [
    {
      id: 'rainy_window',
      name: 'Lluvia en la Ventana de Lectura',
      uri: 'https://media.giphy.com/media/t7Qb8655Z1V9K/giphy.gif',
      isDark: true,
    },
    {
      id: 'fireplace_cozy',
      name: 'Hogar a Leña Acogedor',
      uri: 'https://media.giphy.com/media/3oKIPnAiaMCws8nOsE/giphy.gif',
      isDark: true,
    },
    {
      id: 'coffee_steam',
      name: 'Vapor de Café Caliente',
      uri: 'https://media.giphy.com/media/oLHax51222uy4/giphy.gif',
      isDark: true,
    },
  ],
  videos: [
    {
      id: 'candle_light',
      name: 'Llama Cálida de Vela',
      uri: 'https://assets.mixkit.co/videos/preview/mixkit-flame-of-a-burning-candle-close-up-42898-large.mp4',
      isDark: true,
    },
    {
      id: 'dusty_pages',
      name: 'Páginas al Viento en Biblioteca',
      uri: 'https://assets.mixkit.co/videos/preview/mixkit-turning-the-pages-of-a-book-in-close-up-43181-large.mp4',
      isDark: true,
    },
  ],
};

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setTheme] = useState<CustomThemeState>(defaultTheme);

  // Cargar tema persistido al arrancar la app
  useEffect(() => {
    AsyncStorage.getItem(STORAGE_THEME_KEY).then((json) => {
      if (json) {
        try {
          const parsed = JSON.parse(json);
          if (parsed && parsed.backgroundType) {
            setTheme(parsed);
          }
        } catch {}
      }
    }).catch(() => {});
  }, []);

  const saveThemeState = (newTheme: CustomThemeState) => {
    setTheme(newTheme);
    AsyncStorage.setItem(STORAGE_THEME_KEY, JSON.stringify(newTheme)).catch(() => {});
  };

  const setSolidTheme = (hex: string, explicitIsDark?: boolean, palette?: ThemeColors) => {
    const isDark = explicitIsDark !== undefined ? explicitIsDark : isColorDark(hex);
    let resolvedColors = palette;
    if (!resolvedColors) {
      resolvedColors = isDark
        ? { ...DARK_OBSIDIAN_COLORS, canvasBg: hex }
        : { ...LIGHT_CREAM_COLORS, canvasBg: hex };
    }

    const nextTheme: CustomThemeState = {
      ...theme,
      backgroundType: 'solid',
      solidColor: hex,
      isDark,
      colors: resolvedColors,
    };
    saveThemeState(nextTheme);
  };

  const setGradientTheme = (colors: string[], explicitIsDark?: boolean) => {
    const isDark = explicitIsDark !== undefined
      ? explicitIsDark
      : colors.some((c) => isColorDark(c));

    const resolvedColors = isDark
      ? { ...DARK_OBSIDIAN_COLORS, canvasBg: colors[colors.length - 1] }
      : { ...LIGHT_CREAM_COLORS, canvasBg: colors[colors.length - 1] };

    const nextTheme: CustomThemeState = {
      ...theme,
      backgroundType: 'gradient',
      gradientColors: colors.length >= 2 ? colors : [colors[0], '#EFE8DE'],
      isDark,
      colors: resolvedColors,
    };
    saveThemeState(nextTheme);
  };

  const addGradientColor = (color: string) => {
    const newColors = [...theme.gradientColors, color];
    setGradientTheme(newColors, theme.isDark);
  };

  const removeGradientColor = (index: number) => {
    if (theme.gradientColors.length <= 2) return;
    const newColors = theme.gradientColors.filter((_, i) => i !== index);
    setGradientTheme(newColors, theme.isDark);
  };

  const updateGradientColor = (index: number, color: string) => {
    const newColors = [...theme.gradientColors];
    newColors[index] = color;
    setGradientTheme(newColors, theme.isDark);
  };

  const setMediaTheme = (
    uri: string,
    type: 'image' | 'gif' | 'video',
    name?: string,
    opacity = 0.45,
    isDark = true
  ) => {
    const resolvedColors = isDark ? DARK_OBSIDIAN_COLORS : LIGHT_CREAM_COLORS;

    const nextTheme: CustomThemeState = {
      ...theme,
      backgroundType: type,
      mediaUri: uri,
      mediaName: name || 'Fondo multimedia',
      mediaOverlayOpacity: opacity,
      isDark,
      colors: resolvedColors,
    };
    saveThemeState(nextTheme);
  };

  const toggleContrastMode = () => {
    const nextDark = !theme.isDark;
    const nextColors = nextDark ? DARK_OBSIDIAN_COLORS : LIGHT_CREAM_COLORS;
    const nextTheme: CustomThemeState = {
      ...theme,
      isDark: nextDark,
      colors: {
        ...nextColors,
        canvasBg: theme.backgroundType === 'solid' ? theme.solidColor : nextColors.canvasBg,
      },
    };
    saveThemeState(nextTheme);
  };

  const setMediaOverlayOpacity = (opacity: number) => {
    const nextTheme: CustomThemeState = {
      ...theme,
      mediaOverlayOpacity: opacity,
    };
    saveThemeState(nextTheme);
  };

  const resetToDefault = () => {
    saveThemeState(defaultTheme);
  };

  return (
    <ThemeContext.Provider
      value={{
        theme,
        setSolidTheme,
        setGradientTheme,
        addGradientColor,
        removeGradientColor,
        updateGradientColor,
        setMediaTheme,
        setMediaOverlayOpacity,
        toggleContrastMode,
        resetToDefault,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
};

export function useAppTheme() {
  return useContext(ThemeContext);
}

