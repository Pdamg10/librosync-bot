import React, { useState } from 'react';
import {
  Modal,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as DocumentPicker from 'expo-document-picker';
import { TelegramLink } from '../types';
import { uploadBookFromDevice } from '../services/api';
import { colors } from '../theme/colors';

interface UploadModalProps {
  visible: boolean;
  onClose: () => void;
  telegramLinks: TelegramLink[];
  onUploadSuccess: () => void;
}

const COMMON_GENRES = [
  'Dark Romance',
  'Romance',
  'Fantasía',
  'Ciencia Ficción',
  'Terror',
  'Misterio',
  'Desarrollo Personal',
  'General',
];

export const UploadModal: React.FC<UploadModalProps> = ({
  visible,
  onClose,
  telegramLinks,
  onUploadSuccess,
}) => {
  const [selectedFile, setSelectedFile] = useState<DocumentPicker.DocumentPickerAsset | null>(null);
  const [title, setTitle] = useState('');
  const [author, setAuthor] = useState('');
  const [genre, setGenre] = useState('General');
  const [selectedLinkId, setSelectedLinkId] = useState<number>(
    telegramLinks[0]?.id || 1
  );
  const [isLoading, setIsLoading] = useState(false);

  const handlePickDocument = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ['application/pdf', 'application/epub+zip', 'application/octet-stream'],
        copyToCacheDirectory: true,
      });

      if (!result.canceled && result.assets && result.assets.length > 0) {
        const file = result.assets[0];
        setSelectedFile(file);

        // Auto-sugerir título limpiando extensión
        const nameWithoutExt = file.name.replace(/\.(pdf|epub|mobi)$/i, '');
        if (!title) {
          setTitle(nameWithoutExt);
        }
      }
    } catch (err: any) {
      Alert.alert('Error', 'No se pudo seleccionar el archivo: ' + err.message);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      Alert.alert('Archivo requerido', 'Por favor selecciona un archivo PDF o EPUB.');
      return;
    }
    if (!title.trim()) {
      Alert.alert('Título requerido', 'Por favor escribe el título del libro.');
      return;
    }
    if (!selectedLinkId) {
      Alert.alert('Chat de destino requerido', 'No tienes chats de Telegram vinculados.');
      return;
    }

    setIsLoading(true);
    try {
      await uploadBookFromDevice(
        selectedFile.uri,
        selectedFile.name,
        title.trim(),
        author.trim() || 'Desconocido',
        genre,
        selectedLinkId
      );
      Alert.alert('¡Éxito!', `El libro "${title}" fue subido y enviado al chat de Telegram.`);
      setSelectedFile(null);
      setTitle('');
      setAuthor('');
      setGenre('General');
      onUploadSuccess();
      onClose();
    } catch (e: any) {
      Alert.alert('Error al subir', e.message || 'Ocurrió un error inesperado al subir el libro.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.header}>
          <Text style={styles.headerTitle}>📤 Subir Libro a la Biblioteca</Text>
          <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
            <Text style={styles.closeBtnText}>✕</Text>
          </TouchableOpacity>
        </View>

        <ScrollView contentContainerStyle={styles.container}>
          {/* File Picker Section */}
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>Archivo (PDF o EPUB)</Text>
            <TouchableOpacity onPress={handlePickDocument} style={styles.pickerBox}>
              <Text style={styles.pickerIcon}>{selectedFile ? '📄' : '📁'}</Text>
              <Text style={styles.pickerText} numberOfLines={1}>
                {selectedFile ? selectedFile.name : 'Toca aquí para seleccionar un archivo...'}
              </Text>
              {selectedFile && (
                <Text style={styles.fileSizeText}>
                  {selectedFile.size ? `${(selectedFile.size / (1024 * 1024)).toFixed(2)} MB` : ''}
                </Text>
              )}
            </TouchableOpacity>
          </View>

          {/* Title Input */}
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>Título del Libro *</Text>
            <TextInput
              style={styles.input}
              value={title}
              onChangeText={setTitle}
              placeholder="Ej. Harry Potter y la Piedra Filosofal"
              placeholderTextColor="#64748b"
            />
          </View>

          {/* Author Input */}
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>Autor / Autora</Text>
            <TextInput
              style={styles.input}
              value={author}
              onChangeText={setAuthor}
              placeholder="Ej. J.K. Rowling"
              placeholderTextColor="#64748b"
            />
          </View>

          {/* Genre Selection */}
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>Género / Tema</Text>
            <View style={styles.genreChipsRow}>
              {COMMON_GENRES.map((g) => (
                <TouchableOpacity
                  key={g}
                  onPress={() => setGenre(g)}
                  style={[
                    styles.genreChip,
                    genre === g ? styles.genreChipActive : styles.genreChipInactive,
                  ]}
                >
                  <Text
                    style={[
                      styles.genreChipText,
                      genre === g ? styles.genreChipTextActive : styles.genreChipTextInactive,
                    ]}
                  >
                    {g}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>

          {/* Target Telegram Chat */}
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>Chat de Telegram Destino</Text>
            {telegramLinks.length === 0 ? (
              <Text style={styles.noLinkNotice}>
                ⚠️ No tienes ningún chat vinculado. Se asignará automáticamente al chat predeterminado.
              </Text>
            ) : (
              telegramLinks.map((link) => (
                <TouchableOpacity
                  key={link.id}
                  onPress={() => setSelectedLinkId(link.id)}
                  style={[
                    styles.linkOption,
                    selectedLinkId === link.id ? styles.linkOptionActive : styles.linkOptionInactive,
                  ]}
                >
                  <Text style={styles.linkTitle}>💬 {link.chat_title}</Text>
                  <Text style={styles.linkSub}>
                    {link.forum_enabled ? '🏛️ Forum (Temas)' : '💬 Chat Estándar'}
                  </Text>
                </TouchableOpacity>
              ))
            )}
          </View>

          {/* Submit Button */}
          <TouchableOpacity
            onPress={handleUpload}
            disabled={isLoading}
            style={[styles.uploadButton, isLoading && styles.uploadButtonDisabled]}
          >
            {isLoading ? (
              <ActivityIndicator color="#ffffff" />
            ) : (
              <Text style={styles.uploadButtonText}>🚀 Subir y Sincronizar en Telegram</Text>
            )}
          </TouchableOpacity>
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#0f172a',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#f8fafc',
  },
  closeBtn: {
    padding: 6,
  },
  closeBtnText: {
    fontSize: 18,
    color: '#94a3b8',
    fontWeight: 'bold',
  },
  container: {
    padding: 20,
    paddingBottom: 40,
  },
  section: {
    marginBottom: 20,
  },
  sectionLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#cbd5e1',
    marginBottom: 8,
  },
  pickerBox: {
    backgroundColor: '#1e293b',
    borderWidth: 1.5,
    borderColor: '#4f46e5',
    borderStyle: 'dashed',
    borderRadius: 12,
    padding: 20,
    alignItems: 'center',
  },
  pickerIcon: {
    fontSize: 32,
    marginBottom: 8,
  },
  pickerText: {
    fontSize: 14,
    color: '#f8fafc',
    fontWeight: '600',
  },
  fileSizeText: {
    fontSize: 12,
    color: '#94a3b8',
    marginTop: 4,
  },
  input: {
    backgroundColor: '#1e293b',
    borderWidth: 1,
    borderColor: '#334155',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: '#f8fafc',
    fontSize: 15,
  },
  genreChipsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  genreChip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 20,
    borderWidth: 1,
  },
  genreChipActive: {
    backgroundColor: '#6366f1',
    borderColor: '#818cf8',
  },
  genreChipInactive: {
    backgroundColor: '#1e293b',
    borderColor: '#334155',
  },
  genreChipText: {
    fontSize: 12,
    fontWeight: '600',
  },
  genreChipTextActive: {
    color: '#ffffff',
  },
  genreChipTextInactive: {
    color: '#94a3b8',
  },
  noLinkNotice: {
    color: '#f59e0b',
    fontSize: 13,
  },
  linkOption: {
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    marginBottom: 8,
  },
  linkOptionActive: {
    backgroundColor: '#1e1b4b',
    borderColor: '#6366f1',
  },
  linkOptionInactive: {
    backgroundColor: '#1e293b',
    borderColor: '#334155',
  },
  linkTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#f8fafc',
  },
  linkSub: {
    fontSize: 12,
    color: '#94a3b8',
    marginTop: 2,
  },
  uploadButton: {
    backgroundColor: '#6366f1',
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 10,
  },
  uploadButtonDisabled: {
    opacity: 0.6,
  },
  uploadButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '700',
  },
});
