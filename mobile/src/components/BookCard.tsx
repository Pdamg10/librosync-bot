import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Image,
} from 'react-native';
import Svg, { Path } from 'react-native-svg';
import { Book } from '../types';
import { colors, getGenreEmoji, getBookPalette } from '../theme/colors';
import { useAppTheme } from '../theme/ThemeContext';

interface BookCardProps {
  book: Book;
  onPress: () => void;
  onLongPress?: () => void;
  width?: number;
}

export const BookCard: React.FC<BookCardProps> = ({
  book,
  onPress,
  onLongPress,
  width,
}) => {
  const { theme } = useAppTheme();
  const c = theme.colors;
  const emoji = getGenreEmoji(book.genre);
  const palette = getBookPalette(book.genre);
  const progressPercent = Math.min(100, Math.max(0, Math.round(book.reading_progress || 0)));
  const isEpub = (book.file_format || '').toLowerCase() === 'epub';

  return (
    <TouchableOpacity
      activeOpacity={0.85}
      onPress={onPress}
      onLongPress={onLongPress}
      style={[
        styles.outerContainer,
        width ? { width } : styles.defaultWidth,
      ]}
    >
      {/* ================= LIBRO FÍSICO 3D ================= */}
      <View style={[styles.bookPhysicalWrapper, { backgroundColor: palette.bg }]}>
        {/* Lomo / Spine vertical highlight & shadow (Efecto 3D izquierdo) */}
        <View style={styles.spineHighlight} />
        <View style={styles.spineCrease} />

        {/* Portada / Cover Frontal */}
        <View style={styles.coverInner}>
          {book.cover_url ? (
            <Image
              source={{ uri: book.cover_url }}
              style={styles.coverImage}
              resizeMode="cover"
            />
          ) : (
            <View style={[styles.artCover, { backgroundColor: palette.bg }]}>
              {/* Marco decorativo vintage */}
              <View style={[styles.artBorder, { borderColor: palette.accent }]}>
                <Text style={styles.artEmoji}>{emoji}</Text>
                <Text style={[styles.artTitle, { color: palette.text }]} numberOfLines={3}>
                  {book.title.toUpperCase()}
                </Text>
                <View style={[styles.artDivider, { backgroundColor: palette.accent }]} />
                <Text style={[styles.artAuthor, { color: palette.accent }]} numberOfLines={1}>
                  {book.author || 'Autor desconocido'}
                </Text>
              </View>
            </View>
          )}

          {/* Badge de Formato (.EPUB o .PDF) */}
          <View style={[styles.formatBadge, isEpub ? styles.epubBadge : styles.pdfBadge]}>
            <Text style={styles.formatText}>{book.file_format.toUpperCase()}</Text>
          </View>

          {/* Indicador de Progreso en Lectura */}
          {progressPercent > 0 && (
            <View style={styles.progressPill}>
              <Text style={styles.progressPillText}>{progressPercent}%</Text>
            </View>
          )}
        </View>

        {/* Canto de Páginas (Bloque blanco de hojas físicas en el borde inferior) */}
        <View style={styles.pagesBlock}>
          <View style={styles.pageLine} />
          <View style={styles.pageLine} />
        </View>

        {/* Borde inferior de la tapa dura */}
        <View style={[styles.bottomCoverRim, { backgroundColor: palette.spine }]} />

        {/* Listón Marcapáginas Colgante con corte en 'V' */}
        <View style={styles.ribbonContainer} pointerEvents="none">
          <Svg width={14} height={24} viewBox="0 0 14 24">
            <Path
              d="M0 0 L14 0 L14 24 L7 18 L0 24 Z"
              fill={palette.ribbon || '#EAA023'}
            />
          </Svg>
        </View>
      </View>

      {/* ================= REPISA / ESTANTERÍA DE MADERA ================= */}
      <View style={styles.shelfContainer}>
        <View style={[styles.shelfTopSurface, { backgroundColor: c.shelfBar }]} />
        <View style={[styles.shelfFrontBevel, { backgroundColor: c.shelfBarEdge }]} />
        <View style={styles.shelfBottomShadow} />
      </View>

      {/* ================= METADATOS: TÍTULO Y AUTOR CON FONDO PROTEGIDO ================= */}
      <View style={[styles.metaContainer, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
        <Text style={[styles.bookTitle, { color: c.textPrimary }]} numberOfLines={2}>
          {book.title}
        </Text>
        <Text style={[styles.bookAuthor, { color: c.textSecondary }]} numberOfLines={1}>
          {book.author || 'Desconocido'}
        </Text>
      </View>
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  outerContainer: {
    marginBottom: 20,
    alignItems: 'center',
  },
  defaultWidth: {
    flex: 1,
  },

  /* 3D Physical Book */
  bookPhysicalWrapper: {
    width: '100%',
    height: 195,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    borderBottomLeftRadius: 10,
    borderBottomRightRadius: 10,
    overflow: 'visible',
    position: 'relative',
    shadowColor: '#3c2f2f',
    shadowOffset: { width: 3, height: 6 },
    shadowOpacity: 0.18,
    shadowRadius: 8,
    elevation: 6,
  },

  /* Spine 3D Shading */
  spineHighlight: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 9,
    borderTopLeftRadius: 18,
    borderBottomLeftRadius: 10,
    backgroundColor: 'rgba(255, 255, 255, 0.22)',
    zIndex: 10,
  },
  spineCrease: {
    position: 'absolute',
    left: 8,
    top: 0,
    bottom: 0,
    width: 1.5,
    backgroundColor: 'rgba(0, 0, 0, 0.25)',
    zIndex: 10,
  },

  /* Cover Inner Area */
  coverInner: {
    flex: 1,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    overflow: 'hidden',
    position: 'relative',
  },
  coverImage: {
    width: '100%',
    height: '100%',
  },

  /* Fallback Art Cover when no cover_url exists */
  artCover: {
    flex: 1,
    padding: 10,
    justifyContent: 'center',
    alignItems: 'center',
  },
  artBorder: {
    flex: 1,
    width: '100%',
    borderWidth: 1.5,
    borderRadius: 8,
    padding: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  artEmoji: {
    fontSize: 28,
    marginBottom: 8,
  },
  artTitle: {
    fontSize: 12,
    fontWeight: '800',
    textAlign: 'center',
    letterSpacing: 0.8,
    lineHeight: 16,
  },
  artDivider: {
    width: 24,
    height: 1.5,
    marginVertical: 6,
    borderRadius: 1,
  },
  artAuthor: {
    fontSize: 10,
    fontWeight: '600',
    textAlign: 'center',
  },

  /* Format Badge */
  formatBadge: {
    position: 'absolute',
    top: 8,
    right: 8,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 5,
    zIndex: 5,
  },
  epubBadge: {
    backgroundColor: '#7C3AED',
  },
  pdfBadge: {
    backgroundColor: '#DC2626',
  },
  formatText: {
    fontSize: 9,
    fontWeight: '800',
    color: '#FFFFFF',
    letterSpacing: 0.5,
  },

  /* Reading Progress Pill */
  progressPill: {
    position: 'absolute',
    bottom: 6,
    right: 6,
    backgroundColor: 'rgba(44, 34, 30, 0.85)',
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 8,
    zIndex: 5,
  },
  progressPillText: {
    fontSize: 10,
    fontWeight: '700',
    color: '#FBF8F3',
  },

  /* Pages Layer (Canto de hojas físicas) */
  pagesBlock: {
    height: 13,
    backgroundColor: '#FAF7EE',
    borderTopWidth: 0.8,
    borderBottomWidth: 0.8,
    borderColor: '#E2D8C3',
    justifyContent: 'space-evenly',
    paddingHorizontal: 4,
    zIndex: 2,
  },
  pageLine: {
    height: 0.6,
    backgroundColor: '#EAE1CE',
    width: '100%',
  },

  /* Bottom Cover Rim */
  bottomCoverRim: {
    height: 5,
    borderBottomLeftRadius: 10,
    borderBottomRightRadius: 10,
    zIndex: 2,
  },

  /* Ribbon Bookmark */
  ribbonContainer: {
    position: 'absolute',
    bottom: -13,
    left: 20,
    zIndex: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 3,
    elevation: 4,
  },

  /* Bookshelf (Estantería física) */
  shelfContainer: {
    width: '106%',
    marginTop: 6,
    alignItems: 'center',
  },
  shelfTopSurface: {
    width: '100%',
    height: 3.5,
    backgroundColor: '#D8CEBF',
    borderRadius: 1.5,
    borderTopWidth: 0.8,
    borderTopColor: '#EBE2D5',
  },
  shelfFrontBevel: {
    width: '100%',
    height: 4,
    backgroundColor: '#C5B7A4',
    borderBottomLeftRadius: 2,
    borderBottomRightRadius: 2,
  },
  shelfBottomShadow: {
    width: '96%',
    height: 4,
    backgroundColor: 'rgba(60, 48, 40, 0.08)',
    borderBottomLeftRadius: 3,
    borderBottomRightRadius: 3,
  },

  /* Metadata Under Book with high-contrast card backing */
  metaContainer: {
    width: '92%',
    marginTop: 8,
    alignItems: 'center',
    paddingHorizontal: 6,
    paddingVertical: 4,
    borderRadius: 8,
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 2,
    elevation: 1,
  },
  bookTitle: {
    fontSize: 12,
    fontWeight: '700',
    textAlign: 'center',
    lineHeight: 16,
  },
  bookAuthor: {
    fontSize: 10,
    fontWeight: '500',
    textAlign: 'center',
    marginTop: 2,
  },
});
