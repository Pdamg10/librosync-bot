import React from 'react';
import { View, StyleSheet, Image, ViewProps } from 'react-native';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useAppTheme } from '../theme/ThemeContext';

interface AppBackgroundProps extends ViewProps {
  children: React.ReactNode;
}

function VideoBackground({ uri }: { uri: string }) {
  try {
    const player = useVideoPlayer(uri, (p) => {
      p.loop = true;
      p.muted = true;
      p.play();
    });
    return (
      <VideoView
        style={StyleSheet.absoluteFill}
        player={player}
        allowsPictureInPicture={false}
        contentFit="cover"
        nativeControls={false}
      />
    );
  } catch {
    return null;
  }
}

export function AppBackground({ children, style, ...rest }: AppBackgroundProps) {
  const { theme } = useAppTheme();
  const isDark = theme.isDark;

  const gradientStops = theme.gradientColors && theme.gradientColors.length >= 2
    ? theme.gradientColors
    : ['#FAF7F2', '#EFE8DE'];

  const numStops = gradientStops.length;

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

      {/* 2. Fondo Degradado Suave Dinámico con N colores en SVG */}
      {theme.backgroundType === 'gradient' && (
        <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
          <Defs>
            <LinearGradient id="appMultiGradientBg" x1="0%" y1="0%" x2="0%" y2="100%">
              {gradientStops.map((col, idx) => {
                const pct = Math.round((idx / Math.max(1, numStops - 1)) * 100);
                return (
                  <Stop
                    key={`${idx}-${col}`}
                    offset={`${pct}%`}
                    stopColor={col}
                    stopOpacity="1"
                  />
                );
              })}
            </LinearGradient>
          </Defs>
          <Rect x="0" y="0" width="100%" height="100%" fill="url(#appMultiGradientBg)" />
        </Svg>
      )}

      {/* 3. Fondo Imagen o GIF */}
      {(theme.backgroundType === 'image' || theme.backgroundType === 'gif') && theme.mediaUri && (
        <View style={StyleSheet.absoluteFill}>
          <Image
            source={{ uri: theme.mediaUri }}
            style={StyleSheet.absoluteFill}
            resizeMode="cover"
          />
          {/* Capa de velo protector de contraste */}
          <View
            style={[
              StyleSheet.absoluteFill,
              {
                backgroundColor: isDark ? '#000000' : '#FAF7F2',
                opacity: theme.mediaOverlayOpacity,
              },
            ]}
          />
        </View>
      )}

      {/* 4. Fondo Video */}
      {theme.backgroundType === 'video' && theme.mediaUri && (
        <View style={StyleSheet.absoluteFill}>
          <VideoBackground uri={theme.mediaUri} />
          {/* Capa de velo protector de contraste */}
          <View
            style={[
              StyleSheet.absoluteFill,
              {
                backgroundColor: isDark ? '#000000' : '#FAF7F2',
                opacity: theme.mediaOverlayOpacity,
              },
            ]}
          />
        </View>
      )}

      {/* Capa de contenido de la aplicación */}
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

