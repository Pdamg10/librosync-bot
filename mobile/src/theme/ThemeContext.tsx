import React, { createContext, useContext, useState, useEffect } from 'react';

export type BackgroundType = 'solid' | 'gradient' | 'media';

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
  gradientColors: [string, string];
  gradientAngle: number;
  mediaUri: string | null;
  mediaName: string | null;
  mediaOverlayOpacity: number;
  isDark: boolean;
  colors: ThemeColors;
}

const LIGHT_CREAM_COLORS: ThemeColors = {
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

const DARK_OBSIDIAN_COLORS: ThemeColors = {
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

const SEPIA_VINTAGE_COLORS: ThemeColors = {
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

const MATCHA_TEA_COLORS: ThemeColors = {
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

const MIDNIGHT_BLUE_COLORS: ThemeColors = {
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

interface ThemeContextType {
  theme: CustomThemeState;
  setSolidTheme: (hex: string, isDark?: boolean, palette?: ThemeColors) => void;
  setGradientTheme: (colors: [string, string], isDark?: boolean) => void;
  setMediaTheme: (uri: string, name?: string, opacity?: number, isDark?: boolean) => void;
  setMediaOverlayOpacity: (opacity: number) => void;
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
  setMediaTheme: () => {},
  setMediaOverlayOpacity: () => {},
  resetToDefault: () => {},
});

export const PRESET_THEMES = {
  cream: { name: 'Crema Anaquel (Original)', hex: '#EFE8DE', isDark: false, colors: LIGHT_CREAM_COLORS },
  sepia: { name: 'Sepia Pergamino', hex: '#EADBBE', isDark: false, colors: SEPIA_VINTAGE_COLORS },
  matcha: { name: 'Verde Matcha', hex: '#E3E9DC', isDark: false, colors: MATCHA_TEA_COLORS },
  linen: { name: 'Blanco Lino Nórdico', hex: '#FAF8F5', isDark: false, colors: { ...LIGHT_CREAM_COLORS, canvasBg: '#FAF8F5' } },
  obsidian: { name: 'Obsidiana Noche', hex: '#181513', isDark: true, colors: DARK_OBSIDIAN_COLORS },
  midnight: { name: 'Azul Medianoche', hex: '#131A22', isDark: true, colors: MIDNIGHT_BLUE_COLORS },
};

export const PRESET_GRADIENTS: Array<{ id: string; name: string; colors: [string, string]; isDark: boolean }> = [
  { id: 'vintage_cream', name: 'Crema & Marfil Vintage', colors: ['#FAF7F2', '#EFE8DE'], isDark: false },
  { id: 'sunset_glow', name: 'Atardecer Dorado', colors: ['#FFFBEB', '#FCE7C3'], isDark: false },
  { id: 'warm_terracotta', name: 'Crepúsculo Terracota', colors: ['#FFF5F0', '#FAD8C8'], isDark: false },
  { id: 'sage_breeze', name: 'Brisa de Salvia', colors: ['#F2F8F0', '#DCE8D6'], isDark: false },
  { id: 'lavender_dusk', name: 'Lavanda Silvestre', colors: ['#F8F3FC', '#E7D8F2'], isDark: false },
  { id: 'deep_night', name: 'Noche Profunda & Cuero', colors: ['#28221D', '#120F0D'], isDark: true },
  { id: 'cosmic_indigo', name: 'Índigo Cósmico', colors: ['#1C2533', '#0E141D'], isDark: true },
];

export const PRESET_MEDIA_WALLPAPERS: Array<{ id: string; name: string; uri: string; isDark: boolean }> = [
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
];

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setTheme] = useState<CustomThemeState>(defaultTheme);

  const setSolidTheme = (hex: string, isDark = false, palette?: ThemeColors) => {
    let resolvedColors = palette;
    if (!resolvedColors) {
      resolvedColors = isDark
        ? { ...DARK_OBSIDIAN_COLORS, canvasBg: hex }
        : { ...LIGHT_CREAM_COLORS, canvasBg: hex };
    }

    setTheme((prev) => ({
      ...prev,
      backgroundType: 'solid',
      solidColor: hex,
      isDark,
      colors: resolvedColors!,
    }));
  };

  const setGradientTheme = (colors: [string, string], isDark = false) => {
    const resolvedColors = isDark
      ? { ...DARK_OBSIDIAN_COLORS, canvasBg: colors[1] }
      : { ...LIGHT_CREAM_COLORS, canvasBg: colors[1] };

    setTheme((prev) => ({
      ...prev,
      backgroundType: 'gradient',
      gradientColors: colors,
      isDark,
      colors: resolvedColors,
    }));
  };

  const setMediaTheme = (uri: string, name?: string, opacity = 0.45, isDark = true) => {
    const resolvedColors = isDark ? DARK_OBSIDIAN_COLORS : LIGHT_CREAM_COLORS;

    setTheme((prev) => ({
      ...prev,
      backgroundType: 'media',
      mediaUri: uri,
      mediaName: name || 'Fondo personalizado',
      mediaOverlayOpacity: opacity,
      isDark,
      colors: resolvedColors,
    }));
  };

  const setMediaOverlayOpacity = (opacity: number) => {
    setTheme((prev) => ({
      ...prev,
      mediaOverlayOpacity: opacity,
    }));
  };

  const resetToDefault = () => {
    setTheme(defaultTheme);
  };

  return (
    <ThemeContext.Provider
      value={{
        theme,
        setSolidTheme,
        setGradientTheme,
        setMediaTheme,
        setMediaOverlayOpacity,
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
