import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  Modal,
  ActivityIndicator,
  Alert,
  SafeAreaView,
  TextInput,
  ScrollView,
} from 'react-native';
import { Book, BuddyRead, TelegramLink } from '../types';
import {
  fetchBuddyReads,
  createBuddyRead,
  joinBuddyRead,
  updateBuddyReadProgress,
  fetchBooks,
  getCurrentUserId,
} from '../services/api';
import { useAppTheme } from '../theme/ThemeContext';
import { ReaderModal } from '../components/ReaderModal';

interface BuddyReadScreenProps {
  onOpenDrawer?: () => void;
  groupTitle?: string;
}

export function BuddyReadScreen({
  onOpenDrawer,
  groupTitle = '💋😜Club de lectura📖❤️',
}: BuddyReadScreenProps) {
  const { theme } = useAppTheme();
  const c = theme.colors;

  const [buddyReads, setBuddyReads] = useState<BuddyRead[]>([]);
  const [catalogBooks, setCatalogBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);

  // Filtro
  const [filterMode, setFilterMode] = useState<'all' | 'mine'>('all');

  // Modales
  const [isCreateModalVisible, setIsCreateModalVisible] = useState<boolean>(false);
  const [selectedBookForReader, setSelectedBookForReader] = useState<Book | null>(null);

  // Formulario nueva sesión
  const [newTitle, setNewTitle] = useState<string>('');
  const [searchBookQuery, setSearchBookQuery] = useState<string>('');
  const [selectedBookId, setSelectedBookId] = useState<number | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  const currentUserId = getCurrentUserId();

  const loadData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    try {
      const [reads, books] = await Promise.all([
        fetchBuddyReads(),
        fetchBooks().catch(() => []),
      ]);
      setBuddyReads(reads);
      setCatalogBooks(books);
    } catch (err) {
      console.warn('Error al cargar lecturas conjuntas:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleJoin = async (buddyReadId: number) => {
    try {
      await joinBuddyRead(buddyReadId);
      Alert.alert('¡Te has unido!', 'Ahora participas en esta lectura conjunta.');
      loadData(true);
    } catch (err: any) {
      Alert.alert('Error', err.message || 'No fue posible unirse a la lectura.');
    }
  };

  const handleUpdateProgress = async (buddyReadId: number, progress: number) => {
    try {
      await updateBuddyReadProgress(buddyReadId, progress);
      loadData(true);
    } catch (err: any) {
      Alert.alert('Error', err.message || 'No fue posible registrar el progreso.');
    }
  };

  const handleCreateSession = async () => {
    if (!selectedBookId) {
      Alert.alert('Selecciona un libro', 'Debes elegir el libro a leer en conjunto.');
      return;
    }

    try {
      setIsSubmitting(true);
      await createBuddyRead(selectedBookId, newTitle.trim() || undefined);
      setIsCreateModalVisible(false);
      setNewTitle('');
      setSelectedBookId(null);
      setSearchBookQuery('');
      Alert.alert('¡Lectura Iniciada!', 'La sesión grupal ha sido creada con éxito.');
      loadData(true);
    } catch (err: any) {
      Alert.alert('Error', err.message || 'No fue posible crear la sesión.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const filteredBuddyReads = buddyReads.filter((br) => {
    if (filterMode === 'mine') {
      return br.members.some((m) => m.user_id === currentUserId);
    }
    return true;
  });

  const filteredBooksForModal = catalogBooks.filter((b) => {
    const q = searchBookQuery.toLowerCase().trim();
    if (!q) return true;
    return b.title.toLowerCase().includes(q) || (b.author && b.author.toLowerCase().includes(q));
  });

  const handleProgressUpdated = async (bookId: number, progress: number) => {
    const activeSession = buddyReads.find(
      (br) => br.book_id === bookId && br.members.some((m) => m.user_id === currentUserId)
    );
    if (activeSession) {
      await updateBuddyReadProgress(activeSession.id, progress).catch(() => {});
    }
    loadData(true);
  };

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: c.canvasBg }]}>
      {/* Header Superior */}
      <View style={[styles.header, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
        <View style={styles.headerLeft}>
          {onOpenDrawer && (
            <TouchableOpacity onPress={onOpenDrawer} style={[styles.menuBtn, { backgroundColor: c.cardSecondaryBg }]}>
              <Text style={[styles.menuIcon, { color: c.textPrimary }]}>☰</Text>
            </TouchableOpacity>
          )}
          <View>
            <Text style={[styles.headerTitle, { color: c.textPrimary }]}>Lectura en Conjunto</Text>
            <Text style={[styles.headerSubtitle, { color: c.textSecondary }]}>{groupTitle}</Text>
          </View>
        </View>

        <TouchableOpacity
          onPress={() => setIsCreateModalVisible(true)}
          style={[styles.createBtn, { backgroundColor: c.accent }]}
        >
          <Text style={styles.createBtnText}>+ Iniciar</Text>
        </TouchableOpacity>
      </View>

      {/* Banner Informativo del Club */}
      <View style={[styles.clubBanner, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
        <View style={styles.clubBannerIconContainer}>
          <Text style={styles.clubBannerIcon}>👥</Text>
        </View>
        <View style={styles.clubBannerTextCol}>
          <Text style={[styles.clubBannerTitle, { color: c.textPrimary }]}>
            Sincronía de Lectura Grupal
          </Text>
          <Text style={[styles.clubBannerDesc, { color: c.textSecondary }]}>
            Lee al mismo ritmo con los integrantes de tu club, comparte impresiones y visualiza el progreso colectivo en tiempo real.
          </Text>
        </View>
      </View>

      {/* Filtros de Vista */}
      <View style={styles.filterRow}>
        <TouchableOpacity
          style={[
            styles.filterPill,
            { backgroundColor: c.cardBg, borderColor: c.cardBorder },
            filterMode === 'all' && [styles.filterPillActive, { backgroundColor: c.cardSecondaryBg, borderColor: c.accent }],
          ]}
          onPress={() => setFilterMode('all')}
        >
          <Text
            style={[
              styles.filterPillText,
              { color: c.textSecondary },
              filterMode === 'all' && [styles.filterPillTextActive, { color: c.textPrimary }],
            ]}
          >
            Todas las lecturas ({buddyReads.length})
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[
            styles.filterPill,
            { backgroundColor: c.cardBg, borderColor: c.cardBorder },
            filterMode === 'mine' && [styles.filterPillActive, { backgroundColor: c.cardSecondaryBg, borderColor: c.accent }],
          ]}
          onPress={() => setFilterMode('mine')}
        >
          <Text
            style={[
              styles.filterPillText,
              { color: c.textSecondary },
              filterMode === 'mine' && [styles.filterPillTextActive, { color: c.textPrimary }],
            ]}
          >
            Mis sesiones activas
          </Text>
        </TouchableOpacity>
      </View>

      {/* Lista de Sesiones de Lectura Conjunta */}
      {loading ? (
        <View style={styles.loadingBox}>
          <ActivityIndicator size="large" color={c.accent} />
          <Text style={[styles.loadingText, { color: c.textSecondary }]}>Cargando sesiones del club...</Text>
        </View>
      ) : (
        <FlatList
          data={filteredBuddyReads}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={styles.listContent}
          refreshing={refreshing}
          onRefresh={() => loadData(true)}
          renderItem={({ item }) => {
            const b = item.book;
            const isMember = item.members.some((m) => m.user_id === currentUserId);
            const myMember = item.members.find((m) => m.user_id === currentUserId);

            return (
              <View
                style={[
                  styles.buddyCard,
                  { backgroundColor: c.cardBg, borderColor: c.cardBorder },
                ]}
              >
                {/* Cabecera del libro */}
                <View style={styles.cardHeader}>
                  <View style={styles.bookIconBadge}>
                    <Text style={styles.bookIconText}>📖</Text>
                  </View>
                  <View style={styles.cardHeaderInfo}>
                    <Text style={[styles.bookTitle, { color: c.textPrimary }]} numberOfLines={1}>
                      {item.title || b?.title || 'Lectura Conjunta'}
                    </Text>
                    <Text style={[styles.bookAuthor, { color: c.textSecondary }]} numberOfLines={1}>
                      ✍️ {b?.author || 'Desconocido'} • 🏷️ {b?.genre || 'General'}
                    </Text>
                  </View>
                  <View style={[styles.readersBadge, { backgroundColor: c.cardSecondaryBg }]}>
                    <Text style={[styles.readersBadgeText, { color: c.accent }]}>
                      {item.members.length} {item.members.length === 1 ? 'lector' : 'lectores'}
                    </Text>
                  </View>
                </View>

                {/* Lista de miembros y sus progresos */}
                <Text style={[styles.membersSectionTitle, { color: c.textMuted }]}>
                  AVANCE DE LOS MIEMBROS
                </Text>
                <View style={styles.membersList}>
                  {item.members.map((m) => (
                    <View key={m.id} style={styles.memberRow}>
                      <Text style={[styles.memberName, { color: c.textPrimary }]} numberOfLines={1}>
                        {m.progress_percent >= 100 ? '🏆' : '👤'}{' '}
                        {m.telegram_name || m.telegram_username || `Lector #${m.user_id}`}
                      </Text>
                      <View style={[styles.progressTrack, { backgroundColor: c.cardSecondaryBg }]}>
                        <View
                          style={[
                            styles.progressFill,
                            {
                              width: `${Math.max(5, Math.min(100, m.progress_percent))}%`,
                              backgroundColor: m.progress_percent >= 100 ? '#10B981' : c.accent,
                            },
                          ]}
                        />
                      </View>
                      <Text style={[styles.memberPct, { color: c.textSecondary }]}>
                        {Math.round(m.progress_percent)}%
                      </Text>
                    </View>
                  ))}
                </View>

                {/* Barra de Acciones */}
                <View style={[styles.cardActionsRow, { borderTopColor: c.cardBorder }]}>
                  {!isMember ? (
                    <TouchableOpacity
                      style={[styles.joinBtn, { backgroundColor: c.accent }]}
                      onPress={() => handleJoin(item.id)}
                    >
                      <Text style={styles.joinBtnText}>🤝 Unirme a esta lectura</Text>
                    </TouchableOpacity>
                  ) : (
                    <View style={styles.progressControlsCol}>
                      <Text style={[styles.myProgText, { color: c.textSecondary }]}>
                        Mi avance: <Text style={{ fontWeight: '700', color: c.accent }}>{Math.round(myMember?.progress_percent ?? 0)}%</Text>
                      </Text>
                      <View style={styles.quickButtonsRow}>
                        <TouchableOpacity
                          style={[styles.quickBtn, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}
                          onPress={() => handleUpdateProgress(item.id, Math.min(100, (myMember?.progress_percent ?? 0) + 10))}
                        >
                          <Text style={[styles.quickBtnText, { color: c.textPrimary }]}>+10%</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                          style={[styles.quickBtn, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}
                          onPress={() => handleUpdateProgress(item.id, Math.min(100, (myMember?.progress_percent ?? 0) + 25))}
                        >
                          <Text style={[styles.quickBtnText, { color: c.textPrimary }]}>+25%</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                          style={[styles.quickBtn, { backgroundColor: '#D1FAE5', borderColor: '#A7F3D0' }]}
                          onPress={() => handleUpdateProgress(item.id, 100)}
                        >
                          <Text style={[styles.quickBtnText, { color: '#047857' }]}>100% 🏆</Text>
                        </TouchableOpacity>
                      </View>
                    </View>
                  )}

                  {b && (
                    <TouchableOpacity
                      style={styles.openReaderBtn}
                      onPress={() => setSelectedBookForReader(b)}
                    >
                      <Text style={styles.openReaderBtnText}>📖 Leer Ahora</Text>
                    </TouchableOpacity>
                  )}
                </View>
              </View>
            );
          }}
          ListEmptyComponent={
            <View style={styles.emptyBox}>
              <Text style={styles.emptyIcon}>📚</Text>
              <Text style={[styles.emptyTitle, { color: c.textPrimary }]}>No hay lecturas conjuntas activas</Text>
              <Text style={[styles.emptySubtitle, { color: c.textSecondary }]}>
                {filterMode === 'mine'
                  ? 'No estás participando en ninguna lectura grupal por ahora.'
                  : '¡Sé el primero en iniciar una lectura compartida con tu club!'}
              </Text>
              <TouchableOpacity
                style={[styles.emptyCreateBtn, { backgroundColor: c.accent }]}
                onPress={() => setIsCreateModalVisible(true)}
              >
                <Text style={styles.emptyCreateBtnText}>+ Iniciar Primera Lectura</Text>
              </TouchableOpacity>
            </View>
          }
        />
      )}

      {/* MODAL PARA CREAR NUEVA LECTURA CONJUNTA */}
      <Modal
        visible={isCreateModalVisible}
        animationType="slide"
        transparent
        onRequestClose={() => setIsCreateModalVisible(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={[styles.modalSheet, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
            <View style={styles.modalHeader}>
              <Text style={[styles.modalTitle, { color: c.textPrimary }]}>Iniciar Lectura Conjunta</Text>
              <TouchableOpacity onPress={() => setIsCreateModalVisible(false)}>
                <Text style={[styles.modalCloseIcon, { color: c.textSecondary }]}>✕</Text>
              </TouchableOpacity>
            </View>

            <Text style={[styles.inputLabel, { color: c.textSecondary }]}>
              Nombre de la sesión (Opcional)
            </Text>
            <TextInput
              style={[styles.textInput, { backgroundColor: c.cardSecondaryBg, color: c.textPrimary, borderColor: c.cardBorder }]}
              placeholder="Ej. Lectura Club - Primavera 2026"
              placeholderTextColor={c.textMuted}
              value={newTitle}
              onChangeText={setNewTitle}
            />

            <Text style={[styles.inputLabel, { color: c.textSecondary }]}>
              Selecciona el libro del catálogo:
            </Text>
            <TextInput
              style={[styles.textInput, { backgroundColor: c.cardSecondaryBg, color: c.textPrimary, borderColor: c.cardBorder }]}
              placeholder="Buscar por título o autor..."
              placeholderTextColor={c.textMuted}
              value={searchBookQuery}
              onChangeText={setSearchBookQuery}
            />

            <ScrollView style={styles.booksPickerList} nestedScrollEnabled>
              {filteredBooksForModal.map((b) => {
                const isSelected = selectedBookId === b.id;
                return (
                  <TouchableOpacity
                    key={b.id}
                    style={[
                      styles.pickBookItem,
                      { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder },
                      isSelected && { borderColor: c.accent, borderWidth: 2 },
                    ]}
                    onPress={() => setSelectedBookId(b.id)}
                  >
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.pickBookTitle, { color: c.textPrimary }]} numberOfLines={1}>
                        {b.title}
                      </Text>
                      <Text style={[styles.pickBookAuthor, { color: c.textSecondary }]} numberOfLines={1}>
                        {b.author || 'Autor desconocido'} • {b.genre}
                      </Text>
                    </View>
                    {isSelected && <Text style={[styles.checkMark, { color: c.accent }]}>✓</Text>}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>

            <TouchableOpacity
              style={[
                styles.submitBtn,
                { backgroundColor: c.accent },
                (!selectedBookId || isSubmitting) && styles.submitBtnDisabled,
              ]}
              onPress={handleCreateSession}
              disabled={!selectedBookId || isSubmitting}
            >
              {isSubmitting ? (
                <ActivityIndicator size="small" color="#FAF7F2" />
              ) : (
                <Text style={styles.submitBtnText}>Crear e Invitar al Club</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* Lector Integrado */}
      <ReaderModal
        visible={selectedBookForReader !== null}
        book={selectedBookForReader}
        onClose={() => setSelectedBookForReader(null)}
        onProgressUpdated={handleProgressUpdated}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 18,
    paddingVertical: 14,
    borderBottomWidth: 1,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  menuBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuIcon: {
    fontSize: 18,
    fontWeight: '700',
  },
  headerTitle: {
    fontSize: 17,
    fontWeight: '700',
  },
  headerSubtitle: {
    fontSize: 12,
  },
  createBtn: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 10,
  },
  createBtnText: {
    color: '#FAF7F2',
    fontWeight: '700',
    fontSize: 13,
  },
  clubBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: 16,
    marginTop: 12,
    marginBottom: 8,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    gap: 12,
  },
  clubBannerIconContainer: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#FEE2E2',
    alignItems: 'center',
    justifyContent: 'center',
  },
  clubBannerIcon: {
    fontSize: 22,
  },
  clubBannerTextCol: {
    flex: 1,
  },
  clubBannerTitle: {
    fontSize: 13,
    fontWeight: '700',
    marginBottom: 2,
  },
  clubBannerDesc: {
    fontSize: 11,
    lineHeight: 16,
  },
  filterRow: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    paddingVertical: 6,
    gap: 8,
  },
  filterPill: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    borderWidth: 1,
  },
  filterPillActive: {},
  filterPillText: {
    fontSize: 12,
    fontWeight: '600',
  },
  filterPillTextActive: {
    fontWeight: '700',
  },
  loadingBox: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingText: {
    marginTop: 10,
    fontSize: 13,
  },
  listContent: {
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 36,
  },
  buddyCard: {
    borderRadius: 16,
    padding: 16,
    marginBottom: 14,
    borderWidth: 1,
    shadowColor: '#2C221E',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 5,
    elevation: 3,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
    gap: 10,
  },
  bookIconBadge: {
    width: 38,
    height: 38,
    borderRadius: 10,
    backgroundColor: '#EDE5D8',
    alignItems: 'center',
    justifyContent: 'center',
  },
  bookIconText: {
    fontSize: 20,
  },
  cardHeaderInfo: {
    flex: 1,
  },
  bookTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  bookAuthor: {
    fontSize: 12,
    marginTop: 2,
  },
  readersBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  readersBadgeText: {
    fontSize: 11,
    fontWeight: '700',
  },
  membersSectionTitle: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.8,
    marginBottom: 8,
  },
  membersList: {
    gap: 6,
    marginBottom: 12,
  },
  memberRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  memberName: {
    width: 110,
    fontSize: 12,
    fontWeight: '600',
  },
  progressTrack: {
    flex: 1,
    height: 7,
    borderRadius: 3.5,
    overflow: 'hidden',
    marginHorizontal: 8,
  },
  progressFill: {
    height: '100%',
    borderRadius: 3.5,
  },
  memberPct: {
    width: 36,
    fontSize: 11,
    fontWeight: '700',
    textAlign: 'right',
  },
  cardActionsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    paddingTop: 12,
    marginTop: 4,
  },
  joinBtn: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 8,
  },
  joinBtnText: {
    color: '#FAF7F2',
    fontSize: 12,
    fontWeight: '700',
  },
  progressControlsCol: {
    flex: 1,
    marginRight: 8,
  },
  myProgText: {
    fontSize: 11,
    marginBottom: 4,
  },
  quickButtonsRow: {
    flexDirection: 'row',
    gap: 6,
  },
  quickBtn: {
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 6,
    borderWidth: 1,
  },
  quickBtnText: {
    fontSize: 11,
    fontWeight: '700',
  },
  openReaderBtn: {
    backgroundColor: '#2C2523',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
  },
  openReaderBtnText: {
    color: '#FAF7F2',
    fontSize: 12,
    fontWeight: '700',
  },
  emptyBox: {
    alignItems: 'center',
    paddingVertical: 40,
    paddingHorizontal: 20,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 10,
  },
  emptyTitle: {
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 4,
  },
  emptySubtitle: {
    fontSize: 13,
    textAlign: 'center',
    lineHeight: 18,
    marginBottom: 16,
  },
  emptyCreateBtn: {
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 10,
  },
  emptyCreateBtnText: {
    color: '#FAF7F2',
    fontSize: 13,
    fontWeight: '700',
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(44, 34, 30, 0.6)',
    justifyContent: 'flex-end',
  },
  modalSheet: {
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 20,
    maxHeight: '80%',
    borderTopWidth: 1,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 14,
  },
  modalTitle: {
    fontSize: 17,
    fontWeight: '700',
  },
  modalCloseIcon: {
    fontSize: 18,
    fontWeight: '700',
    padding: 4,
  },
  inputLabel: {
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 6,
    marginTop: 8,
  },
  textInput: {
    height: 42,
    borderRadius: 10,
    paddingHorizontal: 12,
    fontSize: 13,
    borderWidth: 1,
  },
  booksPickerList: {
    maxHeight: 200,
    marginVertical: 10,
  },
  pickBookItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
    marginBottom: 6,
  },
  pickBookTitle: {
    fontSize: 13,
    fontWeight: '700',
  },
  pickBookAuthor: {
    fontSize: 11,
    marginTop: 2,
  },
  checkMark: {
    fontSize: 16,
    fontWeight: '800',
    marginLeft: 8,
  },
  submitBtn: {
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 8,
  },
  submitBtnDisabled: {
    opacity: 0.5,
  },
  submitBtnText: {
    color: '#FAF7F2',
    fontSize: 14,
    fontWeight: '700',
  },
});
