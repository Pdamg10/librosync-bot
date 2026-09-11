import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  ScrollView,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  TouchableOpacity,
  Alert,
  Image,
  Modal,
} from 'react-native';
import { Book, TelegramLink, ShelfSummary, ReadingState, BuddyRead } from '../types';
import {
  fetchBooks,
  fetchTelegramLinks,
  fetchReadingShelves,
  updateBookReadingState,
  fetchBuddyReads,
  createBuddyRead,
  joinBuddyRead,
  updateBuddyReadProgress,
  getCurrentUserId,
} from '../services/api';
import { useResponsive } from '../hooks/useResponsive';
import { BookCard } from '../components/BookCard';
import { GenreChip } from '../components/GenreChip';
import { SearchBar } from '../components/SearchBar';
import { ReaderModal } from '../components/ReaderModal';
import { UploadModal } from '../components/UploadModal';
import { useAppTheme } from '../theme/ThemeContext';

type MainViewTab = 'catalog' | 'shelves' | 'buddy';
type ShelfTab = 'reading' | 'favorites' | 'to_read' | 'finished';

export interface LibraryScreenProps {
  onOpenDrawer?: () => void;
  onNavigateToChat?: () => void;
  initialTab?: MainViewTab;
  initialShelf?: ShelfTab;
  activeTelegramLinkId?: number | null;
  onShelvesLoaded?: (shelves: ShelfSummary | null, totalBooks: number, books: Book[]) => void;
  onOpenBookDetail?: (book: Book) => void;
}

export const LibraryScreen: React.FC<LibraryScreenProps> = ({
  onOpenDrawer,
  onNavigateToChat,
  initialTab,
  initialShelf,
  activeTelegramLinkId,
  onShelvesLoaded,
  onOpenBookDetail,
}) => {
  const { theme } = useAppTheme();
  const c = theme.colors;
  const { isTablet, numColumns, cardWidth } = useResponsive();

  const [activeTab, setActiveTab] = useState<MainViewTab>(initialTab || 'catalog');
  const [selectedShelf, setSelectedShelf] = useState<ShelfTab>(initialShelf || 'reading');

  useEffect(() => {
    if (initialTab) setActiveTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    if (initialShelf) setSelectedShelf(initialShelf);
  }, [initialShelf]);

  const [books, setBooks] = useState<Book[]>([]);
  const [telegramLinks, setTelegramLinks] = useState<TelegramLink[]>([]);
  const [shelves, setShelves] = useState<ShelfSummary | null>(null);
  const [buddyReads, setBuddyReads] = useState<BuddyRead[]>([]);

  const [selectedGenre, setSelectedGenre] = useState<string>('Todos');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);

  // Modales
  const [selectedBookForReader, setSelectedBookForReader] = useState<Book | null>(null);
  const [isUploadModalVisible, setIsUploadModalVisible] = useState<boolean>(false);
  const [isCreateBuddyModalVisible, setIsCreateBuddyModalVisible] = useState<boolean>(false);

  const currentUserId = getCurrentUserId();

  const loadData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    try {
      const [fetchedBooks, links, fetchedShelves, fetchedBuddy] = await Promise.all([
        fetchBooks(undefined, undefined, activeTelegramLinkId || undefined),
        fetchTelegramLinks().catch(() => []),
        fetchReadingShelves().catch(() => null),
        fetchBuddyReads(activeTelegramLinkId || undefined).catch(() => []),
      ]);
      setBooks(fetchedBooks);
      setTelegramLinks(links);
      setShelves(fetchedShelves);
      setBuddyReads(fetchedBuddy);
      onShelvesLoaded?.(fetchedShelves, fetchedBooks.length, fetchedBooks);
    } catch (err: any) {
      console.warn('Error cargando biblioteca:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [activeTelegramLinkId, onShelvesLoaded]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Lista única de géneros dinámicos calculada desde los libros
  const availableGenres = useMemo(() => {
    const set = new Set<string>();
    books.forEach((b) => {
      if (b.genre) set.add(b.genre);
    });
    return ['Todos', ...Array.from(set).sort()];
  }, [books]);

  // Libros filtrados por búsqueda y género
  const filteredBooks = useMemo(() => {
    return books.filter((book) => {
      const matchGenre =
        selectedGenre === 'Todos' ||
        book.genre.toLowerCase() === selectedGenre.toLowerCase();

      const q = searchQuery.toLowerCase().trim();
      const matchSearch =
        !q ||
        book.title.toLowerCase().includes(q) ||
        (book.author && book.author.toLowerCase().includes(q));

      return matchGenre && matchSearch;
    });
  }, [books, selectedGenre, searchQuery]);

  // Estadísticas rápidas
  const stats = useMemo(() => {
    const total = books.length;
    const inProgress = shelves?.reading.length ?? books.filter((b) => b.reading_progress > 0 && b.reading_progress < 100).length;
    const completed = shelves?.finished.length ?? books.filter((b) => b.reading_progress >= 100).length;
    const favCount = shelves?.favorites.length ?? 0;
    return { total, inProgress, completed, favCount };
  }, [books, shelves]);

  const handleProgressUpdated = async (bookId: number, progress: number) => {
    setBooks((prev) =>
      prev.map((b) => (b.id === bookId ? { ...b, reading_progress: progress } : b))
    );
    if (selectedBookForReader && selectedBookForReader.id === bookId) {
      setSelectedBookForReader((prev) => (prev ? { ...prev, reading_progress: progress } : null));
    }
    // Sincronizar con el backend
    try {
      await updateBookReadingState(bookId, {
        progress_percent: progress,
        status: progress >= 100 ? 'finished' : progress > 0 ? 'reading' : undefined,
      });
      const updatedShelves = await fetchReadingShelves().catch(() => null);
      if (updatedShelves) setShelves(updatedShelves);
    } catch (e) {
      console.warn('Error sincronizando estado de lectura:', e);
    }
  };

  const handleToggleFavorite = async (bookId: number, currentFav: boolean) => {
    try {
      await updateBookReadingState(bookId, { is_favorite: !currentFav });
      const updated = await fetchReadingShelves();
      setShelves(updated);
    } catch (e) {
      Alert.alert('Error', 'No se pudo actualizar favoritos');
    }
  };

  const handleJoinBuddyRead = async (brId: number) => {
    try {
      await joinBuddyRead(brId);
      Alert.alert('¡Éxito!', 'Te has unido a la lectura conjunta');
      const updated = await fetchBuddyReads();
      setBuddyReads(updated);
      const updatedShelves = await fetchReadingShelves();
      setShelves(updatedShelves);
    } catch (e: any) {
      Alert.alert('Aviso', e.message || 'Error al unirse');
    }
  };

  const handleUpdateBuddyProgress = async (brId: number, newPct: number) => {
    try {
      await updateBuddyReadProgress(brId, newPct);
      const updated = await fetchBuddyReads();
      setBuddyReads(updated);
      const updatedShelves = await fetchReadingShelves();
      setShelves(updatedShelves);
    } catch (e: any) {
      Alert.alert('Error', e.message || 'Error al actualizar avance');
    }
  };

  const handleCreateBuddyRead = async (book: Book) => {
    try {
      const linkId = telegramLinks[0]?.id;
      await createBuddyRead(book.id, `Lectura de ${book.title}`, linkId);
      setIsCreateBuddyModalVisible(false);
      Alert.alert('¡Lectura Iniciada!', `Se ha iniciado la lectura conjunta de "${book.title}".`);
      const updated = await fetchBuddyReads();
      setBuddyReads(updated);
      setActiveTab('buddy');
    } catch (e: any) {
      Alert.alert('Error', e.message || 'No se pudo iniciar la lectura conjunta');
    }
  };

  // Libros para la pestaña actual de estantes
  const currentShelfBooks: ReadingState[] = useMemo(() => {
    if (!shelves) return [];
    if (selectedShelf === 'reading') return shelves.reading;
    if (selectedShelf === 'favorites') return shelves.favorites;
    if (selectedShelf === 'to_read') return shelves.to_read;
    if (selectedShelf === 'finished') return shelves.finished;
    return [];
  }, [shelves, selectedShelf]);

  return (
    <View style={styles.container}>
      {/* Top Banner / Header */}
      <View style={[styles.header, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
        <View style={styles.headerLeftGroup}>
          {onOpenDrawer && (
            <TouchableOpacity
              onPress={onOpenDrawer}
              style={[styles.drawerTriggerBtn, { backgroundColor: c.cardSecondaryBg }]}
              accessibilityLabel="Abrir menú lateral"
            >
              <Text style={[styles.drawerTriggerIcon, { color: c.textPrimary }]}>☰</Text>
            </TouchableOpacity>
          )}
          <View style={styles.brandContainer}>
            <Image
              source={require('../../assets/anaquel-logo-horizontal.png')}
              style={styles.logoImage}
              resizeMode="contain"
            />
          </View>
        </View>

        <View style={styles.headerRightGroup}>
          {onNavigateToChat && (
            <TouchableOpacity
              onPress={onNavigateToChat}
              style={[styles.chatHeaderBtn, { backgroundColor: c.cardSecondaryBg }]}
              accessibilityLabel="Chat con Griffin"
            >
              <Text style={styles.chatHeaderIcon}>🦉</Text>
            </TouchableOpacity>
          )}

          <TouchableOpacity
            onPress={() => setIsUploadModalVisible(true)}
            style={[styles.uploadBtn, { backgroundColor: c.accent }]}
          >
            <Text style={styles.uploadBtnText}>+ Subir</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Stats Cards */}
      <View style={styles.statsContainer}>
        <View style={[styles.statBox, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.statNumber, { color: c.textPrimary }]}>{stats.total}</Text>
          <Text style={[styles.statLabel, { color: c.textSecondary }]}>Libros</Text>
        </View>
        <View style={[styles.statBox, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.statNumber, { color: '#38bdf8' }]}>{stats.inProgress}</Text>
          <Text style={[styles.statLabel, { color: c.textSecondary }]}>Leyendo</Text>
        </View>
        <View style={[styles.statBox, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.statNumber, { color: '#fbbf24' }]}>{stats.favCount}</Text>
          <Text style={[styles.statLabel, { color: c.textSecondary }]}>Favoritos</Text>
        </View>
        <View style={[styles.statBox, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.statNumber, { color: '#10b981' }]}>{stats.completed}</Text>
          <Text style={[styles.statLabel, { color: c.textSecondary }]}>Terminados</Text>
        </View>
      </View>

      {/* Navigation Segmented Control */}
      <View style={[styles.segmentedControl, { backgroundColor: c.cardSecondaryBg }]}>
        <TouchableOpacity
          style={[styles.segmentBtn, activeTab === 'catalog' && [styles.segmentBtnActive, { backgroundColor: c.cardBg }]]}
          onPress={() => setActiveTab('catalog')}
        >
          <Text style={[styles.segmentText, { color: activeTab === 'catalog' ? c.textPrimary : c.textSecondary }, activeTab === 'catalog' && styles.segmentTextActive]}>
            📚 Catálogo
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.segmentBtn, activeTab === 'shelves' && [styles.segmentBtnActive, { backgroundColor: c.cardBg }]]}
          onPress={() => setActiveTab('shelves')}
        >
          <Text style={[styles.segmentText, { color: activeTab === 'shelves' ? c.textPrimary : c.textSecondary }, activeTab === 'shelves' && styles.segmentTextActive]}>
            📖 Mis Estantes
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.segmentBtn, activeTab === 'buddy' && [styles.segmentBtnActive, { backgroundColor: c.cardBg }]]}
          onPress={() => setActiveTab('buddy')}
        >
          <Text style={[styles.segmentText, { color: activeTab === 'buddy' ? c.textPrimary : c.textSecondary }, activeTab === 'buddy' && styles.segmentTextActive]}>
            👥 Lectura Conjunta
          </Text>
        </TouchableOpacity>
      </View>

      {/* ================= PESTAÑA 1: CATÁLOGO GENERAL ================= */}
      {activeTab === 'catalog' && (
        <>
          <SearchBar
            value={searchQuery}
            onChangeText={setSearchQuery}
            onClear={() => setSearchQuery('')}
          />

          <View style={styles.genreListWrapper}>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.genreScrollContainer}
            >
              {availableGenres.map((genre) => (
                <GenreChip
                  key={genre}
                  genre={genre}
                  isSelected={selectedGenre === genre}
                  onPress={() => setSelectedGenre(genre)}
                  count={
                    genre === 'Todos'
                      ? books.length
                      : books.filter((b) => b.genre.toLowerCase() === genre.toLowerCase()).length
                  }
                />
              ))}
            </ScrollView>
          </View>

          {loading && !refreshing ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color="#6366f1" />
              <Text style={styles.loadingText}>Cargando catálogo sincronizado...</Text>
            </View>
          ) : (
            <FlatList
              data={filteredBooks}
              key={numColumns}
              numColumns={numColumns}
              keyExtractor={(item) => String(item.id)}
              renderItem={({ item }) => (
                <View style={{ width: cardWidth, marginRight: numColumns > 1 ? 12 : 0 }}>
                  <BookCard
                    book={item}
                    onPress={() => setSelectedBookForReader(item)}
                  />
                </View>
              )}
              contentContainerStyle={styles.listContent}
              refreshControl={
                <RefreshControl
                  refreshing={refreshing}
                  onRefresh={() => loadData(true)}
                  tintColor="#6366f1"
                  colors={['#6366f1']}
                />
              }
              ListEmptyComponent={
                <View style={styles.emptyContainer}>
                  <Text style={styles.emptyIcon}>📖</Text>
                  <Text style={styles.emptyTitle}>No se encontraron libros</Text>
                  <Text style={styles.emptySubtitle}>
                    {searchQuery
                      ? `No hay coincidencias para "${searchQuery}"`
                      : 'Sube libros desde el botón "+ Subir" o envíalos al grupo de Telegram.'}
                  </Text>
                </View>
              }
            />
          )}
        </>
      )}

      {/* ================= PESTAÑA 2: MIS ESTANTES ================= */}
      {activeTab === 'shelves' && (
        <View style={{ flex: 1 }}>
          <View style={styles.shelfSubTabs}>
            <TouchableOpacity
              style={[styles.shelfPill, selectedShelf === 'reading' && styles.shelfPillActive]}
              onPress={() => setSelectedShelf('reading')}
            >
              <Text style={[styles.shelfPillText, selectedShelf === 'reading' && styles.shelfPillTextActive]}>
                📖 Leyendo ({shelves?.reading.length ?? 0})
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.shelfPill, selectedShelf === 'favorites' && styles.shelfPillActive]}
              onPress={() => setSelectedShelf('favorites')}
            >
              <Text style={[styles.shelfPillText, selectedShelf === 'favorites' && styles.shelfPillTextActive]}>
                ⭐ Favoritos ({shelves?.favorites.length ?? 0})
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.shelfPill, selectedShelf === 'to_read' && styles.shelfPillActive]}
              onPress={() => setSelectedShelf('to_read')}
            >
              <Text style={[styles.shelfPillText, selectedShelf === 'to_read' && styles.shelfPillTextActive]}>
                📌 Por Leer ({shelves?.to_read.length ?? 0})
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.shelfPill, selectedShelf === 'finished' && styles.shelfPillActive]}
              onPress={() => setSelectedShelf('finished')}
            >
              <Text style={[styles.shelfPillText, selectedShelf === 'finished' && styles.shelfPillTextActive]}>
                🏆 Terminados ({shelves?.finished.length ?? 0})
              </Text>
            </TouchableOpacity>
          </View>

          <FlatList
            data={currentShelfBooks}
            keyExtractor={(item) => String(item.id)}
            contentContainerStyle={styles.shelfListContent}
            renderItem={({ item }) => {
              const b = item.book;
              if (!b) return null;
              return (
                <View style={styles.shelfBookCard}>
                  <View style={styles.shelfBookInfo}>
                    <Text style={styles.shelfBookTitle} numberOfLines={1}>{b.title}</Text>
                    <Text style={styles.shelfBookAuthor} numberOfLines={1}>✍️ {b.author || 'Desconocido'}</Text>
                    <Text style={styles.shelfBookGenre}>🏷️ {b.genre} (.{b.file_format.toUpperCase()})</Text>

                    {/* Barra de progreso */}
                    <View style={styles.shelfProgressBarContainer}>
                      <View style={styles.shelfProgressBarBg}>
                        <View style={[styles.shelfProgressBarFill, { width: `${item.progress_percent}%` }]} />
                      </View>
                      <Text style={styles.shelfProgressText}>{Math.round(item.progress_percent)}%</Text>
                    </View>
                  </View>

                  <View style={styles.shelfCardActions}>
                    <TouchableOpacity
                      onPress={() => handleToggleFavorite(b.id, item.is_favorite)}
                      style={styles.favBtn}
                    >
                      <Text style={styles.favBtnIcon}>{item.is_favorite ? '⭐' : '☆'}</Text>
                    </TouchableOpacity>

                    <TouchableOpacity
                      onPress={() => setSelectedBookForReader(b)}
                      style={styles.openReaderBtn}
                    >
                      <Text style={styles.openReaderBtnText}>Leer</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              );
            }}
            ListEmptyComponent={
              <View style={styles.emptyContainer}>
                <Text style={styles.emptyIcon}>📚</Text>
                <Text style={styles.emptyTitle}>Estante vacío</Text>
                <Text style={styles.emptySubtitle}>
                  {selectedShelf === 'reading' && 'No estás leyendo ningún libro actualmente.'}
                  {selectedShelf === 'favorites' && 'Aún no has marcado libros como favoritos con la estrella.'}
                  {selectedShelf === 'to_read' && 'Tu lista de lecturas pendientes está vacía.'}
                  {selectedShelf === 'finished' && 'Aquí verás los libros que hayas completado al 100%.'}
                </Text>
              </View>
            }
          />
        </View>
      )}

      {/* ================= PESTAÑA 3: LECTURA CONJUNTA ================= */}
      {activeTab === 'buddy' && (
        <View style={{ flex: 1 }}>
          <View style={styles.buddyHeaderRow}>
            <Text style={styles.buddySectionTitle}>Lecturas del Club en Vivo</Text>
            <TouchableOpacity
              style={styles.startBuddyBtn}
              onPress={() => setIsCreateBuddyModalVisible(true)}
            >
              <Text style={styles.startBuddyBtnText}>+ Iniciar Conjunta</Text>
            </TouchableOpacity>
          </View>

          <FlatList
            data={buddyReads}
            keyExtractor={(item) => String(item.id)}
            contentContainerStyle={styles.buddyListContent}
            renderItem={({ item }) => {
              const b = item.book;
              const isMember = item.members.some((m) => m.user_id === currentUserId);
              const myMember = item.members.find((m) => m.user_id === currentUserId);

              return (
                <View style={styles.buddyCard}>
                  <View style={styles.buddyCardHeader}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.buddyBookTitle}>{b?.title || item.title || 'Lectura Conjunta'}</Text>
                      <Text style={styles.buddyBookAuthor}>✍️ {b?.author || 'Desconocido'}</Text>
                    </View>
                    <View style={styles.buddyBadge}>
                      <Text style={styles.buddyBadgeText}>{item.members.length} lectores</Text>
                    </View>
                  </View>

                  <Text style={styles.buddyMembersTitle}>Avance de los miembros:</Text>
                  {item.members.map((m) => (
                    <View key={m.id} style={styles.buddyMemberRow}>
                      <Text style={styles.buddyMemberName} numberOfLines={1}>
                        {m.progress_percent >= 100 ? '🏆' : '📖'} {m.telegram_name || m.telegram_username || `Lector #${m.user_id}`}
                      </Text>
                      <View style={styles.buddyMemberBarBg}>
                        <View
                          style={[
                            styles.buddyMemberBarFill,
                            {
                              width: `${m.progress_percent}%`,
                              backgroundColor: m.progress_percent >= 100 ? '#10b981' : '#6366f1',
                            },
                          ]}
                        />
                      </View>
                      <Text style={styles.buddyMemberPct}>{Math.round(m.progress_percent)}%</Text>
                    </View>
                  ))}

                  {/* Acciones de la Lectura Conjunta */}
                  <View style={styles.buddyActionsRow}>
                    {!isMember ? (
                      <TouchableOpacity
                        style={styles.joinBuddyBtn}
                        onPress={() => handleJoinBuddyRead(item.id)}
                      >
                        <Text style={styles.joinBuddyBtnText}>🤝 Unirme a la Lectura</Text>
                      </TouchableOpacity>
                    ) : (
                      <View style={styles.progressUpdateRow}>
                        <Text style={styles.myProgLabel}>Mi avance:</Text>
                        <TouchableOpacity
                          style={styles.quickProgBtn}
                          onPress={() => handleUpdateBuddyProgress(item.id, Math.min(100, (myMember?.progress_percent ?? 0) + 10))}
                        >
                          <Text style={styles.quickProgText}>+10%</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                          style={styles.quickProgBtn}
                          onPress={() => handleUpdateBuddyProgress(item.id, Math.min(100, (myMember?.progress_percent ?? 0) + 25))}
                        >
                          <Text style={styles.quickProgText}>+25%</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                          style={[styles.quickProgBtn, { backgroundColor: '#10b981' }]}
                          onPress={() => handleUpdateBuddyProgress(item.id, 100)}
                        >
                          <Text style={styles.quickProgText}>100% 🏆</Text>
                        </TouchableOpacity>
                      </View>
                    )}

                    {b && (
                      <TouchableOpacity
                        style={styles.readNowBtn}
                        onPress={() => setSelectedBookForReader(b)}
                      >
                        <Text style={styles.readNowBtnText}>Leer libro</Text>
                      </TouchableOpacity>
                    )}
                  </View>
                </View>
              );
            }}
            ListEmptyComponent={
              <View style={styles.emptyContainer}>
                <Text style={styles.emptyIcon}>👥</Text>
                <Text style={styles.emptyTitle}>No hay lecturas conjuntas activas</Text>
                <Text style={styles.emptySubtitle}>
                  Sé el primero en iniciar una lectura compartida tocando "+ Iniciar Conjunta" o enviando /leerjuntos en Telegram.
                </Text>
              </View>
            }
          />
        </View>
      )}

      {/* Reader Modal */}
      <ReaderModal
        visible={!!selectedBookForReader}
        book={selectedBookForReader}
        onClose={() => setSelectedBookForReader(null)}
        onProgressUpdated={handleProgressUpdated}
      />

      {/* Upload Modal */}
      <UploadModal
        visible={isUploadModalVisible}
        onClose={() => setIsUploadModalVisible(false)}
        telegramLinks={telegramLinks}
        onUploadSuccess={() => loadData(true)}
      />

      {/* Modal para Iniciar Lectura Conjunta */}
      <Modal
        visible={isCreateBuddyModalVisible}
        animationType="slide"
        transparent
        onRequestClose={() => setIsCreateBuddyModalVisible(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.buddyPickModal}>
            <View style={styles.buddyPickHeader}>
              <Text style={styles.buddyPickTitle}>Selecciona un Libro para Leer Juntos</Text>
              <TouchableOpacity onPress={() => setIsCreateBuddyModalVisible(false)}>
                <Text style={styles.closeBtn}>✕</Text>
              </TouchableOpacity>
            </View>

            <FlatList
              data={books}
              keyExtractor={(b) => String(b.id)}
              renderItem={({ item }) => (
                <TouchableOpacity
                  style={styles.pickBookItem}
                  onPress={() => handleCreateBuddyRead(item)}
                >
                  <Text style={styles.pickBookTitle} numberOfLines={1}>📖 {item.title}</Text>
                  <Text style={styles.pickBookAuthor} numberOfLines={1}>✍️ {item.author} | 🏷️ {item.genre}</Text>
                </TouchableOpacity>
              )}
            />
          </View>
        </View>
      </Modal>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: 'transparent',
    paddingHorizontal: 16,
    paddingTop: 12,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  headerLeftGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  drawerTriggerBtn: {
    width: 38,
    height: 38,
    borderRadius: 10,
    backgroundColor: '#FBF8F3',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#DFD5C6',
    shadowColor: '#2C221E',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  drawerTriggerIcon: {
    fontSize: 18,
    color: '#2C221E',
    fontWeight: '700',
  },
  brandContainer: {
    justifyContent: 'center',
  },
  logoImage: {
    width: 155,
    height: 40,
  },
  headerRightGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  chatHeaderBtn: {
    width: 38,
    height: 38,
    borderRadius: 10,
    backgroundColor: '#FBF8F3',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#DFD5C6',
    shadowColor: '#2C221E',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  chatHeaderIcon: {
    fontSize: 18,
  },
  uploadBtn: {
    backgroundColor: '#2C2523',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
    shadowColor: '#3c2f2f',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.15,
    shadowRadius: 4,
    elevation: 3,
  },
  uploadBtnText: {
    color: '#FBF8F3',
    fontSize: 13,
    fontWeight: '700',
  },
  statsContainer: {
    flexDirection: 'row',
    backgroundColor: '#FBF8F3',
    borderRadius: 14,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#DFD5C6',
    justifyContent: 'space-around',
    shadowColor: '#3c2f2f',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  statBox: {
    alignItems: 'center',
  },
  statNumber: {
    fontSize: 17,
    fontWeight: '800',
    color: '#2C221E',
  },
  statLabel: {
    fontSize: 11,
    color: '#7A6E65',
    marginTop: 2,
    fontWeight: '500',
  },
  segmentedControl: {
    flexDirection: 'row',
    backgroundColor: '#EDE5D8',
    borderRadius: 10,
    padding: 3,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#DFD5C6',
  },
  segmentBtn: {
    flex: 1,
    paddingVertical: 8,
    alignItems: 'center',
    borderRadius: 8,
  },
  segmentBtnActive: {
    backgroundColor: '#2C2523',
  },
  segmentText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#7A6E65',
  },
  segmentTextActive: {
    color: '#FBF8F3',
    fontWeight: '700',
  },
  genreListWrapper: {
    marginBottom: 12,
  },
  genreScrollContainer: {
    paddingVertical: 2,
  },
  listContent: {
    paddingBottom: 24,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    color: '#7A6E65',
    marginTop: 12,
    fontSize: 14,
  },
  emptyContainer: {
    paddingVertical: 60,
    alignItems: 'center',
    paddingHorizontal: 24,
  },
  emptyIcon: {
    fontSize: 44,
    marginBottom: 10,
  },
  emptyTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: '#2C221E',
    marginBottom: 6,
  },
  emptySubtitle: {
    fontSize: 13,
    color: '#7A6E65',
    textAlign: 'center',
    lineHeight: 18,
  },
  // Estantes
  shelfSubTabs: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: 12,
  },
  shelfPill: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 16,
    backgroundColor: '#F3EDE2',
    borderWidth: 1,
    borderColor: '#DFD5C6',
  },
  shelfPillActive: {
    backgroundColor: '#2C2523',
    borderColor: '#2C2523',
  },
  shelfPillText: {
    fontSize: 12,
    color: '#7A6E65',
    fontWeight: '600',
  },
  shelfPillTextActive: {
    color: '#FAF7F2',
    fontWeight: '700',
  },
  shelfListContent: {
    paddingBottom: 24,
  },
  shelfBookCard: {
    flexDirection: 'row',
    backgroundColor: '#FBF8F3',
    borderRadius: 14,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#DFD5C6',
    alignItems: 'center',
    shadowColor: '#2C221E',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  shelfBookInfo: {
    flex: 1,
  },
  shelfBookTitle: {
    color: '#2C221E',
    fontSize: 15,
    fontWeight: '700',
    marginBottom: 3,
  },
  shelfBookAuthor: {
    color: '#7A6E65',
    fontSize: 13,
    marginBottom: 2,
  },
  shelfBookGenre: {
    color: '#9C8E82',
    fontSize: 11,
    marginBottom: 6,
  },
  shelfProgressBarContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  shelfProgressBarBg: {
    flex: 1,
    height: 6,
    backgroundColor: '#E5DDD0',
    borderRadius: 3,
    overflow: 'hidden',
  },
  shelfProgressBarFill: {
    height: '100%',
    backgroundColor: '#D97706',
  },
  shelfProgressText: {
    color: '#D97706',
    fontSize: 11,
    fontWeight: '700',
  },
  shelfCardActions: {
    alignItems: 'center',
    gap: 8,
    marginLeft: 12,
  },
  favBtn: {
    padding: 4,
  },
  favBtnIcon: {
    fontSize: 22,
    color: '#D97706',
  },
  openReaderBtn: {
    backgroundColor: '#2C2523',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  openReaderBtnText: {
    color: '#FAF7F2',
    fontSize: 12,
    fontWeight: '700',
  },
  // Lecturas Conjuntas
  buddyHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  buddySectionTitle: {
    color: '#2C221E',
    fontSize: 16,
    fontWeight: '700',
  },
  startBuddyBtn: {
    backgroundColor: '#2C2523',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  startBuddyBtnText: {
    color: '#FAF7F2',
    fontSize: 12,
    fontWeight: '700',
  },
  buddyListContent: {
    paddingBottom: 24,
  },
  buddyCard: {
    backgroundColor: '#FBF8F3',
    borderRadius: 14,
    padding: 14,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#DFD5C6',
    shadowColor: '#2C221E',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  buddyCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 10,
  },
  buddyBookTitle: {
    color: '#2C221E',
    fontSize: 16,
    fontWeight: '700',
  },
  buddyBookAuthor: {
    color: '#7A6E65',
    fontSize: 13,
    marginTop: 2,
  },
  buddyBadge: {
    backgroundColor: '#EDE5D8',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  buddyBadgeText: {
    color: '#D97706',
    fontSize: 11,
    fontWeight: '600',
  },
  buddyMembersTitle: {
    color: '#7A6E65',
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 6,
  },
  buddyMemberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  buddyMemberName: {
    color: '#2C221E',
    fontSize: 12,
    width: 100,
  },
  buddyMemberBarBg: {
    flex: 1,
    height: 6,
    backgroundColor: '#E5DDD0',
    borderRadius: 3,
    overflow: 'hidden',
    marginHorizontal: 8,
  },
  buddyMemberBarFill: {
    height: '100%',
  },
  buddyMemberPct: {
    color: '#7A6E65',
    fontSize: 11,
    fontWeight: '700',
    width: 35,
    textAlign: 'right',
  },
  buddyActionsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: '#DFD5C6',
  },
  joinBuddyBtn: {
    backgroundColor: '#D97706',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  joinBuddyBtnText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '700',
  },
  progressUpdateRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  myProgLabel: {
    color: '#7A6E65',
    fontSize: 11,
    fontWeight: '600',
  },
  quickProgBtn: {
    backgroundColor: '#EDE5D8',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: '#DFD5C6',
  },
  quickProgText: {
    color: '#2C221E',
    fontSize: 11,
    fontWeight: '700',
  },
  readNowBtn: {
    backgroundColor: '#2C2523',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
  },
  readNowBtnText: {
    color: '#FAF7F2',
    fontSize: 12,
    fontWeight: '600',
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(44, 34, 30, 0.65)',
    justifyContent: 'flex-end',
  },
  buddyPickModal: {
    backgroundColor: '#FBF8F3',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    padding: 16,
    maxHeight: '75%',
    borderTopWidth: 1,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: '#DFD5C6',
  },
  buddyPickHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 14,
  },
  buddyPickTitle: {
    color: '#2C221E',
    fontSize: 16,
    fontWeight: '700',
  },
  closeBtn: {
    color: '#7A6E65',
    fontSize: 20,
    padding: 4,
  },
  pickBookItem: {
    backgroundColor: '#EDE5D8',
    borderRadius: 10,
    padding: 12,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: '#DFD5C6',
  },
  pickBookTitle: {
    color: '#2C221E',
    fontSize: 14,
    fontWeight: '700',
    marginBottom: 2,
  },
  pickBookAuthor: {
    color: '#7A6E65',
    fontSize: 12,
  },
});
