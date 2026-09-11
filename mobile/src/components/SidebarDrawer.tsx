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
const DRAWER_WIDTH = Math.min(SCREEN_WIDTH * 0.85, 340);

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

        {/* Contenedor del Drawer deslizante adaptado a temas */}
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
                  <Text style={[styles.userName, { color: c.textPrimary }]} numberOfLines={1}>
                    {userName}
                  </Text>
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
                activeScreen === 'library' && [styles.navItemActive, { backgroundColor: c.cardSecondaryBg }],
              ]}
              onPress={() => handleNavigate('library', 'catalog')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>📚</Text>
                <Text style={[styles.navLabel, { color: c.textPrimary }]}>Catálogo General</Text>
              </View>
              <View style={[styles.badgePill, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
                <Text style={[styles.badgePillText, { color: c.textSecondary }]}>{totalBooksCount}</Text>
              </View>
            </TouchableOpacity>

            {/* Libros en curso (con barra y % en tiempo real) */}
            <View style={styles.shelfBlock}>
              <TouchableOpacity
                style={[
                  styles.navItem,
                  styles.shelfHeaderItem,
                  expandedShelf === 'reading' && [styles.navItemActive, { backgroundColor: c.cardSecondaryBg }],
                ]}
                onPress={() => toggleShelf('reading')}
              >
                <View style={styles.navItemLeft}>
                  <Text style={styles.navIcon}>📖</Text>
                  <Text style={[styles.navLabel, { color: c.textPrimary }]}>Libros en curso</Text>
                </View>
                <View style={styles.shelfHeaderRight}>
                  <View style={[styles.badgePill, styles.badgePillReading]}>
                    <Text style={styles.badgePillReadingText}>{readingBooks.length}</Text>
                  </View>
                  <Text style={[styles.chevronIcon, { color: c.textMuted }]}>
                    {expandedShelf === 'reading' ? '▲' : '▼'}
                  </Text>
                </View>
              </TouchableOpacity>

              {expandedShelf === 'reading' && (
                <View style={[styles.shelfBooksList, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
                  {readingBooks.length === 0 ? (
                    <Text style={[styles.emptyShelfText, { color: c.textSecondary }]}>
                      No tienes libros en lectura ahora.
                    </Text>
                  ) : (
                    readingBooks.map((item) => (
                      <TouchableOpacity
                        key={item.id}
                        style={[styles.drawerBookCard, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
                        onPress={() => handleBookPress(item)}
                      >
                        <View style={styles.drawerBookTopRow}>
                          <Text style={[styles.drawerBookTitle, { color: c.textPrimary }]} numberOfLines={1}>
                            {item.book?.title || 'Libro en lectura'}
                          </Text>
                          <Text style={[styles.drawerBookPercent, { color: c.accent }]}>
                            {Math.round(item.progress_percent)}%
                          </Text>
                        </View>
                        <Text style={[styles.drawerBookAuthor, { color: c.textSecondary }]} numberOfLines={1}>
                          {item.book?.author || 'Autor desconocido'}
                        </Text>
                        <View style={[styles.progressBarBg, { backgroundColor: c.cardSecondaryBg }]}>
                          <View
                            style={[
                              styles.progressBarFill,
                              {
                                backgroundColor: c.accent,
                                width: `${Math.min(Math.max(item.progress_percent, 5), 100)}%`,
                              },
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
                    <Text style={[styles.viewMoreLinkText, { color: c.accent }]}>
                      Ver en estantería completa →
                    </Text>
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
                  expandedShelf === 'finished' && [styles.navItemActive, { backgroundColor: c.cardSecondaryBg }],
                ]}
                onPress={() => toggleShelf('finished')}
              >
                <View style={styles.navItemLeft}>
                  <Text style={styles.navIcon}>🏆</Text>
                  <Text style={[styles.navLabel, { color: c.textPrimary }]}>Libros terminados</Text>
                </View>
                <View style={styles.shelfHeaderRight}>
                  <View style={[styles.badgePill, styles.badgePillFinished]}>
                    <Text style={styles.badgePillFinishedText}>{finishedBooks.length}</Text>
                  </View>
                  <Text style={[styles.chevronIcon, { color: c.textMuted }]}>
                    {expandedShelf === 'finished' ? '▲' : '▼'}
                  </Text>
                </View>
              </TouchableOpacity>

              {expandedShelf === 'finished' && (
                <View style={[styles.shelfBooksList, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
                  {finishedBooks.length === 0 ? (
                    <Text style={[styles.emptyShelfText, { color: c.textSecondary }]}>
                      Aún no has completado libros.
                    </Text>
                  ) : (
                    finishedBooks.map((item) => (
                      <TouchableOpacity
                        key={item.id}
                        style={[styles.drawerBookCard, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
                        onPress={() => handleBookPress(item)}
                      >
                        <View style={styles.drawerBookTopRow}>
                          <Text style={[styles.drawerBookTitle, { color: c.textPrimary }]} numberOfLines={1}>
                            {item.book?.title || 'Libro leído'}
                          </Text>
                          <Text style={styles.badgeCompletedLabel}>100%</Text>
                        </View>
                        <Text style={[styles.drawerBookAuthor, { color: c.textSecondary }]} numberOfLines={1}>
                          {item.book?.author || 'Autor'}
                        </Text>
                      </TouchableOpacity>
                    ))
                  )}
                  <TouchableOpacity
                    style={styles.viewMoreLink}
                    onPress={() => handleNavigate('library', 'shelves:finished')}
                  >
                    <Text style={[styles.viewMoreLinkText, { color: c.accent }]}>
                      Ver historial de lecturas →
                    </Text>
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
                  expandedShelf === 'to_read' && [styles.navItemActive, { backgroundColor: c.cardSecondaryBg }],
                ]}
                onPress={() => toggleShelf('to_read')}
              >
                <View style={styles.navItemLeft}>
                  <Text style={styles.navIcon}>📌</Text>
                  <Text style={[styles.navLabel, { color: c.textPrimary }]}>Pendientes por leer</Text>
                </View>
                <View style={styles.shelfHeaderRight}>
                  <View style={[styles.badgePill, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
                    <Text style={[styles.badgePillText, { color: c.textSecondary }]}>{toReadBooks.length}</Text>
                  </View>
                  <Text style={[styles.chevronIcon, { color: c.textMuted }]}>
                    {expandedShelf === 'to_read' ? '▲' : '▼'}
                  </Text>
                </View>
              </TouchableOpacity>

              {expandedShelf === 'to_read' && (
                <View style={[styles.shelfBooksList, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
                  {toReadBooks.length === 0 ? (
                    <Text style={[styles.emptyShelfText, { color: c.textSecondary }]}>
                      No hay libros en tu lista de deseos.
                    </Text>
                  ) : (
                    toReadBooks.map((item) => (
                      <TouchableOpacity
                        key={item.id}
                        style={[styles.drawerBookCard, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
                        onPress={() => handleBookPress(item)}
                      >
                        <View style={styles.drawerBookTopRow}>
                          <Text style={[styles.drawerBookTitle, { color: c.textPrimary }]} numberOfLines={1}>
                            {item.book?.title || 'Libro pendiente'}
                          </Text>
                          <Text style={styles.badgePendingLabel}>0%</Text>
                        </View>
                        <Text style={[styles.drawerBookAuthor, { color: c.textSecondary }]} numberOfLines={1}>
                          {item.book?.author || 'Autor'}
                        </Text>
                      </TouchableOpacity>
                    ))
                  )}
                  <TouchableOpacity
                    style={styles.viewMoreLink}
                    onPress={() => handleNavigate('library', 'shelves:to_read')}
                  >
                    <Text style={[styles.viewMoreLinkText, { color: c.accent }]}>
                      Ver lista de espera →
                    </Text>
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
                <Text style={[styles.navLabel, { color: c.textPrimary }]}>Favoritos</Text>
              </View>
              <View style={[styles.badgePill, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
                <Text style={[styles.badgePillText, { color: c.textSecondary }]}>{favoriteCount}</Text>
              </View>
            </TouchableOpacity>

            {/* Lectura en conjunto (Club) - Ventana Dedicada */}
            <TouchableOpacity
              style={[styles.navItem, activeScreen === 'buddy' && [styles.navItemActive, { backgroundColor: c.cardSecondaryBg }]]}
              onPress={() => handleNavigate('buddy')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>👥</Text>
                <Text style={[styles.navLabel, { color: c.textPrimary }]}>Lectura Conjunta</Text>
              </View>
              <View style={[styles.badgePill, styles.badgePillClub]}>
                <Text style={styles.badgePillClubText}>En vivo</Text>
              </View>
            </TouchableOpacity>

            <View style={[styles.divider, { backgroundColor: c.cardBorder }]} />

            {/* SECCIÓN 2: HERRAMIENTAS, CHAT & PERSONALIZACIÓN */}
            <Text style={[styles.sectionLabel, { color: c.textMuted }]}>FUNCIONES & ASISTENTE</Text>

            {/* Chat con Griffin (Asistente IA con Gemini y base de datos) */}
            <TouchableOpacity
              style={[
                styles.navItem,
                styles.chatHighlightItem,
                { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder },
                activeScreen === 'chat' && [styles.navItemActive, { borderColor: c.accent }],
              ]}
              onPress={() => handleNavigate('chat')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>🦉</Text>
                <View>
                  <Text style={[styles.navLabel, { color: c.textPrimary }]}>Griffin IA</Text>
                  <Text style={[styles.navSublabel, { color: c.textSecondary }]}>Bibliotecario Inteligente</Text>
                </View>
              </View>
              <View style={[styles.assistantBadge, { backgroundColor: c.accent }]}>
                <Text style={styles.assistantBadgeText}>AI</Text>
              </View>
            </TouchableOpacity>

            {/* Personalización (Fondo sólido, degradado, imagen, gif, video) */}
            <TouchableOpacity
              style={[
                styles.navItem,
                activeScreen === 'customize' && [styles.navItemActive, { backgroundColor: c.cardSecondaryBg }],
              ]}
              onPress={() => handleNavigate('customize')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>🎨</Text>
                <View>
                  <Text style={[styles.navLabel, { color: c.textPrimary }]}>Personalización</Text>
                  <Text style={[styles.navSublabel, { color: c.textSecondary }]}>Fondos, temas y multimedia</Text>
                </View>
              </View>
              <Text style={[styles.chevronIcon, { color: c.textMuted }]}>›</Text>
            </TouchableOpacity>

            {/* Sincronización Telegram */}
            <TouchableOpacity
              style={[
                styles.navItem,
                activeScreen === 'telegram' && [styles.navItemActive, { backgroundColor: c.cardSecondaryBg }],
              ]}
              onPress={() => handleNavigate('telegram')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>📱</Text>
                <Text style={[styles.navLabel, { color: c.textPrimary }]}>Grupos Telegram</Text>
              </View>
              <Text style={[styles.chevronIcon, { color: c.textMuted }]}>›</Text>
            </TouchableOpacity>

            {/* Ajustes Generales */}
            <TouchableOpacity
              style={[
                styles.navItem,
                activeScreen === 'settings' && [styles.navItemActive, { backgroundColor: c.cardSecondaryBg }],
              ]}
              onPress={() => handleNavigate('settings')}
            >
              <View style={styles.navItemLeft}>
                <Text style={styles.navIcon}>⚙️</Text>
                <Text style={[styles.navLabel, { color: c.textPrimary }]}>Ajustes y Conexión</Text>
              </View>
              <Text style={[styles.chevronIcon, { color: c.textMuted }]}>›</Text>
            </TouchableOpacity>

            {/* SECCIÓN 3: CLUB VIP */}
            <View style={[styles.subscribeCard, { backgroundColor: '#3B5B75' }]}>
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
              <Text style={[styles.footerBrand, { color: c.textSecondary }]}>LibroSync • Anaquel v1.0</Text>
              <Text style={[styles.footerNote, { color: c.textMuted }]}>Impulsado por Gemini IA y Telegram</Text>
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
    backgroundColor: 'rgba(20, 15, 12, 0.55)',
  },
  drawerContainer: {
    width: DRAWER_WIDTH,
    height: '100%',
    borderRightWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 4, height: 0 },
    shadowOpacity: 0.2,
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
    width: 50,
    height: 50,
    borderRadius: 25,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  avatarEmoji: {
    fontSize: 26,
  },
  profileInfo: {
    flex: 1,
  },
  userName: {
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 2,
  },
  groupBadge: {
    fontSize: 12,
    fontWeight: '500',
  },
  closeBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 8,
  },
  closeBtnText: {
    fontSize: 14,
    fontWeight: '700',
  },
  divider: {
    height: 1,
    marginVertical: 14,
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.8,
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
    borderRadius: 12,
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
  },
  navSublabel: {
    fontSize: 11,
    marginTop: 1,
  },
  badgePill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
    borderWidth: 1,
  },
  badgePillText: {
    fontSize: 11,
    fontWeight: '700',
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
    borderRadius: 12,
    padding: 10,
    marginBottom: 6,
    borderWidth: 1,
  },
  emptyShelfText: {
    fontSize: 12,
    fontStyle: 'italic',
    paddingVertical: 6,
    paddingHorizontal: 4,
  },
  drawerBookCard: {
    borderRadius: 8,
    padding: 8,
    marginBottom: 6,
    borderWidth: 1,
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
    flex: 1,
    marginRight: 6,
  },
  drawerBookPercent: {
    fontSize: 11,
    fontWeight: '700',
  },
  drawerBookAuthor: {
    fontSize: 11,
    marginBottom: 5,
  },
  progressBarBg: {
    height: 4,
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    borderRadius: 2,
  },
  badgeCompletedLabel: {
    fontSize: 10,
    fontWeight: '700',
    color: '#047857',
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
  },
  chatHighlightItem: {
    borderWidth: 1,
  },
  assistantBadge: {
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
    borderRadius: 16,
    padding: 14,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.15,
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
    fontSize: 14,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  subscribeSubtitle: {
    fontSize: 11,
    color: 'rgba(255, 255, 255, 0.8)',
    marginTop: 1,
  },
  subscribeBtn: {
    backgroundColor: '#FAF7F2',
    paddingVertical: 8,
    borderRadius: 8,
    alignItems: 'center',
  },
  subscribeBtnText: {
    color: '#3B5B75',
    fontSize: 12,
    fontWeight: '700',
  },
  drawerFooter: {
    marginTop: 24,
    alignItems: 'center',
  },
  footerBrand: {
    fontSize: 12,
    fontWeight: '700',
  },
  footerNote: {
    fontSize: 10,
    marginTop: 2,
  },
});
