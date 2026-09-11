import React from 'react';
import { View, StyleSheet, Image, ViewProps } from 'react-native';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';
import { useAppTheme } from '../theme/ThemeContext';

interface AppBackgroundProps extends ViewProps {
  children: React.ReactNode;
}

export function AppBackground({ children, style, ...rest }: AppBackgroundProps) {
  const { theme } = useAppTheme();

  return (
    <View style={[styles.container, style]} {...rest}>
      {/* 1. Fondo Sólido */}
      {theme.backgroundType === 'solid' && (
        <View
          style={[
            StyleSheet.absoluteFill,
            { backgroundColor: theme.solidColor },
          ]}
        />
      )}

      {/* 2. Fondo Degradado Suave con SVG */}
      {theme.backgroundType === 'gradient' && (
        <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
          <Defs>
            <LinearGradient id="appGradientBg" x1="0%" y1="0%" x2="0%" y2="100%">
              <Stop offset="0%" stopColor={theme.gradientColors[0]} stopOpacity="1" />
              <Stop offset="100%" stopColor={theme.gradientColors[1]} stopOpacity="1" />
            </LinearGradient>
          </Defs>
          <Rect x="0" y="0" width="100%" height="100%" fill="url(#appGradientBg)" />
        </Svg>
      )}

      {/* 3. Fondo Multimedia (Foto / GIF / Video) */}
      {theme.backgroundType === 'media' && theme.mediaUri && (
        <View style={StyleSheet.absoluteFill}>
          <Image
            source={{ uri: theme.mediaUri }}
            style={StyleSheet.absoluteFill}
            resizeMode="cover"
          />
          {/* Capa de velo/opacidad para mantener los textos legibles estilo reproductor */}
          <View
            style={[
              StyleSheet.absoluteFill,
              {
                backgroundColor: theme.isDark ? '#000000' : '#EFE8DE',
                opacity: theme.mediaOverlayOpacity,
              },
            ]}
          />
        </View>
      )}

      {/* Capa de contenido de la pantalla */}
      <View style={styles.contentLayer}>{children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    position: 'relative',
  },
  contentLayer: {
    flex: 1,
  },
});
