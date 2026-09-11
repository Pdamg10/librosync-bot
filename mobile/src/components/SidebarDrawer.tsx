import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Modal,
  Animated,
  ScrollView,
  Dimensions,
  TouchableWithoutFeedback,
} from 'react-native';
import { Book, ShelfSummary, ReadingState } from '../types';
import { useAppTheme } from '../theme/ThemeContext';

interface SidebarDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  activeScreen: string;
  onNavigate: (screen: string, subParam?: string) => void;
  shelves: ShelfSummary | null;
  totalBooksCount?: number;
  onOpenBook?: (book: Book) => void;
  groupTitle?: string;
  userName?: string;
}

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const DRAWER_WIDTH = Math.min(SCREEN_WIDTH * 0.82, 340);

export function SidebarDrawer({
  isOpen,
  onClose,
  activeScreen,
  onNavigate,
  shelves,
  totalBooksCount = 0,
  onOpenBook,
  groupTitle = '💋😜Club de lectura📖❤️',
  userName = 'Lector LibroSync',
}: SidebarDrawerProps) {
  const { theme } = useAppTheme();
  const c = theme.colors;

  const slideAnim = useRef(new Animated.Value(-DRAWER_WIDTH)).current;
  const fadeAnim = useRef(new Animated.Value(0)).current;

  // Secciones expandibles de estantes
  const [expandedShelf, setExpandedShelf] = useState<'reading' | 'finished' | 'to_read' | null>('reading');

  useEffect(() => {
    if (isOpen) {
      Animated.parallel([
        Animated.timing(slideAnim, {
          toValue: 0,
          duration: 250,
          useNativeDriver: true,
        }),
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 250,
          useNativeDriver: true,
        }),
      ]).start();
    } else {
      Animated.parallel([
        Animated.timing(slideAnim, {
          toValue: -DRAWER_WIDTH,
          duration: 200,
          useNativeDriver: true,
        }),
        Animated.timing(fadeAnim, {
          toValue: 0,
          duration: 200,
          useNativeDriver: true,
        }),
      ]).start();
    }
  }, [isOpen]);

  const readingBooks = shelves?.reading || [];
  const finishedBooks = shelves?.finished || [];
  const toReadBooks = shelves?.to_read || [];
  const favoriteCount = shelves?.favorites?.length || 0;

  const toggleShelf = (shelf: 'reading' | 'finished' | 'to_read') => {
    setExpandedShelf(expandedShelf === shelf ? null : shelf);
  };

  const handleNavigate = (screen: string, subParam?: string) => {
    onClose();
    setTimeout(() => {
      onNavigate(screen, subParam);
    }, 150);
  };

  const handleBookPress = (item: ReadingState) => {
    if (item.book && onOpenBook) {
      onClose();
      setTimeout(() => {
        onOpenBook(item.book!);
      }, 150);
    }
  };

  if (!isOpen) return null;

  return (
    <Modal
      transparent
      visible={isOpen}
      animationType="none"
      onRequestClose={onClose}
    >
      <View style={styles.overlay}>
        {/* Backdrop táctil para cerrar */}
        <TouchableWithoutFeedback onPress={onClose}>
          <Animated.View style={[styles.backdrop, { opacity: fadeAnim }]} />
        </TouchableWithoutFeedback>

        {/* Contenedor del Drawer deslizante */}
        <Animated.View
          style={[
            styles.drawerContainer,
            {
              backgroundColor: c.cardBg,
              borderRightColor: c.cardBorder,
              transform: [{ translateX: slideAnim }],
            },
          ]}
        >
          <ScrollView
            style={styles.drawerScroll}
            showsVerticalScrollIndicator={false}
            contentContainerStyle={styles.drawerContent}
          >
            {/* Header: Perfil del Usuario y Comunidad */}
            <View style={styles.profileHeader}>
              <View style={styles.avatarRow}>
                <View style={[styles.avatarContainer, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
                  <Text style={styles.avatarEmoji}>👩‍🌾</Text>
                </View>
                <View style={styles.profileInfo}>
                  <Text style={[styles.userName, { color: c.textPrimary }]} numberOfLines={1}>{userName}</Text>
                  <Text style={[styles.groupBadge, { color: c.textSecondary }]} numberOfLines={1}>
                    {groupTitle}
                  </Text>
                </View>
                <TouchableOpacity
                  onPress={onClose}
                  style={[styles.closeBtn, { backgroundColor: c.cardSecondaryBg }]}
                  hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                >
                  <Text style={[styles.closeBtnText, { color: c.textSecondary }]}>✕</Text>
                </TouchableOpacity>
              </View>
            </View>

            <View style={[styles.divider, { backgroundColor: c.cardBorder }]} />

            {/* SECCIÓN 1: VISTA DE BIBLIOTECA Y ESTANTES */}
            <Text style={[styles.sectionLabel, { color: c.textMuted }]}>BIBLIOTECA & PROGRESO</Text>

            {/* Catálogo General */}
            <TouchableOpacity
              style={[
                styles.navItem,
                activeScreen === 'library' && styles.navItemActive,
              ]}
              onPress={() => handleNavigate('library', 'catalog')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>📚</Text>
                <Text style={styles.navLabel}>Catálogo General</Text>
              </View>
              <View style={styles.badgePill}>
                <Text style={styles.badgePillText}>{totalBooksCount}</Text>
              </View>
            </TouchableOpacity>

            {/* Libros en curso (con barra y % en tiempo real) */}
            <View style={styles.shelfBlock}>
              <TouchableOpacity
                style={[
                  styles.navItem,
                  styles.shelfHeaderItem,
                  expandedShelf === 'reading' && styles.navItemActive,
                ]}
                onPress={() => toggleShelf('reading')}
              >
                <View style={styles.navItemLeft}>
                  <Text style={styles.navIcon}>📖</Text>
                  <Text style={styles.navLabel}>Libros en curso</Text>
                </View>
                <View style={styles.shelfHeaderRight}>
                  <View style={[styles.badgePill, styles.badgePillReading]}>
                    <Text style={styles.badgePillReadingText}>{readingBooks.length}</Text>
                  </View>
                  <Text style={styles.chevronIcon}>
                    {expandedShelf === 'reading' ? '▲' : '▼'}
                  </Text>
                </View>
              </TouchableOpacity>

              {expandedShelf === 'reading' && (
                <View style={styles.shelfBooksList}>
                  {readingBooks.length === 0 ? (
                    <Text style={styles.emptyShelfText}>No tienes libros en lectura ahora.</Text>
                  ) : (
                    readingBooks.map((item) => (
                      <TouchableOpacity
                        key={item.id}
                        style={styles.drawerBookCard}
                        onPress={() => handleBookPress(item)}
                      >
                        <View style={styles.drawerBookTopRow}>
                          <Text style={styles.drawerBookTitle} numberOfLines={1}>
                            {item.book?.title || 'Libro en lectura'}
                          </Text>
                          <Text style={styles.drawerBookPercent}>
                            {Math.round(item.progress_percent)}%
                          </Text>
                        </View>
                        <Text style={styles.drawerBookAuthor} numberOfLines={1}>
                          {item.book?.author || 'Autor desconocido'}
                        </Text>
                        <View style={styles.progressBarBg}>
                          <View
                            style={[
                              styles.progressBarFill,
                              { width: `${Math.min(Math.max(item.progress_percent, 5), 100)}%` },
                            ]}
                          />
                        </View>
                      </TouchableOpacity>
                    ))
                  )}
                  <TouchableOpacity
                    style={styles.viewMoreLink}
                    onPress={() => handleNavigate('library', 'shelves:reading')}
                  >
                    <Text style={styles.viewMoreLinkText}>Ver en estantería completa →</Text>
                  </TouchableOpacity>
                </View>
              )}
            </View>

            {/* Libros terminados */}
            <View style={styles.shelfBlock}>
              <TouchableOpacity
                style={[
                  styles.navItem,
                  styles.shelfHeaderItem,
                  expandedShelf === 'finished' && styles.navItemActive,
                ]}
                onPress={() => toggleShelf('finished')}
              >
                <View style={styles.navItemLeft}>
                  <Text style={styles.navIcon}>🏆</Text>
                  <Text style={styles.navLabel}>Libros terminados</Text>
                </View>
                <View style={styles.shelfHeaderRight}>
                  <View style={[styles.badgePill, styles.badgePillFinished]}>
                    <Text style={styles.badgePillFinishedText}>{finishedBooks.length}</Text>
                  </View>
                  <Text style={styles.chevronIcon}>
                    {expandedShelf === 'finished' ? '▲' : '▼'}
                  </Text>
                </View>
              </TouchableOpacity>

              {expandedShelf === 'finished' && (
                <View style={styles.shelfBooksList}>
                  {finishedBooks.length === 0 ? (
                    <Text style={styles.emptyShelfText}>Aún no has completado libros.</Text>
                  ) : (
                    finishedBooks.map((item) => (
                      <TouchableOpacity
                        key={item.id}
                        style={styles.drawerBookCard}
                        onPress={() => handleBookPress(item)}
                      >
                        <View style={styles.drawerBookTopRow}>
                          <Text style={styles.drawerBookTitle} numberOfLines={1}>
                            {item.book?.title || 'Libro leído'}
                          </Text>
                          <Text style={styles.badgeCompletedLabel}>100%</Text>
                        </View>
                        <Text style={styles.drawerBookAuthor} numberOfLines={1}>
                          {item.book?.author || 'Autor'}
                        </Text>
                      </TouchableOpacity>
                    ))
                  )}
                  <TouchableOpacity
                    style={styles.viewMoreLink}
                    onPress={() => handleNavigate('library', 'shelves:finished')}
                  >
                    <Text style={styles.viewMoreLinkText}>Ver historial de lecturas →</Text>
                  </TouchableOpacity>
                </View>
              )}
            </View>

            {/* Libros pendientes a leer */}
            <View style={styles.shelfBlock}>
              <TouchableOpacity
                style={[
                  styles.navItem,
                  styles.shelfHeaderItem,
                  expandedShelf === 'to_read' && styles.navItemActive,
                ]}
                onPress={() => toggleShelf('to_read')}
              >
                <View style={styles.navItemLeft}>
                  <Text style={styles.navIcon}>📌</Text>
                  <Text style={styles.navLabel}>Pendientes por leer</Text>
                </View>
                <View style={styles.shelfHeaderRight}>
                  <View style={styles.badgePill}>
                    <Text style={styles.badgePillText}>{toReadBooks.length}</Text>
                  </View>
                  <Text style={styles.chevronIcon}>
                    {expandedShelf === 'to_read' ? '▲' : '▼'}
                  </Text>
                </View>
              </TouchableOpacity>

              {expandedShelf === 'to_read' && (
                <View style={styles.shelfBooksList}>
                  {toReadBooks.length === 0 ? (
                    <Text style={styles.emptyShelfText}>No hay libros en tu lista de deseos.</Text>
                  ) : (
                    toReadBooks.map((item) => (
                      <TouchableOpacity
                        key={item.id}
                        style={styles.drawerBookCard}
                        onPress={() => handleBookPress(item)}
                      >
                        <View style={styles.drawerBookTopRow}>
                          <Text style={styles.drawerBookTitle} numberOfLines={1}>
                            {item.book?.title || 'Libro pendiente'}
                          </Text>
                          <Text style={styles.badgePendingLabel}>0%</Text>
                        </View>
                        <Text style={styles.drawerBookAuthor} numberOfLines={1}>
                          {item.book?.author || 'Autor'}
                        </Text>
                      </TouchableOpacity>
                    ))
                  )}
                  <TouchableOpacity
                    style={styles.viewMoreLink}
                    onPress={() => handleNavigate('library', 'shelves:to_read')}
                  >
                    <Text style={styles.viewMoreLinkText}>Ver lista de espera →</Text>
                  </TouchableOpacity>
                </View>
              )}
            </View>

            {/* Favoritos */}
            <TouchableOpacity
              style={styles.navItem}
              onPress={() => handleNavigate('library', 'shelves:favorites')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>⭐</Text>
                <Text style={styles.navLabel}>Favoritos</Text>
              </View>
              <View style={styles.badgePill}>
                <Text style={styles.badgePillText}>{favoriteCount}</Text>
              </View>
            </TouchableOpacity>

            {/* Lectura en conjunto (Club) - Ventana Dedicada */}
            <TouchableOpacity
              style={[styles.navItem, activeScreen === 'buddy' && styles.navItemActive]}
              onPress={() => handleNavigate('buddy')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>👥</Text>
                <Text style={styles.navLabel}>Lectura Conjunta</Text>
              </View>
              <View style={[styles.badgePill, styles.badgePillClub]}>
                <Text style={styles.badgePillClubText}>En vivo</Text>
              </View>
            </TouchableOpacity>

            <View style={styles.divider} />

            {/* SECCIÓN 2: HERRAMIENTAS, CHAT & PERSONALIZACIÓN */}
            <Text style={styles.sectionLabel}>FUNCIONES & ASISTENTE</Text>

            {/* Chat con Griffin (Asistente IA) */}
            <TouchableOpacity
              style={[
                styles.navItem,
                styles.chatHighlightItem,
                activeScreen === 'chat' && styles.navItemActive,
              ]}
              onPress={() => handleNavigate('chat')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>💬</Text>
                <View>
                  <Text style={styles.navLabel}>Chat con Griffin</Text>
                  <Text style={styles.navSublabel}>Bibliotecario IA en vivo</Text>
                </View>
              </View>
              <View style={styles.assistantBadge}>
                <Text style={styles.assistantBadgeText}>AI</Text>
              </View>
            </TouchableOpacity>

            {/* Personalización (Fondo sólido, degradado, foto/video/gif) */}
            <TouchableOpacity
              style={[
                styles.navItem,
                activeScreen === 'customize' && styles.navItemActive,
              ]}
              onPress={() => handleNavigate('customize')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>🎨</Text>
                <View>
                  <Text style={styles.navLabel}>Personalización</Text>
                  <Text style={styles.navSublabel}>Fondos, temas y multimedia</Text>
                </View>
              </View>
              <Text style={styles.chevronIcon}>›</Text>
            </TouchableOpacity>

            {/* Sincronización Telegram */}
            <TouchableOpacity
              style={[
                styles.navItem,
                activeScreen === 'telegram' && styles.navItemActive,
              ]}
              onPress={() => handleNavigate('telegram')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>📱</Text>
                <Text style={styles.navLabel}>Grupos Telegram</Text>
              </View>
              <Text style={styles.chevronIcon}>›</Text>
            </TouchableOpacity>

            {/* Ajustes Generales */}
            <TouchableOpacity
              style={[
                styles.navItem,
                activeScreen === 'settings' && styles.navItemActive,
              ]}
              onPress={() => handleNavigate('settings')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>⚙️</Text>
                <Text style={styles.navLabel}>Ajustes de Lectura</Text>
              </View>
              <Text style={styles.chevronIcon}>›</Text>
            </TouchableOpacity>

            {/* SECCIÓN 3: BOTÓN SUSCRIPCIÓN / CLUB VIP (Inspirado en la imagen de referencia) */}
            <View style={styles.subscribeCard}>
              <View style={styles.subscribeHeader}>
                <View style={styles.subscribeBellCircle}>
                  <Text style={styles.subscribeBellIcon}>🔔</Text>
                </View>
                <View style={styles.subscribeTitles}>
                  <Text style={styles.subscribeTitle}>Membresía Club</Text>
                  <Text style={styles.subscribeSubtitle}>Acceso exclusivo a novedades</Text>
                </View>
              </View>
              <TouchableOpacity
                style={styles.subscribeBtn}
                onPress={() => alert('¡Próximamente disponible! Mantente atento a las novedades del club.')}
              >
                <Text style={styles.subscribeBtnText}>Suscripción</Text>
              </TouchableOpacity>
            </View>

            {/* Pie del Drawer */}
            <View style={styles.drawerFooter}>
              <Text style={styles.footerBrand}>LibroSync • Anaquel v1.0</Text>
              <Text style={styles.footerNote}>Clasificación asistida por IA</Text>
            </View>
          </ScrollView>
        </Animated.View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    flexDirection: 'row',
  },
  backdrop: {
    ...StyleSheet.absoluteFill,
    backgroundColor: 'rgba(44, 34, 30, 0.45)',
  },
  drawerContainer: {
    width: DRAWER_WIDTH,
    height: '100%',
    backgroundColor: '#FAF7F2',
    borderRightWidth: 1,
    borderRightColor: '#DFD5C6',
    shadowColor: '#2C221E',
    shadowOffset: { width: 4, height: 0 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 16,
  },
  drawerScroll: {
    flex: 1,
  },
  drawerContent: {
    paddingHorizontal: 18,
    paddingTop: 48,
    paddingBottom: 36,
  },
  profileHeader: {
    marginBottom: 16,
  },
  avatarRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  avatarContainer: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: '#EDE5D8',
    borderWidth: 2,
    borderColor: '#DFD5C6',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  avatarEmoji: {
    fontSize: 28,
  },
  profileInfo: {
    flex: 1,
  },
  userName: {
    fontSize: 16,
    fontWeight: '700',
    color: '#2C221E',
    marginBottom: 2,
  },
  groupBadge: {
    fontSize: 12,
    color: '#7A6E65',
    fontWeight: '500',
  },
  closeBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#EDE5D8',
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 8,
  },
  closeBtnText: {
    fontSize: 14,
    fontWeight: '700',
    color: '#7A6E65',
  },
  divider: {
    height: 1,
    backgroundColor: '#E5DDD0',
    marginVertical: 14,
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.8,
    color: '#9C8E82',
    marginBottom: 8,
    marginTop: 4,
    textTransform: 'uppercase',
  },
  navItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 12,
    marginBottom: 4,
    backgroundColor: 'transparent',
  },
  navItemActive: {
    backgroundColor: '#EDE5D8',
  },
  navItemLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    flex: 1,
  },
  navIcon: {
    fontSize: 18,
    width: 24,
    textAlign: 'center',
  },
  navLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#2C221E',
  },
  navSublabel: {
    fontSize: 11,
    color: '#7A6E65',
    marginTop: 1,
  },
  badgePill: {
    backgroundColor: '#EDE5D8',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#DFD5C6',
  },
  badgePillText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#7A6E65',
  },
  badgePillReading: {
    backgroundColor: '#FEF3C7',
    borderColor: '#FDE68A',
  },
  badgePillReadingText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#B45309',
  },
  badgePillFinished: {
    backgroundColor: '#D1FAE5',
    borderColor: '#A7F3D0',
  },
  badgePillFinishedText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#047857',
  },
  badgePillClub: {
    backgroundColor: '#FEE2E2',
    borderColor: '#FECACA',
  },
  badgePillClubText: {
    fontSize: 10,
    fontWeight: '700',
    color: '#DC2626',
  },
  chevronIcon: {
    fontSize: 12,
    color: '#9C8E82',
    fontWeight: '700',
  },
  shelfBlock: {
    marginBottom: 4,
  },
  shelfHeaderItem: {
    marginBottom: 2,
  },
  shelfHeaderRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  shelfBooksList: {
    backgroundColor: '#F4ECE1',
    borderRadius: 12,
    padding: 10,
    marginBottom: 6,
    borderWidth: 1,
    borderColor: '#E5DDD0',
  },
  emptyShelfText: {
    fontSize: 12,
    color: '#7A6E65',
    fontStyle: 'italic',
    paddingVertical: 6,
    paddingHorizontal: 4,
  },
  drawerBookCard: {
    backgroundColor: '#FBF8F3',
    borderRadius: 8,
    padding: 8,
    marginBottom: 6,
    borderWidth: 1,
    borderColor: '#DFD5C6',
  },
  drawerBookTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 2,
  },
  drawerBookTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: '#2C221E',
    flex: 1,
    marginRight: 6,
  },
  drawerBookPercent: {
    fontSize: 11,
    fontWeight: '700',
    color: '#D97706',
  },
  drawerBookAuthor: {
    fontSize: 11,
    color: '#7A6E65',
    marginBottom: 5,
  },
  progressBarBg: {
    height: 4,
    backgroundColor: '#E5DDD0',
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: '#D97706',
    borderRadius: 2,
  },
  badgeCompletedLabel: {
    fontSize: 10,
    fontWeight: '700',
    color: '#059669',
    backgroundColor: '#D1FAE5',
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 4,
  },
  badgePendingLabel: {
    fontSize: 10,
    fontWeight: '700',
    color: '#7A6E65',
    backgroundColor: '#EDE5D8',
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 4,
  },
  viewMoreLink: {
    paddingVertical: 6,
    alignItems: 'center',
  },
  viewMoreLinkText: {
    fontSize: 11,
    fontWeight: '600',
    color: '#8C5A2B',
  },
  chatHighlightItem: {
    backgroundColor: '#F3EDE2',
    borderWidth: 1,
    borderColor: '#DFD5C6',
  },
  assistantBadge: {
    backgroundColor: '#8E75B2',
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 8,
  },
  assistantBadgeText: {
    fontSize: 10,
    fontWeight: '800',
    color: '#FFFFFF',
  },
  subscribeCard: {
    marginTop: 18,
    backgroundColor: '#3B5B75',
    borderRadius: 16,
    padding: 14,
    shadowColor: '#2C221E',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.12,
    shadowRadius: 6,
    elevation: 4,
  },
  subscribeHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
  },
  subscribeBellCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: 'rgba(255, 255, 255, 0.18)',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 10,
  },
  subscribeBellIcon: {
    fontSize: 18,
  },
  subscribeTitles: {
    flex: 1,
  },
  subscribeTitle: {
    fontSize: 13,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  subscribeSubtitle: {
    fontSize: 11,
    color: 'rgba(255, 255, 255, 0.8)',
    marginTop: 1,
  },
  subscribeBtn: {
    backgroundColor: '#EAA023',
    borderRadius: 10,
    paddingVertical: 8,
    alignItems: 'center',
  },
  subscribeBtnText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#2C221E',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  drawerFooter: {
    marginTop: 24,
    alignItems: 'center',
    paddingBottom: 10,
  },
  footerBrand: {
    fontSize: 11,
    fontWeight: '600',
    color: '#9C8E82',
  },
  footerNote: {
    fontSize: 10,
    color: '#B0A398',
    marginTop: 2,
  },
});
