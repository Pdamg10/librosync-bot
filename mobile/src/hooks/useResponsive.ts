import { useWindowDimensions } from 'react-native';

export interface ResponsiveLayout {
  isTablet: boolean;
  isLandscape: boolean;
  width: number;
  height: number;
  numColumns: number;
  horizontalPadding: number;
  cardWidth: number;
}

export function useResponsive(): ResponsiveLayout {
  const { width, height } = useWindowDimensions();

  const isTablet = width >= 768;
  const isLandscape = width > height;

  // Determinar columnas del catálogo
  let numColumns = 1;
  if (isTablet) {
    numColumns = isLandscape ? 4 : 3;
  } else {
    numColumns = isLandscape ? 2 : 1;
  }

  const horizontalPadding = isTablet ? 24 : 16;
  const totalGutter = (numColumns - 1) * 12;
  const availableWidth = width - (horizontalPadding * 2) - totalGutter;
  const cardWidth = Math.floor(availableWidth / numColumns);

  return {
    isTablet,
    isLandscape,
    width,
    height,
    numColumns,
    horizontalPadding,
    cardWidth,
  };
}
