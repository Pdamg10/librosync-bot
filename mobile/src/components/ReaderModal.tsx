import React, { useState } from 'react';
import {
  Modal,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Linking,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Book, ThemeMode } from '../types';
import { colors, getGenreEmoji } from '../theme/colors';
import { getBookDownloadUrl, updateReadingProgress } from '../services/api';

interface ReaderModalProps {
  visible: boolean;
  book: Book | null;
  onClose: () => void;
  onProgressUpdated: (bookId: number, progress: number) => void;
}

export const ReaderModal: React.FC<ReaderModalProps> = ({
  visible,
  book,
  onClose,
  onProgressUpdated,
}) => {
  if (!book) return null;

  const [readerTheme, setReaderTheme] = useState<ThemeMode>('dark');
  const [fontSize, setFontSize] = useState<number>(17);
  const [currentProgress, setCurrentProgress] = useState<number>(book.reading_progress || 0);
  const [isSaving, setIsSaving] = useState<boolean>(false);

  const themeColors = colors[readerTheme];
  const emoji = getGenreEmoji(book.genre);

  const handleUpdateProgress = async (newProgress: number) => {
    setCurrentProgress(newProgress);
    setIsSaving(true);
    try {
      await updateReadingProgress(book.id, newProgress);
      onProgressUpdated(book.id, newProgress);
    } catch (e: any) {
      console.warn('Error al guardar progreso:', e);
    } finally {
      setIsSaving(false);
    }
  };

  const handleOpenExternal = async () => {
    const downloadUrl = getBookDownloadUrl(book.id);
    try {
      const supported = await Linking.canOpenURL(downloadUrl);
      if (supported) {
        await Linking.openURL(downloadUrl);
      } else {
        Alert.alert('Descarga', `Abre este enlace en tu navegador o lector:\n${downloadUrl}`);
      }
    } catch {
      await Linking.openURL(downloadUrl);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView style={[styles.safeArea, { backgroundColor: themeColors.background }]}>
        {/* Header Toolbar */}
        <View style={[styles.header, { borderBottomColor: themeColors.border }]}>
          <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
            <Text style={[styles.closeBtnText, { color: themeColors.text }]}>✕ Cerrar</Text>
          </TouchableOpacity>

          <View style={styles.headerTitleContainer}>
            <Text style={[styles.headerTitle, { color: themeColors.text }]} numberOfLines={1}>
              {book.title}
            </Text>
            <Text style={[styles.headerSubtitle, { color: themeColors.textSecondary }]} numberOfLines={1}>
              {book.author}
            </Text>
          </View>

          <TouchableOpacity onPress={handleOpenExternal} style={styles.downloadBtn}>
            <Text style={styles.downloadBtnText}>📥 Abrir</Text>
          </TouchableOpacity>
        </View>

        {/* Controls Toolbar (Font Size & Themes) */}
        <View style={[styles.controlsBar, { backgroundColor: themeColors.surface, borderBottomColor: themeColors.border }]}>
          {/* Themes */}
          <View style={styles.themeSelector}>
            <TouchableOpacity
              onPress={() => setReaderTheme('dark')}
              style={[
                styles.themeDot,
                { backgroundColor: '#0f172a', borderColor: readerTheme === 'dark' ? '#6366f1' : '#334155' },
              ]}
            >
              <Text style={{ fontSize: 10, color: '#fff' }}>🌙</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => setReaderTheme('sepia')}
              style={[
                styles.themeDot,
                { backgroundColor: '#fcf6ea', borderColor: readerTheme === 'sepia' ? '#b45309' : '#dfd2b5' },
              ]}
            >
              <Text style={{ fontSize: 10, color: '#443627' }}>📜</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => setReaderTheme('light')}
              style={[
                styles.themeDot,
                { backgroundColor: '#ffffff', borderColor: readerTheme === 'light' ? '#4f46e5' : '#cbd5e1' },
              ]}
            >
              <Text style={{ fontSize: 10, color: '#000' }}>☀️</Text>
            </TouchableOpacity>
          </View>

          {/* Font size */}
          <View style={styles.fontSizeControls}>
            <TouchableOpacity
              onPress={() => setFontSize((f) => Math.max(13, f - 2))}
              style={[styles.fontBtn, { backgroundColor: themeColors.surfaceLight }]}
            >
              <Text style={[styles.fontBtnText, { color: themeColors.text }]}>A-</Text>
            </TouchableOpacity>
            <Text style={[styles.fontSizeLabel, { color: themeColors.textSecondary }]}>{fontSize}</Text>
            <TouchableOpacity
              onPress={() => setFontSize((f) => Math.min(26, f + 2))}
              style={[styles.fontBtn, { backgroundColor: themeColors.surfaceLight }]}
            >
              <Text style={[styles.fontBtnText, { color: themeColors.text }]}>A+</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Reader Content Body */}
        <ScrollView contentContainerStyle={styles.bodyContent}>
          {/* Book Header Card */}
          <View style={[styles.bookCard, { backgroundColor: themeColors.surface, borderColor: themeColors.border }]}>
            <Text style={styles.genreBanner}>{emoji} {book.genre.toUpperCase()}</Text>
            <Text style={[styles.bookMainTitle, { color: themeColors.text }]}>{book.title}</Text>
            <Text style={[styles.bookMainAuthor, { color: themeColors.textSecondary }]}>Por: {book.author}</Text>
            <Text style={[styles.formatTag, { color: themeColors.textMuted }]}>
              Formato: {book.file_format.toUpperCase()} • Sincronizado con Telegram
            </Text>

            <TouchableOpacity onPress={handleOpenExternal} style={styles.mainActionBtn}>
              <Text style={styles.mainActionBtnText}>
                🚀 Abrir archivo completo en lector ({book.file_format.toUpperCase()})
              </Text>
            </TouchableOpacity>
          </View>

          {/* Reading preview / note text */}
          <View style={styles.textContainer}>
            <Text style={[styles.paragraph, { color: themeColors.text, fontSize, lineHeight: fontSize * 1.6 }]}>
              Bienvenido al lector integrado de <Text style={{ fontWeight: 'bold' }}>Anaquel</Text>. Este ejemplar está sincronizado en tiempo real con tu biblioteca de Telegram.
            </Text>

            <Text style={[styles.paragraph, { color: themeColors.text, fontSize, lineHeight: fontSize * 1.6 }]}>
              Puedes ajustar el tamaño de texto, el modo de contraste (Noche, Sepia o Día) y registrar tu avance de lectura a continuación. Los cambios se guardarán automáticamente en tu base de datos y se reflejarán tanto en esta app como en el bot de Telegram.
            </Text>
          </View>

          {/* Reading Progress Tracker Section */}
          <View style={[styles.progressCard, { backgroundColor: themeColors.surface, borderColor: themeColors.border }]}>
            <View style={styles.progressCardHeader}>
              <Text style={[styles.progressCardTitle, { color: themeColors.text }]}>
                📊 Progreso de lectura: {Math.round(currentProgress)}%
              </Text>
              {isSaving && <ActivityIndicator size="small" color="#6366f1" />}
            </View>

            {/* Visual Progress Bar */}
            <View style={[styles.progressBarBg, { backgroundColor: themeColors.surfaceLight }]}>
              <View
                style={[
                  styles.progressBarFill,
                  { width: `${Math.min(100, Math.max(0, currentProgress))}%` },
                  currentProgress >= 100 && styles.progressBarDone,
                ]}
              />
            </View>

            {/* Quick buttons */}
            <View style={styles.quickButtonsRow}>
              {[0, 25, 50, 75, 100].map((val) => (
                <TouchableOpacity
                  key={val}
                  onPress={() => handleUpdateProgress(val)}
                  style={[
                    styles.quickBtn,
                    currentProgress === val ? styles.quickBtnActive : { backgroundColor: themeColors.surfaceLight },
                  ]}
                >
                  <Text
                    style={[
                      styles.quickBtnText,
                      currentProgress === val ? styles.quickBtnTextActive : { color: themeColors.textSecondary },
                    ]}
                  >
                    {val === 0 ? 'Inicio' : val === 100 ? '✅ Leído' : `${val}%`}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  closeBtn: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 8,
  },
  closeBtnText: {
    fontSize: 15,
    fontWeight: '600',
  },
  headerTitleContainer: {
    flex: 1,
    paddingHorizontal: 12,
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  headerSubtitle: {
    fontSize: 12,
  },
  downloadBtn: {
    backgroundColor: '#6366f1',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  downloadBtnText: {
    color: '#ffffff',
    fontSize: 13,
    fontWeight: '700',
  },
  controlsBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderBottomWidth: 1,
  },
  themeSelector: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  themeDot: {
    width: 28,
    height: 28,
    borderRadius: 14,
    borderWidth: 2,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 10,
  },
  fontSizeControls: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  fontBtn: {
    width: 32,
    height: 32,
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
  },
  fontBtnText: {
    fontSize: 13,
    fontWeight: 'bold',
  },
  fontSizeLabel: {
    marginHorizontal: 10,
    fontSize: 13,
    fontWeight: '600',
  },
  bodyContent: {
    padding: 20,
    paddingBottom: 40,
  },
  bookCard: {
    padding: 18,
    borderRadius: 14,
    borderWidth: 1,
    marginBottom: 20,
  },
  genreBanner: {
    fontSize: 12,
    fontWeight: '800',
    color: '#818cf8',
    letterSpacing: 1.1,
    marginBottom: 6,
  },
  bookMainTitle: {
    fontSize: 22,
    fontWeight: '800',
    marginBottom: 6,
    lineHeight: 28,
  },
  bookMainAuthor: {
    fontSize: 15,
    marginBottom: 10,
  },
  formatTag: {
    fontSize: 12,
    marginBottom: 16,
  },
  mainActionBtn: {
    backgroundColor: '#4f46e5',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: 'center',
  },
  mainActionBtnText: {
    color: '#ffffff',
    fontWeight: '700',
    fontSize: 14,
  },
  textContainer: {
    marginBottom: 24,
  },
  paragraph: {
    marginBottom: 16,
    textAlign: 'justify',
  },
  progressCard: {
    padding: 16,
    borderRadius: 14,
    borderWidth: 1,
  },
  progressCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10,
  },
  progressCardTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  progressBarBg: {
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
    marginBottom: 16,
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: '#6366f1',
  },
  progressBarDone: {
    backgroundColor: '#10b981',
  },
  quickButtonsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  quickBtn: {
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 8,
    alignItems: 'center',
    minWidth: 50,
  },
  quickBtnActive: {
    backgroundColor: '#6366f1',
  },
  quickBtnText: {
    fontSize: 12,
    fontWeight: '700',
  },
  quickBtnTextActive: {
    color: '#ffffff',
  },
});
